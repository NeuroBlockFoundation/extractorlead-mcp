# Servidor MCP remoto de ExtractorLead (Streamable HTTP, sin estado).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Sin root: el proceso solo necesita salir a la API.
RUN useradd --uid 10001 --no-create-home mcp
USER 10001

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["extractorlead-mcp", "--http", "--port", "8080"]
