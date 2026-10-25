# ExtractorLead for Claude (MCP + Skill)

Find B2B/B2C leads (emails and phone numbers) on LinkedIn, Instagram, TikTok and
websites, and enrich your own contact lists, directly from Claude.

- **MCP server** — 13 tools that call the ExtractorLead API with *your* API key.
- **Skill** — teaches Claude the workflow: check balance, quote, ask before
  spending credits, poll async jobs, deliver results.

Every action is billed to your ExtractorLead account, exactly as through the
API. Claude always asks for confirmation before launching anything that costs
credits.

## 1. Get an API key

Sign in at <https://app.extractorlead.com> → **Profile → API keys** → create a
key. It starts with `sk_live_`. Treat it like a password.

## 2. Add it to Claude

### claude.ai and Claude Desktop (custom connector)

1. **Customize → Connectors → + Add → Add custom connector**
   (Team/Enterprise: an Owner adds it under *Organization settings → Connectors*).
2. Name: `ExtractorLead` · URL: `https://api.extractorlead.com/mcp`
3. Authentication: **No sign in**. Under **Request headers** add
   `X-API-Key` = `sk_live_...`
4. Add, then enable it in a chat from the tools menu.

If your client can't set headers, you can use the URL
`https://api.extractorlead.com/mcp?api_key=sk_live_...` instead. That URL is a
secret: anyone who has it can spend your credits. Revoke the key if it leaks.

**Skill (recommended):** download
[`extractorlead-skill.zip`](https://github.com/NeuroBlockFoundation/extractorlead-mcp/releases/latest/download/extractorlead-skill.zip)
and upload it at
**Customize → Skills → + → Upload a skill**.

### Claude Code (plugin: connector + skill in one step)

```
/plugin marketplace add NeuroBlockFoundation/extractorlead-mcp
/plugin install extractorlead@extractorlead
```

Claude Code prompts for the API key and stores it in the system keychain.

Connector only, without the skill:

```
claude mcp add --transport http extractorlead https://api.extractorlead.com/mcp --header "X-API-Key: sk_live_..."
```

### Local server (stdio)

Useful for passing a CSV/XLSX straight from disk (`file_path`), which the remote
connector can't read.

```json
{
  "mcpServers": {
    "extractorlead": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/NeuroBlockFoundation/extractorlead-mcp", "extractorlead-mcp"],
      "env": { "EXTRACTORLEAD_API_KEY": "sk_live_..." }
    }
  }
}
```

Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS).

## 3. Try it

> Find me 25 emails of marketing directors at SaaS companies in Madrid.

> Here's my Sales Navigator export: get me phones and emails, quote first.

> Fill the missing phones in this CRM list and give me back the Excel.

## Tools

| Tool | Costs credits | What it does |
|---|---|---|
| `get_account` | no | Balance and plan |
| `search_leads` | yes | New leads by niche + location (LinkedIn / Instagram / TikTok, emails or phones) |
| `lookup_linkedin_profile` | yes | Contact details for one LinkedIn profile |
| `analyze_website` | yes | Contacts and business info from a website |
| `get_task_result` | no | Status/result of the three above (waits up to 50 s, paginated) |
| `preview_bulk_enrichment` | no | Validate + quote a list of people |
| `start_bulk_enrichment` | yes | Enrich up to 5,000 people (email 2, phone 3, both 4 credits per *delivered* contact) |
| `get_bulk_status` / `get_bulk_results` / `get_bulk_download_link` | no | Track and fetch a bulk job |
| `preview_list_enrichment` | no | Analyze your own list and quote filling its gaps |
| `start_list_enrichment` | up to `credit_cap` | Fill gaps; returns your same Excel with new columns |
| `get_list_enrichment` | no | Status + download link of the edited Excel |

Phones in bulk jobs arrive asynchronously (up to ~1 hour, `phase:
awaiting_phones`). Claude tells you and you can ask again later with the same
job.

## Development

```
pip install -e ".[test]" pytest-asyncio
pytest
extractorlead-mcp            # stdio (needs EXTRACTORLEAD_API_KEY)
extractorlead-mcp --http     # remote multi-user server on :8080, /mcp + /health
python scripts/build_skill_zip.py   # dist/extractorlead-skill.zip
claude plugin validate .
```

`EXTRACTORLEAD_API_URL` overrides the API base URL (default
`https://api.extractorlead.com`; in the cluster it points to the internal
Service). In HTTP mode the server **never** uses a key from its environment or
reads its own disk: every request must bring the user's key (`X-API-Key`,
`Authorization: Bearer`, or `?api_key=`), and the access log is disabled so
keys in the URL aren't written to logs.

Deployment: the remote server runs on ExtractorLead's infrastructure (image from
`Dockerfile`, Terraform stack `extractor-lead/mcp`). This public repository is a
mirror synced automatically on every release.
