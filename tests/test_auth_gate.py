import httpx
import pytest
import respx

from extractorlead_mcp import auth_gate
from extractorlead_mcp.auth_gate import AuthGate
from extractorlead_mcp.client import DEFAULT_BASE_URL
from extractorlead_mcp.guide import BrowserGuide

ACCOUNT = DEFAULT_BASE_URL + "/api/v1/account"
TOKEN = "elo_at_" + "a" * 64


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("EXTRACTORLEAD_API_URL", raising=False)
    monkeypatch.delenv("MCP_PUBLIC_URL", raising=False)
    auth_gate._valid_until.clear()


async def _inner(scope, receive, send):
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"mcp"})


def _client():
    app = BrowserGuide(AuthGate(_inner))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="https://api.extractorlead.com")


async def test_no_credentials_returns_401_with_oauth_discovery():
    async with _client() as c:
        r = await c.post("/mcp", json={})
    assert r.status_code == 401
    header = r.headers["www-authenticate"]
    assert header.startswith("Bearer ")
    assert ('resource_metadata="https://api.extractorlead.com/.well-known/'
            'oauth-protected-resource/mcp"') in header
    assert 'scope="leads"' in header


async def test_api_keys_keep_working_without_validation():
    async with _client() as c:
        for headers, params in (({"X-API-Key": "sk_live_x"}, None),
                                ({"Authorization": "Bearer sk_live_x"}, None),
                                ({}, {"api_key": "sk_live_x"})):
            r = await c.post("/mcp", json={}, headers=headers, params=params)
            assert r.status_code == 200 and r.text == "mcp"


@respx.mock
async def test_oauth_token_is_checked_and_cached():
    route = respx.get(ACCOUNT).mock(return_value=httpx.Response(200, json={}))
    async with _client() as c:
        for _ in range(3):
            r = await c.post("/mcp", json={}, headers={"Authorization": f"Bearer {TOKEN}"})
            assert r.status_code == 200
    assert route.call_count == 1
    assert route.calls[0].request.headers["X-API-Key"] == TOKEN


@respx.mock
async def test_expired_oauth_token_asks_claude_to_refresh():
    respx.get(ACCOUNT).mock(return_value=httpx.Response(401, json={"error": "TOKEN_INVALID"}))
    async with _client() as c:
        r = await c.post("/mcp", json={}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith('Bearer error="invalid_token"')


@respx.mock
async def test_api_outage_does_not_lock_users_out():
    respx.get(ACCOUNT).mock(side_effect=httpx.ConnectError("down"))
    async with _client() as c:
        r = await c.post("/mcp", json={}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


async def test_browser_guide_and_other_paths_are_public():
    async with _client() as c:
        page = await c.get("/mcp", headers={"Accept": "text/html"})
        assert page.status_code == 200 and "Conectar" in page.text
        assert "X-API-Key" not in page.text
        assert (await c.get("/health")).status_code == 200
        assert (await c.options("/mcp")).status_code == 200
