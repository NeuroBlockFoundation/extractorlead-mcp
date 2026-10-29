"""Puerta de autenticación del conector remoto (modo HTTP).

Sin credenciales, /mcp responde 401 con la cabecera WWW-Authenticate que
indica dónde están los metadatos OAuth. Es lo que hace que Claude muestre el
botón "Conectar" y lleve al usuario a iniciar sesión en ExtractorLead, en vez
de pedirle que pegue una API key en algún sitio.

Siguen valiendo, para quien ya las usa:
  - una API key (X-API-Key, Authorization: Bearer o ?api_key=), sin cambios;
  - el access token OAuth (elo_at_...), que se valida contra la API y, si
    caducó o se revocó, se responde 401 invalid_token para que Claude lo
    renueve con su refresh token.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlparse

import httpx

from .client import base_url

ACCESS_PREFIX = "elo_at_"
_CACHE_TTL = 60.0
_CACHE_MAX = 5000
_valid_until: dict[str, float] = {}


def public_url() -> str:
    return (os.getenv("MCP_PUBLIC_URL") or "https://api.extractorlead.com/mcp").rstrip("/")


def resource_metadata_url() -> str:
    override = os.getenv("MCP_RESOURCE_METADATA_URL")
    if override:
        return override
    # En producción /.well-known/* del mismo host lo sirve la API (el ALB solo
    # manda /mcp a este servicio).
    p = urlparse(public_url())
    return f"{p.scheme}://{p.netloc}/.well-known/oauth-protected-resource{p.path}"


def _credential(scope) -> tuple[str, str]:
    """(tipo, valor) de la credencial de la petición, o ("", "")."""
    headers = {k.decode("latin-1").lower(): v.decode("latin-1")
               for k, v in scope.get("headers") or []}
    key = headers.get("x-api-key", "").strip()
    if key:
        return "header", key
    auth = headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer ") and auth[7:].strip():
        return "bearer", auth[7:].strip()
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    key = (query.get("api_key") or [""])[0].strip()
    if key:
        return "query", key
    return "", ""


async def _token_is_valid(token: str, transport: httpx.AsyncBaseTransport | None = None) -> bool | None:
    """True/False según la API; None si no se pudo comprobar (se deja pasar)."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    if _valid_until.get(digest, 0) > now:
        return True
    try:
        async with httpx.AsyncClient(base_url=base_url(), timeout=8.0,
                                     transport=transport) as http:
            resp = await http.get("/api/v1/account", headers={"X-API-Key": token})
    except httpx.HTTPError:
        return None
    if resp.status_code == 401:
        _valid_until.pop(digest, None)
        return False
    if resp.status_code >= 500:
        return None
    if len(_valid_until) >= _CACHE_MAX:
        _valid_until.clear()
    _valid_until[digest] = now + _CACHE_TTL
    return True


async def _unauthorized(send, error: str | None = None) -> None:
    params = [f'resource_metadata="{resource_metadata_url()}"', 'scope="leads"']
    if error:
        params.insert(0, f'error="{error}"')
    body = json.dumps({
        "error": error or "unauthorized",
        "message": "Conecta tu cuenta de ExtractorLead: en Claude pulsa Conectar e "
                   "inicia sesión. / Connect your ExtractorLead account: click "
                   "Connect in Claude and sign in.",
    }).encode()
    await send({"type": "http.response.start", "status": 401, "headers": [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"www-authenticate", ("Bearer " + ", ".join(params)).encode()),
        (b"cache-control", b"no-store"),
    ]})
    await send({"type": "http.response.body", "body": body})


class AuthGate:
    """ASGI: exige credencial en /mcp; el resto (health, guía) pasa tal cual."""

    def __init__(self, app, transport: httpx.AsyncBaseTransport | None = None):
        self.app = app
        self._transport = transport

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("method") == "OPTIONS"
                or scope.get("path", "").rstrip("/") != "/mcp"):
            return await self.app(scope, receive, send)

        _, value = _credential(scope)
        if not value:
            return await _unauthorized(send)
        if value.startswith(ACCESS_PREFIX):
            if await _token_is_valid(value, self._transport) is False:
                return await _unauthorized(send, "invalid_token")
        return await self.app(scope, receive, send)
