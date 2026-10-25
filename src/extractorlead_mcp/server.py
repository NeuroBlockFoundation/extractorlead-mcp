"""Servidor MCP de ExtractorLead.

Expone la API pública v1 como herramientas para Claude. Dos modos:

  stdio  Claude Desktop / Claude Code en local. La API key sale de la variable
         de entorno EXTRACTORLEAD_API_KEY y el servidor puede leer ficheros
         CSV/XLSX del disco del usuario.
  http   Conector remoto (claude.ai, Claude Desktop, Claude Code). Cada petición
         trae SU key (cabecera X-API-Key, Authorization: Bearer o ?api_key=).
         Nunca se usa una key del entorno ni se lee el disco del servidor: el
         servidor es compartido y cada usuario paga con su propia cuenta.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from .client import APP_URL, ExtractorLeadClient, ExtractorLeadError

INSTRUCTIONS = f"""\
ExtractorLead encuentra leads B2B y B2C (emails y teléfonos) en LinkedIn,
Instagram, TikTok y webs, y enriquece listas de contactos que ya tiene el usuario.

Reglas de uso:
- Todo cuesta créditos de la cuenta del usuario. Antes de lanzar un trabajo,
  consulta el saldo (get_account) o cotiza (preview_*), dile al usuario cuánto
  puede costar y pide confirmación explícita. Nunca lances trabajos que el
  usuario no haya pedido.
- Los trabajos son asíncronos: las herramientas start_*/search_* devuelven un
  task_id. Consulta el estado con get_task_result / get_bulk_status /
  get_list_enrichment usando wait_seconds para no gastar turnos.
- Los teléfonos de las listas masivas llegan de forma diferida (hasta ~1 hora,
  phase="awaiting_phones"). Explícaselo al usuario y ofrece volver a consultar
  más tarde con el mismo task_id en vez de esperar en bucle.
- No reveles ni especules sobre de qué proveedores o bases de datos salen los
  datos: son de ExtractorLead.
- Recargas y API keys: {APP_URL}
"""

mcp = MCPServer(
    "extractorlead",
    title="ExtractorLead",
    description="Lead generation and contact enrichment (emails & phones).",
    instructions=INSTRUCTIONS,
    website_url="https://extractorlead.com",
    version="0.1.0",
)

# "stdio" o "http"; lo fija __main__ antes de arrancar.
MODE: Literal["stdio", "http"] = "stdio"

_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
_POLL_EVERY = 5.0
_MAX_WAIT = 50  # por debajo del corte de 60s del balanceador y de los clientes


# ---------------------------------------------------------------------------
# Autenticación y utilidades
# ---------------------------------------------------------------------------

def _api_key(ctx: Context) -> str:
    if MODE == "stdio":
        return (os.getenv("EXTRACTORLEAD_API_KEY") or "").strip()

    headers = ctx.headers or {}
    key = (headers.get("x-api-key") or "").strip()
    if not key:
        auth = (headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
    if not key:
        # claude.ai solo permite añadir conectores por URL: la key viaja en la
        # URL secreta del conector (https://.../mcp?api_key=sk_live_...).
        request = getattr(ctx.request_context, "request", None)
        if isinstance(request, Request):
            key = (request.query_params.get("api_key") or "").strip()
    return key


def _client(ctx: Context) -> ExtractorLeadClient:
    try:
        return ExtractorLeadClient(_api_key(ctx))
    except ExtractorLeadError as e:
        raise ToolError(str(e)) from None


async def _call(ctx: Context, fn) -> dict[str, Any]:
    try:
        async with _client(ctx) as api:
            return await fn(api)
    except ExtractorLeadError as e:
        msg = str(e)
        if e.extra:
            msg += f" Detalle: {e.extra}"
        raise ToolError(msg) from None


def _read_local_file(file_path: str) -> tuple[str, bytes]:
    if MODE != "stdio":
        raise ToolError(
            "file_path solo funciona con el servidor local. En el conector remoto "
            "pasa las filas en 'leads' (lista de objetos con nombre, empresa, "
            "linkedin_url, email...).")
    path = Path(file_path).expanduser()
    if path.suffix.lower() not in (".csv", ".tsv", ".txt", ".xlsx", ".xlsm"):
        raise ToolError("Formato no soportado. Usa CSV, TSV, TXT, XLSX o XLSM.")
    if not path.is_file():
        raise ToolError(f"No existe el fichero: {path}")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ToolError("El fichero supera el límite de 20 MB.")
    return path.name, path.read_bytes()


def _list_input(leads: list[dict[str, Any]] | None, file_path: str | None):
    if bool(leads) == bool(file_path):
        raise ToolError("Indica 'leads' (lista de filas) o 'file_path', uno de los dos.")
    return (None if leads else _read_local_file(file_path))


async def _send_list(api: ExtractorLeadClient, path: str,
                     leads: list[dict[str, Any]] | None, file_path: str | None,
                     config: dict[str, Any]) -> dict[str, Any]:
    config = {k: v for k, v in config.items() if v is not None}
    upload = _list_input(leads, file_path)
    if upload:
        return await api.post_file(path, upload[0], upload[1], config)
    return await api.post(path, {"leads": leads, "config": config})


async def _poll(get, wait_seconds: int, is_done) -> dict[str, Any]:
    """Consulta hasta que el trabajo termina o se agota la espera."""
    wait = max(0, min(int(wait_seconds or 0), _MAX_WAIT))
    deadline = anyio.current_time() + wait
    body = await get()
    while not is_done(body) and anyio.current_time() + _POLL_EVERY <= deadline:
        await anyio.sleep(_POLL_EVERY)
        body = await get()
    return body


def _paginate_lists(result: Any, offset: int, limit: int) -> tuple[Any, dict | None]:
    """Recorta las listas largas del resultado para no desbordar el contexto."""
    if not isinstance(result, dict):
        return result, None
    page = None
    out = {}
    for k, v in result.items():
        if isinstance(v, list) and len(v) > limit:
            out[k] = v[offset:offset + limit]
            page = {"field": k, "total": len(v), "offset": offset,
                    "returned": len(out[k]),
                    "has_more": offset + limit < len(v)}
        else:
            out[k] = v
    return out, page


_SPENDS = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                          idempotent_hint=False, open_world_hint=True)
_READS = ToolAnnotations(read_only_hint=True, open_world_hint=True)


# ---------------------------------------------------------------------------
# Cuenta
# ---------------------------------------------------------------------------

@mcp.tool(title="Saldo y plan", annotations=_READS)
async def get_account(ctx: Context) -> dict[str, Any]:
    """Saldo de créditos y estado de la suscripción de ExtractorLead.

    Úsalo antes de lanzar cualquier trabajo para saber si hay saldo suficiente.
    """
    return await _call(ctx, lambda api: api.get("/account"))


# ---------------------------------------------------------------------------
# Búsquedas de leads por nicho
# ---------------------------------------------------------------------------

@mcp.tool(title="Buscar leads por nicho", annotations=_SPENDS)
async def search_leads(
    ctx: Context,
    channel: Literal["linkedin", "instagram", "tiktok"],
    contact: Literal["emails", "phones"],
    niche: str,
    location: str,
    lead_count: int = 25,
    country: str | None = None,
) -> dict[str, Any]:
    """Busca leads nuevos de un nicho en una zona. Consume créditos.

    - channel: "linkedin" para B2B (cargos, empresas), "instagram"/"tiktok" para
      creadores y negocios locales.
    - contact: "emails" o "phones".
    - niche: a quién buscas, p.ej. "directores de marketing de SaaS" o
      "clínicas dentales".
    - location: ciudad, región o país, p.ej. "Madrid".
    - lead_count: 1..500 (por defecto 25).
    - country: código ISO de 2 letras, solo para linkedin+phones (p.ej. "es").

    Devuelve un task_id; recoge los leads con get_task_result.
    Pide confirmación al usuario antes de llamarla.
    """
    if not 1 <= lead_count <= 500:
        raise ToolError("lead_count debe estar entre 1 y 500.")
    body: dict[str, Any] = {"niche": niche, "location": location, "lead_count": lead_count}
    if country and channel == "linkedin" and contact == "phones":
        body["country"] = country
    return await _call(ctx, lambda api: api.post(f"/{channel}/{contact}", body))


@mcp.tool(title="Enriquecer perfil de LinkedIn", annotations=_SPENDS)
async def lookup_linkedin_profile(ctx: Context, linkedin_url: str) -> dict[str, Any]:
    """Obtiene email, teléfono y datos profesionales de UN perfil de LinkedIn.

    linkedin_url: https://www.linkedin.com/in/<usuario>/
    Devuelve un task_id; el resultado se recoge con get_task_result.
    """
    if "linkedin.com/in/" not in linkedin_url:
        raise ToolError("Debe ser una URL de perfil: https://www.linkedin.com/in/<usuario>/")
    return await _call(ctx, lambda api: api.post("/linkedin/profile", {"url": linkedin_url}))


@mcp.tool(title="Analizar web", annotations=_SPENDS)
async def analyze_website(ctx: Context, url: str, language: str = "es") -> dict[str, Any]:
    """Analiza una web: contactos (emails, teléfonos, redes), negocio y servicios.

    url debe incluir http:// o https://. Devuelve un task_id para get_task_result.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return await _call(ctx, lambda api: api.post("/web/analyze",
                                                 {"url": url, "language": language}))


@mcp.tool(title="Resultado de una búsqueda", annotations=_READS)
async def get_task_result(
    ctx: Context,
    task_id: str,
    wait_seconds: int = 30,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Estado y resultado de search_leads, lookup_linkedin_profile o analyze_website.

    - wait_seconds: espera hasta 50s a que termine antes de responder.
    - offset/limit: paginación de la lista de leads cuando es larga.
    status: PENDING | PROCESSING | COMPLETED | FAILED | CANCELLED.
    """
    async def run(api: ExtractorLeadClient):
        body = await _poll(lambda: api.get(f"/tasks/{task_id}"), wait_seconds,
                           lambda b: b.get("status") in _TERMINAL)
        result, page = _paginate_lists(body.get("result"), max(0, offset),
                                       max(1, min(limit, 200)))
        body["result"] = result
        if page:
            body["pagination"] = page
        return body
    return await _call(ctx, run)


# ---------------------------------------------------------------------------
# Enriquecimiento masivo: lista de personas → emails y teléfonos
# ---------------------------------------------------------------------------

_LEADS_DOC = """
    Entrada (una de las dos):
    - leads: lista de filas, cada una con los campos que tenga: first_name,
      last_name, full_name, company, domain, title, linkedin_url, email,
      location. También valen cabeceras en español (Nombre, Apellido, Cargo,
      Empresa, LinkedIn...). Máx. 5000 filas.
    - file_path: ruta a un CSV/XLSX local (solo servidor local; un export de
      Sales Navigator vale tal cual).
    Opciones:
    - contact_info: "all_contact_info" (por defecto: pide el teléfono y entrega
      el email solo de quien tiene teléfono), "phone_info" o "email_info".
    - match_mode: "strict" (la persona exacta) o "related" (además otros
      contactos análogos de la misma empresa, usando el cargo como semilla).
    - related_per_company: 1..10 contactos análogos por empresa (con related).
    - require_mobile: true para contar solo móviles, no centralitas.
    Precio por contacto ENTREGADO: solo email 2, solo teléfono 3, ambos 4,
    nada 0 créditos."""


def _bulk_config(contact_info, match_mode, related_per_company, require_mobile):
    return {"contact_info": contact_info, "match_mode": match_mode,
            "related_per_company": related_per_company,
            "require_mobile": require_mobile}


_PREVIEW_BULK_DOC = """Valida una lista de personas y calcula el coste máximo. NO cobra nada.

    Úsalo SIEMPRE antes de start_bulk_enrichment y enseña al usuario
    rows_accepted, max_credits y available_credits.
""" + _LEADS_DOC

_START_BULK_DOC = """Lanza el enriquecimiento de una lista de personas. Consume créditos.

    Solo tras preview_bulk_enrichment y con la confirmación del usuario.
    Devuelve un task_id; sigue el trabajo con get_bulk_status.
""" + _LEADS_DOC


@mcp.tool(title="Cotizar enriquecimiento masivo", annotations=_READS,
          description=_PREVIEW_BULK_DOC)
async def preview_bulk_enrichment(
    ctx: Context,
    leads: list[dict[str, Any]] | None = None,
    file_path: str | None = None,
    contact_info: Literal["all_contact_info", "phone_info", "email_info"] = "all_contact_info",
    match_mode: Literal["strict", "related"] = "strict",
    related_per_company: int | None = None,
    require_mobile: bool | None = None,
) -> dict[str, Any]:
    cfg = _bulk_config(contact_info, match_mode, related_per_company, require_mobile)
    return await _call(ctx, lambda api: _send_list(api, "/leads/bulk/preview",
                                                   leads, file_path, cfg))


@mcp.tool(title="Lanzar enriquecimiento masivo", annotations=_SPENDS,
          description=_START_BULK_DOC)
async def start_bulk_enrichment(
    ctx: Context,
    leads: list[dict[str, Any]] | None = None,
    file_path: str | None = None,
    contact_info: Literal["all_contact_info", "phone_info", "email_info"] = "all_contact_info",
    match_mode: Literal["strict", "related"] = "strict",
    related_per_company: int | None = None,
    require_mobile: bool | None = None,
) -> dict[str, Any]:
    cfg = _bulk_config(contact_info, match_mode, related_per_company, require_mobile)
    return await _call(ctx, lambda api: _send_list(api, "/leads/bulk",
                                                   leads, file_path, cfg))


@mcp.tool(title="Estado del enriquecimiento masivo", annotations=_READS)
async def get_bulk_status(ctx: Context, task_id: str, wait_seconds: int = 30) -> dict[str, Any]:
    """Contadores de un trabajo masivo (nunca la lista).

    phase: processing | awaiting_phones | completed. Con partial=true ya se
    pueden leer los leads decididos con get_bulk_results. Los teléfonos pueden
    tardar hasta ~1 hora: si phase es awaiting_phones, avisa al usuario y
    vuelve a consultar más tarde en lugar de esperar en bucle.
    """
    async def run(api: ExtractorLeadClient):
        return await _poll(lambda: api.get(f"/leads/bulk/{task_id}"), wait_seconds,
                           lambda b: b.get("status") in _TERMINAL or b.get("partial"))
    return await _call(ctx, run)


@mcp.tool(title="Leads del enriquecimiento masivo", annotations=_READS)
async def get_bulk_results(
    ctx: Context,
    task_id: str,
    page: int = 1,
    per_page: int = 50,
    only: Literal["all", "with_phone", "with_email", "with_both"] = "all",
    match: Literal["all", "exact", "related"] = "all",
) -> dict[str, Any]:
    """Leads enriquecidos de un trabajo masivo, paginados (per_page máx. 200).

    Para listas grandes ofrece al usuario get_bulk_download_link en vez de
    paginar todo en la conversación.
    """
    per_page = max(1, min(per_page, 200))
    return await _call(ctx, lambda api: api.get(
        f"/leads/bulk/{task_id}/results", page=page, per_page=per_page,
        only=only, match=match))


@mcp.tool(title="Enlace de descarga (masivo)", annotations=_READS)
async def get_bulk_download_link(ctx: Context, task_id: str) -> dict[str, Any]:
    """Enlace temporal (15 min) para descargar todos los leads del trabajo en JSON."""
    return await _call(ctx, lambda api: api.get(f"/leads/bulk/{task_id}/download"))


# ---------------------------------------------------------------------------
# Enriquecer una lista existente: rellena huecos y devuelve el Excel editado
# ---------------------------------------------------------------------------

def _enrich_config(wants_phone, phone_for_all, credit_cap=None):
    return {"wants_phone": wants_phone, "phone_for_all": phone_for_all,
            "credit_cap": credit_cap}


@mcp.tool(title="Cotizar relleno de lista", annotations=_READS)
async def preview_list_enrichment(
    ctx: Context,
    leads: list[dict[str, Any]] | None = None,
    file_path: str | None = None,
    wants_phone: bool = True,
    phone_for_all: bool = False,
) -> dict[str, Any]:
    """Analiza una lista propia (CRM, Excel) y cotiza rellenar sus huecos. NO cobra.

    A diferencia del enriquecimiento masivo, conserva las columnas del usuario
    y devuelve su mismo Excel con columnas nuevas. Devuelve columnas
    detectadas, huecos (sin_telefono, sin_email...), coste y tope_sugerido.
    - phone_for_all: true para buscar teléfono también en filas que ya traen uno
      (p.ej. cuando son centralitas).
    """
    cfg = _enrich_config(wants_phone, phone_for_all)
    return await _call(ctx, lambda api: _send_list(api, "/leads/enrich/preview",
                                                   leads, file_path, cfg))


@mcp.tool(title="Lanzar relleno de lista", annotations=_SPENDS)
async def start_list_enrichment(
    ctx: Context,
    credit_cap: int,
    leads: list[dict[str, Any]] | None = None,
    file_path: str | None = None,
    wants_phone: bool = True,
    phone_for_all: bool = False,
) -> dict[str, Any]:
    """Lanza el relleno de huecos de una lista. Consume créditos hasta credit_cap.

    credit_cap: tope de gasto que el usuario ha aprobado (usa el tope_sugerido
    de preview_list_enrichment si no dice otro). Sigue el trabajo con
    get_list_enrichment.
    """
    if credit_cap <= 0:
        raise ToolError("credit_cap debe ser mayor que 0.")
    cfg = _enrich_config(wants_phone, phone_for_all, credit_cap)
    return await _call(ctx, lambda api: _send_list(api, "/leads/enrich",
                                                   leads, file_path, cfg))


@mcp.tool(title="Estado del relleno de lista", annotations=_READS)
async def get_list_enrichment(
    ctx: Context,
    task_id: str,
    wait_seconds: int = 30,
    include_rows: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Estado del relleno de lista; al terminar, resumen y enlace al Excel editado.

    include_rows=true añade las filas (paginadas con offset/limit, máx. 200).
    """
    async def run(api: ExtractorLeadClient):
        params = {}
        if include_rows:
            params = {"include": "filas", "offset": max(0, offset),
                      "limit": max(1, min(limit, 200))}
        body = await _poll(lambda: api.get(f"/leads/enrich/{task_id}", **params),
                           wait_seconds,
                           lambda b: str(b.get("status")).upper() in _TERMINAL)
        if body.get("xlsx_disponible"):
            try:
                link = await api.get(f"/leads/enrich/{task_id}/download")
                body["download_url"] = link.get("download_url")
                body["download_expires_in"] = link.get("expires_in")
            except ExtractorLeadError:
                body["download_url"] = None
        return body
    return await _call(ctx, run)


# ---------------------------------------------------------------------------
# Prompts y salud
# ---------------------------------------------------------------------------

@mcp.prompt(title="Prospectar un nicho")
def prospect(niche: str, location: str) -> str:
    """Plantilla para buscar leads de un nicho con confirmación de coste."""
    return (f"Quiero leads de «{niche}» en {location}. Mira mi saldo en "
            "ExtractorLead, propónme el canal (LinkedIn, Instagram o TikTok), el tipo de "
            "contacto y cuántos leads, dime el coste y espera mi confirmación antes de lanzar.")


@mcp.prompt(title="Enriquecer mi lista")
def enrich_my_list() -> str:
    """Plantilla para enriquecer una lista de contactos propia."""
    return ("Quiero enriquecer una lista de contactos con ExtractorLead. Cotízala primero, "
            "explícame qué se va a rellenar y cuánto costará como máximo, y no lances "
            "nada hasta que confirme.")


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})
