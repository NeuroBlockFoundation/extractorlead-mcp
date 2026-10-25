"""Arranque: `extractorlead-mcp` (stdio) o `extractorlead-mcp --http`."""
import argparse
import os
import sys

from . import server


def main() -> None:
    parser = argparse.ArgumentParser(prog="extractorlead-mcp")
    parser.add_argument("--http", action="store_true",
                        help="Servidor remoto Streamable HTTP (multiusuario) en vez de stdio.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    args = parser.parse_args()

    if args.http:
        server.MODE = "http"
        import uvicorn
        # Sin estado: cualquier réplica atiende cualquier petición, así que se
        # puede escalar detrás del balanceador sin sesiones pegajosas.
        from .guide import BrowserGuide
        app = server.mcp.streamable_http_app(stateless_http=True, json_response=True,
                                             host=args.host)
        # Quien abre la URL del conector en un navegador ve cómo añadirlo a Claude.
        app = BrowserGuide(app)
        # access_log=False: la URL del conector de claude.ai lleva la API key en
        # ?api_key=, y el log de accesos la escribiría en claro en cada petición.
        uvicorn.run(app, host=args.host, port=args.port, access_log=False,
                    proxy_headers=True, forwarded_allow_ips="*")
    else:
        server.MODE = "stdio"
        if not os.getenv("EXTRACTORLEAD_API_KEY"):
            print("Aviso: falta EXTRACTORLEAD_API_KEY; las herramientas fallarán hasta "
                  "configurarla.", file=sys.stderr)
        server.mcp.run("stdio")


if __name__ == "__main__":
    main()
