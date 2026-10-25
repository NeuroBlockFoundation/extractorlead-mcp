"""La página que ve quien abre la URL del conector en un navegador.

`/mcp` es un endpoint MCP: a un navegador le responde 406 con un JSON-RPC que
no explica nada. Esta capa intercepta SOLO las peticiones de navegador (GET que
acepta text/html y no text/event-stream) y les sirve una guía para conectar
ExtractorLead a Claude. Los clientes MCP no mandan `Accept: text/html`, así que
para ellos no cambia nada.
"""
from __future__ import annotations

import html

from .client import APP_URL

MCP_URL = "https://api.extractorlead.com/mcp"
SKILL_URL = ("https://github.com/NeuroBlockFoundation/extractorlead-mcp/"
             "releases/latest/download/extractorlead-skill.zip")
REPO_URL = "https://github.com/NeuroBlockFoundation/extractorlead-mcp"

_TEXTS = {
    "es": {
        "title": "Conecta ExtractorLead con Claude",
        "lead": ("Esta dirección es el conector de ExtractorLead para Claude. No es una "
                 "página web: se pega en Claude y desde ahí puedes buscar leads, "
                 "enriquecer tus listas y consultar tu saldo hablando con él."),
        "url": "URL del conector",
        "copy": "Copiar",
        "copied": "Copiado",
        "s1": "Crea tu API key",
        "s1d": ("En <a href=\"{app}/profile\">app.extractorlead.com</a> → Perfil → API keys. "
                "Empieza por <code>sk_live_</code>. Guárdala: solo se muestra una vez."),
        "s2": "Añade el conector en claude.ai o Claude Desktop",
        "s2d": ("<b>Personalizar → Conectores → Añadir → Añadir conector personalizado</b>. "
                "Pega la URL de arriba, en Autenticación elige <b>Sin inicio de sesión</b> y "
                "en <b>Cabeceras de la petición</b> añade <code>X-API-Key</code> con tu key. "
                "En Team/Enterprise lo añade un Owner desde Configuración de la organización."),
        "s3": "Sube la skill (recomendado)",
        "s3d": ("Descarga <a href=\"{skill}\">extractorlead-skill.zip</a> y súbela en "
                "<b>Personalizar → Skills → + → Subir una skill</b>. Enseña a Claude a "
                "cotizar antes de gastar y a seguir los trabajos largos."),
        "s4": "¿Usas Claude Code?",
        "s4d": "Un comando y listo:",
        "s4p": "O el plugin, que trae el conector y la skill juntos:",
        "try": "Pruébalo",
        "ex": ["¿Cuántos créditos me quedan en ExtractorLead?",
               "Búscame 25 emails de directores de marketing de empresas SaaS en Madrid.",
               "Te paso mi export de Sales Navigator: cotízame teléfonos y emails."],
        "note": ("Todo lo que Claude lance se cobra de tus créditos, igual que en la app, "
                 "y siempre te pedirá confirmación antes de gastar."),
        "more": "Guía completa y código",
    },
    "en": {
        "title": "Connect ExtractorLead to Claude",
        "lead": ("This address is ExtractorLead's connector for Claude. It isn't a web "
                 "page: you add it to Claude, then find leads, enrich your lists and "
                 "check your balance just by asking."),
        "url": "Connector URL",
        "copy": "Copy",
        "copied": "Copied",
        "s1": "Create your API key",
        "s1d": ("At <a href=\"{app}/profile\">app.extractorlead.com</a> → Profile → API keys. "
                "It starts with <code>sk_live_</code>. Save it: it's shown only once."),
        "s2": "Add the connector in claude.ai or Claude Desktop",
        "s2d": ("<b>Customize → Connectors → Add → Add custom connector</b>. Paste the URL "
                "above, set Authentication to <b>No sign in</b> and under <b>Request "
                "headers</b> add <code>X-API-Key</code> with your key. On Team/Enterprise "
                "an Owner adds it from Organization settings."),
        "s3": "Upload the skill (recommended)",
        "s3d": ("Download <a href=\"{skill}\">extractorlead-skill.zip</a> and upload it at "
                "<b>Customize → Skills → + → Upload a skill</b>. It teaches Claude to quote "
                "before spending and to follow long-running jobs."),
        "s4": "Using Claude Code?",
        "s4d": "One command:",
        "s4p": "Or the plugin, which bundles the connector and the skill:",
        "try": "Try it",
        "ex": ["How many ExtractorLead credits do I have left?",
               "Find me 25 emails of marketing directors at SaaS companies in Madrid.",
               "Here's my Sales Navigator export: quote phones and emails for it."],
        "note": ("Everything Claude runs is billed to your credits, just like in the app, "
                 "and it always asks before spending."),
        "more": "Full guide and source code",
    },
}

_CLI = (f'claude mcp add --transport http extractorlead {MCP_URL} '
        f'--header "X-API-Key: sk_live_..."')
_PLUGIN = ("/plugin marketplace add NeuroBlockFoundation/extractorlead-mcp\n"
           "/plugin install extractorlead@extractorlead")


def pick_language(accept_language: str) -> str:
    """El primer idioma del navegador que tengamos; español por defecto."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in _TEXTS:
            return code
    return "es"


def render(lang: str) -> str:
    t = _TEXTS.get(lang, _TEXTS["es"])
    fmt = {"app": APP_URL, "skill": SKILL_URL}

    def copy_block(text: str, multiline: bool = False) -> str:
        tag = "pre" if multiline else "code"
        return (f'<div class="copy"><{tag} class="mono">{html.escape(text)}</{tag}>'
                f'<button type="button" data-copy="{html.escape(text, quote=True)}">'
                f'{t["copy"]}</button></div>')

    examples = "".join(f"<li>{html.escape(e)}</li>" for e in t["ex"])
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["title"]}</title>
<meta name="robots" content="noindex">
<link rel="icon" href="{APP_URL}/extractor-icon.png">
<style>
:root {{
  --bg: #f5f5f7; --card: #ffffff; --text: #1d1d1f; --muted: #6e6e73;
  --line: rgba(0,0,0,.08); --primary: #007AFF; --primary-soft: #e8f2ff; --code: rgba(0,0,0,.05);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #000000; --card: #1c1c1e; --text: #f5f5f7; --muted: #98989d;
    --line: rgba(255,255,255,.1); --primary: #0A84FF; --primary-soft: rgba(10,132,255,.15);
    --code: rgba(255,255,255,.07);
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}}
main {{ max-width: 680px; margin: 0 auto; padding: 48px 16px 64px; }}
header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }}
header img {{ width: 40px; height: 40px; border-radius: 10px; }}
h1 {{ font-size: 26px; letter-spacing: -.02em; margin: 0; }}
.lead {{ color: var(--muted); margin: 0 0 28px; }}
.card {{ background: var(--card); border-radius: 16px; padding: 20px; margin-bottom: 16px;
         border: 1px solid var(--line); }}
.label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted);
          margin: 0 0 8px; font-weight: 600; }}
ol {{ list-style: none; padding: 0; margin: 0; counter-reset: s; }}
ol > li {{ counter-increment: s; position: relative; padding-left: 40px; margin-bottom: 22px; }}
ol > li:last-child {{ margin-bottom: 0; }}
ol > li::before {{ content: counter(s); position: absolute; left: 0; top: 0; width: 26px; height: 26px;
  border-radius: 50%; background: var(--primary-soft); color: var(--primary); font-weight: 600;
  font-size: 13px; display: flex; align-items: center; justify-content: center; }}
h2 {{ font-size: 15px; margin: 0 0 4px; }}
p {{ margin: 0 0 8px; }}
a {{ color: var(--primary); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }}
p code {{ background: var(--code); padding: 1px 5px; border-radius: 5px; }}
.copy {{ display: flex; align-items: flex-start; gap: 8px; background: var(--code); border-radius: 10px;
         padding: 10px 10px 10px 12px; margin-top: 8px; }}
.copy .mono {{ flex: 1; min-width: 0; margin: 0; white-space: pre-wrap; word-break: break-all; }}
.copy button {{ flex-shrink: 0; border: 0; border-radius: 8px; background: var(--primary); color: #fff;
  font: 600 12px/1 inherit; font-family: inherit; padding: 7px 10px; cursor: pointer; }}
.copy button:hover {{ filter: brightness(1.08); }}
ul.ex {{ margin: 0; padding-left: 18px; }}
ul.ex li {{ margin-bottom: 6px; }}
.note {{ font-size: 13px; color: var(--muted); }}
footer {{ font-size: 13px; color: var(--muted); text-align: center; margin-top: 24px; }}
</style>
</head>
<body>
<main>
  <header>
    <img src="{APP_URL}/extractor-icon.png" alt="">
    <h1>{t["title"]}</h1>
  </header>
  <p class="lead">{t["lead"]}</p>

  <div class="card">
    <p class="label">{t["url"]}</p>
    {copy_block(MCP_URL)}
  </div>

  <div class="card">
    <ol>
      <li><h2>{t["s1"]}</h2><p>{t["s1d"].format(**fmt)}</p></li>
      <li><h2>{t["s2"]}</h2><p>{t["s2d"]}</p></li>
      <li><h2>{t["s3"]}</h2><p>{t["s3d"].format(**fmt)}</p></li>
      <li><h2>{t["s4"]}</h2><p>{t["s4d"]}</p>{copy_block(_CLI)}
        <p style="margin-top:12px">{t["s4p"]}</p>{copy_block(_PLUGIN, multiline=True)}</li>
    </ol>
  </div>

  <div class="card">
    <p class="label">{t["try"]}</p>
    <ul class="ex">{examples}</ul>
    <p class="note" style="margin-top:12px">{t["note"]}</p>
  </div>

  <footer><a href="{REPO_URL}">{t["more"]}</a> · <a href="{APP_URL}">app.extractorlead.com</a></footer>
</main>
<script>
document.querySelectorAll("button[data-copy]").forEach(function (b) {{
  b.addEventListener("click", function () {{
    var done = function () {{
      b.textContent = {t["copied"]!r};
      setTimeout(function () {{ b.textContent = {t["copy"]!r}; }}, 1500);
    }};
    if (navigator.clipboard) {{
      navigator.clipboard.writeText(b.dataset.copy).then(done, function () {{}});
    }}
  }});
}});
</script>
</body>
</html>"""


def _wants_page(scope) -> bool:
    if scope.get("type") != "http" or scope.get("method") != "GET":
        return False
    if scope.get("path", "").rstrip("/") != "/mcp":
        return False
    accept = ""
    for k, v in scope.get("headers") or []:
        if k == b"accept":
            accept = v.decode("latin-1").lower()
    return "text/html" in accept and "text/event-stream" not in accept


class BrowserGuide:
    """ASGI: sirve la guía a los navegadores y deja pasar todo lo demás."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not _wants_page(scope):
            return await self.app(scope, receive, send)
        accept_language = ""
        for k, v in scope.get("headers") or []:
            if k == b"accept-language":
                accept_language = v.decode("latin-1")
        body = render(pick_language(accept_language)).encode("utf-8")
        await send({"type": "http.response.start", "status": 200, "headers": [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"public, max-age=300"),
            (b"vary", b"Accept, Accept-Language"),
            (b"x-content-type-options", b"nosniff"),
        ]})
        await send({"type": "http.response.body", "body": body})
