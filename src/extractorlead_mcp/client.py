"""Cliente HTTP de la API pública v1 de ExtractorLead.

El servidor MCP no toca la base de datos ni los workers: todo pasa por la API
pública con la API key del propio usuario, así que el cobro de créditos, los
límites y la propiedad de las tareas se aplican exactamente igual que para
cualquier integración.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.extractorlead.com"
APP_URL = "https://app.extractorlead.com"

# Campos que jamás deben llegar al modelo: identifican al proveedor de datos.
# La API ya los quita en /tasks; aquí se repite para TODAS las respuestas
# (resultados masivos incluidos), porque lo que devuelve una herramienta MCP lo
# lee el modelo y acaba en la conversación.
PROVIDER_FIELDS = frozenset({
    "source", "photo_url", "logo_url", "company_logo_url",
    "organization_id", "person_id",
})
# Este paquete es público: los campos cuyo nombre ya delata al proveedor se
# comparan por su hash en vez de escribirse.
_PROVIDER_FIELD_HASHES = frozenset({
    "dac0d97dcdc3c9f4025759f7b65af643aeaa90efb570fca93ceb5e9fc10869cd",
})


def _is_provider_field(key: str) -> bool:
    return key in PROVIDER_FIELDS or (
        hashlib.sha256(key.encode()).hexdigest() in _PROVIDER_FIELD_HASHES)


def strip_provider_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_provider_fields(v) for k, v in value.items()
                if not _is_provider_field(k)}
    if isinstance(value, list):
        return [strip_provider_fields(v) for v in value]
    return value


class ExtractorLeadError(Exception):
    """Error de la API con un mensaje pensado para que el modelo lo explique."""

    def __init__(self, code: str, message: str, status: int | None = None,
                 extra: dict | None = None):
        self.code = code
        self.status = status
        self.extra = extra or {}
        super().__init__(f"{code}: {message}")


_HINTS = {
    401: (f"La API key no es válida o falta. Crea una en {APP_URL} (Perfil → API keys) "
          "y configúrala en el conector."),
    402: f"Saldo insuficiente. Se pueden recargar créditos en {APP_URL}/profile.",
    404: "La tarea no existe o pertenece a otra cuenta.",
    429: "Demasiadas peticiones; espera unos segundos y reintenta.",
    503: "Servicio temporalmente no disponible; el trabajo en curso no se ve afectado. Reintenta.",
}


def base_url() -> str:
    return (os.getenv("EXTRACTORLEAD_API_URL") or DEFAULT_BASE_URL).rstrip("/")


class ExtractorLeadClient:
    def __init__(self, api_key: str, url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 55.0):
        if not api_key:
            raise ExtractorLeadError("API_KEY_MISSING", _HINTS[401], 401)
        if not api_key.startswith("sk_live_"):
            raise ExtractorLeadError(
                "API_KEY_INVALID",
                "La API key debe empezar por 'sk_live_'. " + _HINTS[401], 401)
        self._http = httpx.AsyncClient(
            base_url=(url or base_url()) + "/api/v1",
            headers={"X-API-Key": api_key,
                     "User-Agent": "extractorlead-mcp/0.1"},
            # El balanceador corta a los 60s: mejor fallar antes con un
            # mensaje claro que quedarse colgado.
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> "ExtractorLeadClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, *, json: dict | None = None,
                      params: dict | None = None, files: dict | None = None,
                      data: dict | None = None) -> dict:
        try:
            resp = await self._http.request(method, path, json=json, params=params,
                                            files=files, data=data)
        except httpx.TimeoutException:
            raise ExtractorLeadError(
                "TIMEOUT", "La API de ExtractorLead no respondió a tiempo. Reintenta.")
        except httpx.HTTPError as e:
            raise ExtractorLeadError("NETWORK_ERROR",
                                     f"No se pudo conectar con ExtractorLead ({type(e).__name__}).")

        try:
            body = resp.json()
        except ValueError:
            body = None

        if resp.status_code >= 400:
            body = body if isinstance(body, dict) else {}
            code = body.get("error") or f"HTTP_{resp.status_code}"
            message = body.get("message") or resp.reason_phrase
            hint = _HINTS.get(resp.status_code)
            if hint and hint not in message:
                message = f"{message} {hint}"
            extra = {k: v for k, v in body.items() if k not in ("error", "message", "docs")}
            raise ExtractorLeadError(code, message, resp.status_code,
                                     strip_provider_fields(extra))

        if not isinstance(body, dict):
            raise ExtractorLeadError("BAD_RESPONSE", "Respuesta inesperada de la API.",
                                     resp.status_code)
        return strip_provider_fields(body)

    async def get(self, path: str, **params) -> dict:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self.request("GET", path, params=clean or None)

    async def post(self, path: str, body: dict) -> dict:
        return await self.request("POST", path, json=body)

    async def post_file(self, path: str, filename: str, content: bytes,
                        config: dict) -> dict:
        import json as _json
        return await self.request(
            "POST", path,
            files={"file": (filename, content)},
            data={"config": _json.dumps(config)} if config else None)
