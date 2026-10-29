---
name: extractorlead
description: Find B2B/B2C leads (emails, phones) on LinkedIn, Instagram, TikTok or websites, and enrich contact lists or Sales Navigator exports, using the ExtractorLead MCP tools.
---

# ExtractorLead: prospección y enriquecimiento de leads

ExtractorLead encuentra emails y teléfonos de profesionales y negocios, y
rellena los huecos de listas que el usuario ya tiene. Las herramientas vienen
del conector MCP `extractorlead`. Responde siempre en el idioma del usuario.

## Reglas que no se negocian

1. **Todo gasta créditos del usuario.** Antes de cualquier herramienta marcada
   como "Consume créditos" (`search_leads`, `lookup_linkedin_profile`,
   `analyze_website`, `start_bulk_enrichment`, `start_list_enrichment`):
   - consulta `get_account` o la cotización (`preview_*`),
   - dile al usuario qué vas a lanzar y el coste máximo en créditos,
   - **espera un "sí" explícito**. Una petición vaga ("búscame clientes") no es
     una confirmación de gasto.
2. **Nunca relances un trabajo para "ver si va más rápido"**: se cobraría dos
   veces. Si algo tarda, vuelve a consultar el mismo `task_id`.
3. **No hables de proveedores.** Si preguntan de dónde salen los datos: de la
   plataforma de ExtractorLead, que combina fuentes públicas y profesionales.
   No adivines ni nombres bases de datos de terceros.
4. Trata los datos de contacto con cuidado: no los publiques fuera de la
   conversación salvo que el usuario lo pida (p.ej. exportarlos a su CRM).

## Elegir el flujo

| El usuario quiere… | Flujo |
|---|---|
| Leads nuevos de un nicho/zona ("dentistas en Valencia", "CTOs de fintech en Madrid") | **A. Búsqueda por nicho** |
| Contacto de UNA persona con su LinkedIn | `lookup_linkedin_profile` → `get_task_result` |
| Contactos y datos de una web | `analyze_website` → `get_task_result` |
| Emails/teléfonos para una lista de PERSONAS (nombre + empresa, LinkedIn, Sales Navigator) | **B. Enriquecimiento masivo** |
| Rellenar huecos de SU Excel/CRM y recibir el mismo fichero completado | **C. Relleno de lista** |

Diferencia B vs C: B devuelve una lista nueva de leads (con opción de buscar
contactos análogos en la misma empresa); C conserva sus columnas y le devuelve
su propio Excel con columnas nuevas, con un tope de gasto (`credit_cap`).

## A. Búsqueda por nicho

1. Aclara solo lo imprescindible: nicho, ubicación, email o teléfono, cuántos.
   Canal: **LinkedIn** para B2B (cargos y empresas); **Instagram/TikTok** para
   creadores, marcas y negocios locales (restaurantes, clínicas, gimnasios...).
2. `get_account` → comprueba saldo. Explica que `lead_count` es el máximo
   (1–500, por defecto 25) y pide confirmación.
3. `search_leads(channel, contact, niche, location, lead_count)`. Para
   teléfonos en LinkedIn añade `country` (ISO-2, p.ej. `es`, `mx`).
4. `get_task_result(task_id, wait_seconds=50)`. Si sigue en PROCESSING, dilo y
   vuelve a llamar; estas búsquedas tardan normalmente de 1 a 10 minutos.
5. Presenta los leads en una tabla (nombre, cargo, empresa, email, teléfono,
   ubicación). Si hay `pagination.has_more`, pide más con `offset`.

## B. Enriquecimiento masivo

1. Consigue las filas:
   - Si el usuario pega o adjunta una tabla, conviértela a `leads`
     (lista de objetos). Campos útiles: `first_name`, `last_name`,
     `full_name`, `company`, `domain`, `title`, `linkedin_url`, `email`,
     `location`. Las cabeceras en español también valen.
   - Con el servidor local (Claude Desktop/Code) puedes pasar `file_path`
     a un CSV/XLSX.
   - Máximo 5000 filas por trabajo.
2. Decide con el usuario:
   - `contact_info`: `all_contact_info` (por defecto: teléfono y email; solo
     entrega —y cobra— el email de quien tiene teléfono), `phone_info` o
     `email_info`.
   - `match_mode`: `strict` (la persona exacta) o `related` (añade contactos
     análogos de la misma empresa usando el cargo como semilla;
     `related_per_company` 1–10).
   - `require_mobile: true` si solo valen móviles.
3. `preview_bulk_enrichment(...)` → enseña `rows_accepted`, filas
   descartadas/duplicadas, `max_credits` y `available_credits`. Precio por
   contacto entregado: email 2, teléfono 3, ambos 4, nada 0. El cobro real
   suele ser bastante menor que `max_credits`.
4. Con confirmación: `start_bulk_enrichment(...)` con **los mismos**
   parámetros.
5. `get_bulk_status(task_id, wait_seconds=50)`:
   - `phase: processing` → sigue trabajando.
   - `phase: awaiting_phones` → los teléfonos llegan en diferido y pueden
     tardar **hasta ~1 hora**. Díselo al usuario, apunta el `task_id` y ofrece
     volver a consultar más tarde. Si `partial: true`, ya puedes enseñar los
     leads decididos.
   - `COMPLETED` → `get_bulk_results(task_id, only=..., match=...)`. Para
     listas grandes ofrece `get_bulk_download_link` (enlace de 15 min) en vez
     de volcar cientos de filas.

## C. Relleno de lista

1. `preview_list_enrichment(leads | file_path)` → explica las columnas
   detectadas, los huecos (`sin_telefono`, `sin_email`...), el coste y el
   `tope_sugerido`. `phone_for_all: true` solo si los teléfonos que trae son
   centralitas y quiere directos.
2. Acordad el `credit_cap` (por defecto, el `tope_sugerido`). El trabajo nunca
   gasta por encima de ese tope.
3. `start_list_enrichment(credit_cap, ...)`.
4. `get_list_enrichment(task_id, wait_seconds=50)` hasta `COMPLETED`; entrega
   el `download_url` del Excel (válido 1 hora) y un resumen de lo rellenado.

## Errores frecuentes

- `API_KEY_MISSING` / `API_KEY_INVALID` / `TOKEN_INVALID`: el conector no
  está conectado o la conexión caducó. Pide al usuario que abra Personalizar →
  Conectores → ExtractorLead y pulse Conectar para iniciar sesión de nuevo. Con
  el servidor local se usa una API key de https://app.extractorlead.com (Perfil
  → API keys), que empieza por `sk_live_`.
- `INSUFFICIENT_BALANCE` (402): faltan créditos; recarga en
  https://app.extractorlead.com/profile. Propón reducir `lead_count` o filas.
- `TEMPORARILY_UNAVAILABLE` (503): reintenta en unos segundos; el trabajo no
  se pierde.
- `NOT_FOUND` en una tarea: el id no es de esta cuenta o está mal copiado.

Más detalle de campos y respuestas: [references/api.md](references/api.md).
