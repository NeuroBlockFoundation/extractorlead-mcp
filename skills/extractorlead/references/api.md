# Referencia de herramientas ExtractorLead

| Herramienta | Cobra | Devuelve |
|---|---|---|
| `get_account` | no | `tokens_balance`, `subscription_active`, `monthly_quota`, `remaining_in_period`, `credit_price_eur` |
| `search_leads` | sí | `task_id`, `status: queued` |
| `lookup_linkedin_profile` | sí | `task_id` |
| `analyze_website` | sí | `task_id` |
| `get_task_result` | no | `status`, `progress`, `result` (leads en `result.profiles` u otra lista), `pagination` |
| `preview_bulk_enrichment` | no | `rows_accepted`, `rows_skipped`, `rows_duplicated`, `detected_columns`, `max_credits`, `available_credits`, `sufficient_balance`, `sample` |
| `start_bulk_enrichment` | sí | `task_id`, `max_credits`, `rows_accepted` |
| `get_bulk_status` | no | `status`, `phase`, `progress`, `stats`, `credits_charged`, `leads_available`, `partial`, `pending_phone` |
| `get_bulk_results` | no | `leads[]`, `page`, `total`, `total_pages`, `has_more` |
| `get_bulk_download_link` | no | `download_url` (15 min), `total` |
| `preview_list_enrichment` | no | `columnas_detectadas`, `huecos`, `coste` (con `tope_sugerido`), `saldo_disponible`, `muestra` |
| `start_list_enrichment` | hasta `credit_cap` | `task_id`, `credit_cap`, `huecos` |
| `get_list_enrichment` | no | `status`, `stage`, resumen y `download_url` del Excel (1 h) |

## Estados

- Tareas: `PENDING` → `PROCESSING` → `COMPLETED` | `FAILED` | `CANCELLED`.
- Masivo, además `phase`: `processing` → `awaiting_phones` → `completed`.
  `COMPLETED` solo llega cuando el trabajo es definitivo.

## Campos de un lead (masivo)

`name`, `first_name`, `last_name`, `title`, `seniority`, `company`,
`company_domain`, `company_industry`, `company_size`, `linkedin_url`,
`location`, `city`, `country`, `email`, `email_status`, `phone_numbers`
(cada uno con `number` y `type`), `phone_status` (`found` | `not_found` |
`not_requested`; mientras llegan los teléfonos el trabajo está en
`awaiting_phones`), `match_type` (`exact` | `related`), `credits_cost`.

## Precios

- Masivo, por contacto **entregado**: solo email 2, solo teléfono 3, ambos 4,
  sin datos 0 créditos. Con `all_contact_info` un lead sin teléfono no se
  entrega ni se cobra.
- Búsquedas por nicho: según plan; `get_account` da el precio por crédito.
