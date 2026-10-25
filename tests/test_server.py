import json
import socket
import threading
import time

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from extractorlead_mcp import server
from extractorlead_mcp.client import DEFAULT_BASE_URL

API = DEFAULT_BASE_URL + "/api/v1"
KEY = "sk_live_test123"


@pytest.fixture(autouse=True)
def stdio_mode(monkeypatch):
    monkeypatch.setattr(server, "MODE", "stdio")
    monkeypatch.setattr(server, "_POLL_EVERY", 0.01)
    monkeypatch.setenv("EXTRACTORLEAD_API_KEY", KEY)
    monkeypatch.delenv("EXTRACTORLEAD_API_URL", raising=False)


def _payload(result):
    return json.loads(result.content[0].text)


async def _call(name, args=None):
    async with Client(server.mcp) as c:
        return await c.call_tool(name, args or {})


@respx.mock
async def test_account_sends_key_and_strips_provider_fields():
    route = respx.get(f"{API}/account").mock(return_value=httpx.Response(
        200, json={"tokens_balance": 40, "source": "secret",
                   "nested": [{"organization_id": 1, "ok": 2}]}))
    res = await _call("get_account")
    assert not res.is_error
    assert _payload(res) == {"tokens_balance": 40, "nested": [{"ok": 2}]}
    assert route.calls[0].request.headers["X-API-Key"] == KEY


@respx.mock
async def test_search_leads_routes_by_channel_and_contact():
    route = respx.post(f"{API}/instagram/phones").mock(return_value=httpx.Response(
        202, json={"task_id": "task_1_abc", "status": "queued"}))
    res = await _call("search_leads", {"channel": "instagram", "contact": "phones",
                                        "niche": "clínicas dentales", "location": "Madrid",
                                        "country": "es"})
    assert _payload(res)["task_id"] == "task_1_abc"
    body = json.loads(route.calls[0].request.content)
    # country solo aplica a linkedin+phones
    assert body == {"niche": "clínicas dentales", "location": "Madrid", "lead_count": 25}


@respx.mock
async def test_api_error_becomes_tool_error_with_hint():
    respx.post(f"{API}/linkedin/emails").mock(return_value=httpx.Response(
        402, json={"error": "INSUFFICIENT_BALANCE", "message": "No balance."}))
    res = await _call("search_leads", {"channel": "linkedin", "contact": "emails",
                                        "niche": "CTOs", "location": "Madrid"})
    assert res.is_error
    text = res.content[0].text
    assert "INSUFFICIENT_BALANCE" in text and "app.extractorlead.com" in text


async def test_missing_key(monkeypatch):
    monkeypatch.delenv("EXTRACTORLEAD_API_KEY")
    res = await _call("get_account")
    assert res.is_error and "API_KEY_MISSING" in res.content[0].text


@respx.mock
async def test_get_task_polls_until_done_and_paginates():
    profiles = [{"name": f"p{i}", "photo_url": "x"} for i in range(120)]
    respx.get(f"{API}/tasks/task_1_abc").mock(side_effect=[
        httpx.Response(200, json={"status": "PROCESSING", "result": None}),
        httpx.Response(200, json={"status": "COMPLETED", "result": {"profiles": profiles}}),
    ])
    res = await _call("get_task_result", {"task_id": "task_1_abc", "wait_seconds": 5,
                                           "offset": 100, "limit": 50})
    body = _payload(res)
    assert body["status"] == "COMPLETED"
    assert [p["name"] for p in body["result"]["profiles"]] == [f"p{i}" for i in range(100, 120)]
    assert "photo_url" not in body["result"]["profiles"][0]
    assert body["pagination"] == {"field": "profiles", "total": 120, "offset": 100,
                                  "returned": 20, "has_more": False}


@respx.mock
async def test_bulk_preview_json_rows():
    route = respx.post(f"{API}/leads/bulk/preview").mock(return_value=httpx.Response(
        200, json={"rows_accepted": 1, "max_credits": 4}))
    leads = [{"first_name": "Ana", "company": "Acme"}]
    res = await _call("preview_bulk_enrichment", {"leads": leads, "match_mode": "related",
                                                   "related_per_company": 3})
    assert _payload(res)["max_credits"] == 4
    sent = json.loads(route.calls[0].request.content)
    assert sent["leads"] == leads
    assert sent["config"] == {"contact_info": "all_contact_info", "match_mode": "related",
                              "related_per_company": 3}


@respx.mock
async def test_bulk_file_upload_in_stdio(tmp_path):
    f = tmp_path / "leads.csv"
    f.write_text("Nombre,Empresa\nAna,Acme\n", encoding="utf-8")
    route = respx.post(f"{API}/leads/bulk").mock(return_value=httpx.Response(
        202, json={"task_id": "task_1_b"}))
    res = await _call("start_bulk_enrichment", {"file_path": str(f)})
    assert not res.is_error
    req = route.calls[0].request
    assert req.headers["content-type"].startswith("multipart/form-data")
    assert b"Ana,Acme" in req.content


async def test_file_path_refused_in_http_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "MODE", "http")
    f = tmp_path / "x.csv"
    f.write_text("a\n")
    # El servidor remoto es compartido: leer su disco sería una fuga.
    with pytest.raises(ToolError, match="solo funciona con el servidor local"):
        server._read_local_file(str(f))


async def test_leads_xor_file():
    res = await _call("preview_bulk_enrichment", {})
    assert res.is_error and "uno de los dos" in res.content[0].text


@respx.mock
async def test_list_enrichment_adds_download_link():
    respx.get(f"{API}/leads/enrich/task_1_e").mock(return_value=httpx.Response(
        200, json={"status": "COMPLETED", "xlsx_disponible": True}))
    respx.get(f"{API}/leads/enrich/task_1_e/download").mock(return_value=httpx.Response(
        200, json={"download_url": "https://s3/x.xlsx", "expires_in": 3600}))
    body = _payload(await _call("get_list_enrichment", {"task_id": "task_1_e",
                                                         "wait_seconds": 0}))
    assert body["download_url"] == "https://s3/x.xlsx"


# ---------------------------------------------------------------------------
# Modo HTTP real: la key llega por petición y nunca del entorno
# ---------------------------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(monkeypatch):
    import uvicorn
    monkeypatch.setattr(server, "MODE", "http")
    # Una key en el entorno del servidor compartido NO debe usarse nunca.
    monkeypatch.setenv("EXTRACTORLEAD_API_KEY", "sk_live_SERVER_ENV")
    port = _free_port()
    from extractorlead_mcp.guide import BrowserGuide
    app = BrowserGuide(server.mcp.streamable_http_app(stateless_http=True,
                                                      json_response=True, host="0.0.0.0"))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(5)


async def _http_call(url, headers=None):
    import httpx2
    from mcp.client.streamable_http import streamable_http_client
    async with httpx2.AsyncClient(headers=headers or {}) as http:
        async with Client(streamable_http_client(url, http_client=http)) as c:
            return await c.call_tool("get_account", {})


@pytest.mark.parametrize("how", ["header", "bearer", "query"])
@respx.mock
async def test_http_mode_uses_per_request_key(http_server, how):
    route = respx.get(f"{API}/account").mock(return_value=httpx.Response(
        200, json={"tokens_balance": 7}))
    url, headers = f"{http_server}/mcp", {}
    if how == "header":
        headers = {"X-API-Key": "sk_live_user_a"}
    elif how == "bearer":
        headers = {"Authorization": "Bearer sk_live_user_a"}
    else:
        url += "?api_key=sk_live_user_a"
    res = await _http_call(url, headers)
    assert not res.is_error, res.content
    assert route.calls[-1].request.headers["X-API-Key"] == "sk_live_user_a"


@respx.mock
async def test_http_mode_without_key_never_falls_back_to_env(http_server):
    route = respx.get(f"{API}/account").mock(return_value=httpx.Response(200, json={}))
    res = await _http_call(f"{http_server}/mcp")
    assert res.is_error and "API_KEY_MISSING" in res.content[0].text
    assert not route.called


def test_health(http_server):
    import httpx2
    assert httpx2.get(f"{http_server}/health").json() == {"status": "ok"}


def test_hashed_provider_field_is_stripped():
    from extractorlead_mcp.client import strip_provider_fields
    hidden = bytes.fromhex("61706f6c6c6f5f6964").decode()
    assert strip_provider_fields({hidden: 1, "email": "a@b.c"}) == {"email": "a@b.c"}


def test_browser_gets_the_guide_in_its_language(http_server):
    import httpx2
    r = httpx2.get(f"{http_server}/mcp", headers={
        "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-GB,en;q=0.9"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Connect ExtractorLead to Claude" in r.text
    assert "https://api.extractorlead.com/mcp" in r.text
    r = httpx2.get(f"{http_server}/mcp", headers={"Accept": "text/html", "Accept-Language": "fr"})
    assert "Conecta ExtractorLead con Claude" in r.text


def test_mcp_clients_are_not_affected_by_the_guide(http_server):
    import httpx2
    # Un GET de cliente MCP (SSE) sigue yendo al servidor MCP, no a la guia.
    # Un GET SSE abre un stream que no se cierra solo: basta con las cabeceras.
    with httpx2.stream("GET", f"{http_server}/mcp", headers={"Accept": "text/event-stream"},
                       timeout=5) as r:
        assert "text/html" not in r.headers.get("content-type", "")
