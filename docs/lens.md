# Lens (MCP server)

The Lens lets you zoom into any day: `lumitrace-lens` (`lumitrace/lens/`; Docker service `lens`) lets
AI apps (Claude, ChatGPT, Cursor, ...) read the journal. AI apps see it as **Lumitrace**. It reads
the SQLite index built by the Spectrum (the indexer) and the
Frames (day files) in storage, and it writes only the `feedback` table plus a JSON copy under
`_system/feedback/`.

```bash
uv run lumitrace-lens                         # LUMITRACE_MCP_TRANSPORT (default streamable-http on :8002/mcp)
uv run lumitrace-lens --transport stdio       # for Claude Desktop / Cursor running it locally
uv run lumitrace-lens reset-oauth             # forget all OAuth clients and tokens
```

| Module | What it does |
|---|---|
| `server.py` | `build_server(settings, storage=None, *, transport=None)`, server instructions, tool registration, `/health` |
| `tools.py` | `LensTools`: the five tools as plain Python returning JSON-ready dicts |
| `search.py` | Hybrid search: FTS5 bm25 + sqlite-vec cosine, reciprocal rank fusion, snippets |
| `dates.py` | Date arguments (`YYYY-MM-DD`, `today`, `yesterday`, `MM-DD`) |
| `index.py` | Read-only per-call connections; missing / empty / mismatched index handling |
| `auth.py` | Auth modes `none`, `token`, `oauth` (`build_auth`) |
| `oauth.py` | Single-owner OAuth 2.1 authorization server with a password page |

## Server instructions

Sent to every client at connection time (`INSTRUCTIONS` in `server.py`): answer **only** from
what the tools return, **cite the date** (YYYY-MM-DD) of every entry used, say plainly when
nothing was found, resolve relative dates ("last Tuesday") to explicit dates, which tool to use
for what, and to call `feedback` when the owner says an answer was wrong.

## Tools

All dates are `YYYY-MM-DD` strings. Date arguments also accept `today` and `yesterday`
(resolved in `LUMITRACE_TIMEZONE` with the 4 a.m. rollover). Natural-language phrases are the AI
client's job; the tool descriptions say so. Bad arguments return an MCP tool error with a
message that explains the accepted format. All read tools are annotated `readOnlyHint`.

### `search(query, from_date?, to_date?, limit=10)`

Hybrid search over passages (title, journal, notes, transcript, facts).

* Keyword: the query is split into words, stop words dropped (unless nothing else is left),
  each word quoted (so FTS5 syntax in the query is inert) and ORed; ranked by `bm25`.
* Meaning: the query is embedded with `embed_texts` (same model as the indexer) and ranked by
  sqlite-vec cosine distance (`passages_vec ... MATCH ? AND k = ?`).
* Both lists fetch `max(4 × limit, 20)` candidates and are merged with reciprocal rank fusion,
  `score = Σ 1 / (60 + rank)`; ties go to the better single rank, then the lower id.
* Date filters are inclusive and applied in SQL on both sides (`p.date BETWEEN` for FTS,
  `rowid IN (SELECT id FROM passages WHERE date ...)` inside the vec0 KNN query).
* Falls back to keyword-only (with a `note`) if embedding fails or the index was built with a
  different `embedding_model`.
* `limit` is 1–50.

```json
{"query": "pumpkin", "from_date": null, "to_date": null, "search_modes": ["keyword", "meaning"],
 "results": [{"date": "2024-10-10", "section": "journal", "heading": "Summary",
              "snippet": "We drove out to the pumpkin patch…", "path": "2024/10/2024-10-10/2024-10-10.md",
              "score": 0.032522, "matched_by": ["keyword", "meaning"]}]}
```

### `get_day(date)`

Reads the day file from storage (the source of truth; works even before the index exists) and
returns `found`, `path`, `title`, `facts` (the `DayFacts` fields), `journal`, `notes`,
`transcript` (one item per capture: `time`, `kind`, `location`, `audio`, `photos`, `text`,
`translation`: the English translation of a recording, or `null`),
`audio` and `photos` (`{name, path, link}` with `link` from `storage.get_share_link`, i.e. a
private Google Drive link that opens only for the owner, or `file://` locally; `link` is `null`
with an `error` if the file is missing), and `user_edited`. A missing day returns
`found: false` and a `note`.

### `query_facts(kind, contains?, from_date?, to_date?, limit=50, person?)`

`kind`: `meals` | `activities` | `people` | `places` | `family` | `mood` | `highlights`.
`contains` is a case-insensitive substring (LIKE wildcards are escaped); for meals it matches the
item or the meal type ("breakfast"), for family the text or the category ("food"). `person`
(case-insensitive exact name) only applies to `family`; with any other kind it is an input
error. Returns:

* `rows`: newest first, each with `date` (meals: `meal_type`, `item`; activities: `kind`,
  `minutes`; people / places: `name`; family: `person`, `category` (`mood`, `food`, `places`,
  `activities`, `moments`, `health`, `school`), `text`, `minutes`; highlights: `text`; mood:
  `mood`, `mood_score`), at most `limit` (1–500); `truncated` says if there were more.
* `counts`: `rows`, `days`, `first_date`, `last_date` over **all** matches.
* `aggregates` over all matches: meals `top_items` and `by_meal_type`; activities
  `total_minutes` and `by_kind` (times, days, total and average minutes); people `by_person` and
  places `by_place` (days, first and last date); family `by_person_and_category` (times, days,
  total minutes) and `top_items` (per person and category); mood `average_score`, `min_score`,
  `max_score`, `days_with_score`, `by_mood`.

### `on_this_day(date?, years_back=10)`

`date` is `YYYY-MM-DD`, `today`/`yesterday`, or `MM-DD` (reference year = this year); default
today. Returns entries with the same month and day in the `years_back` (1–100) years before the
reference year, newest first: `date`, `years_ago`, `title`, `mood`, `mood_score`, `city`,
`weather`, `people`, `places`, `highlights`, `family` (rows of `person`, `category`, `text`,
`minutes`), `summary` (start of the first journal passage) and `path`. February 29 only matches February 29.

### `feedback(question, answer, comment, rating="wrong", dates?, tool?)`

`rating`: `wrong` | `incomplete` | `good` | `other`. `dates` defaults to the `YYYY-MM-DD` dates
found in `answer`. Writes the JSON copy to `_system/feedback/YYYY/MM/<UTC timestamp>-<random>.json`
(the durable record) and a row in the `feedback` table (with `storage_path`, `client` = the AI
app's name). If one of the two writes fails the other is still kept; the index file and schema
are created if missing. Returns `saved`, `id`, `dates`, `storage_path`.

## The index

* Each tool call opens its own **read-only** connection (`connect(..., read_only=True)`), so the
  indexer can sync or rebuild at any time. Only `feedback` opens it for writing.
* Missing file, unreadable file or no schema: tools return empty results with a `note` saying
  the index has not been built yet. Schema but no rows: `note` says the index is empty.
* Embedding dimension mismatch: tool error telling the owner to rebuild (`docs/runbook.md`).

## Transports and authentication

| Transport | Used by | Auth |
|---|---|---|
| `stdio` | Claude Desktop, Cursor (server runs on the same machine) | none (local process) |
| `streamable-http` (`LUMITRACE_MCP_HOST`:`LUMITRACE_MCP_PORT``LUMITRACE_MCP_PATH`) | remote and phone apps | `LUMITRACE_MCP_AUTH_MODE` |

`LUMITRACE_MCP_AUTH_MODE`:

* `none`: no auth. Only for a server bound to `127.0.0.1` (a warning is logged otherwise).
* `token` (default): `Authorization: Bearer <LUMITRACE_MCP_AUTH_TOKEN>`. The token must be at
  least 16 characters and not a placeholder (`openssl rand -hex 32`), or the server refuses to
  start. Missing or wrong token → `401` with `WWW-Authenticate: Bearer`.
* `oauth`: a minimal single-owner OAuth 2.1 authorization server for Claude and ChatGPT
  connectors (decision 0032). Needs `LUMITRACE_MCP_OWNER_PASSWORD` (16+ characters) and
  `LUMITRACE_MCP_PUBLIC_URL` = the public **https** root URL of the server (no path; it is the
  OAuth issuer, and the protected resource is `<public URL><LUMITRACE_MCP_PATH>`). If
  `LUMITRACE_MCP_AUTH_TOKEN` is also set, that static token keeps working (handy for Cursor).

`GET /health` is always unauthenticated: `{"status", "version", "auth_mode", "index_present"}`.

### OAuth details

Endpoints (served by the MCP SDK's auth support; Lumitrace supplies storage and the login step):

| Endpoint | Purpose |
|---|---|
| `/.well-known/oauth-protected-resource/mcp` | RFC 9728 resource metadata (advertised in the `401`) |
| `/.well-known/oauth-authorization-server` | RFC 8414 server metadata |
| `/register` | RFC 7591 dynamic client registration (open, capped at 50 clients) |
| `/authorize` | authorization code + PKCE (S256 only) → redirects to `/oauth/login` |
| `/oauth/login` | password page: **Allow** / **Deny** |
| `/token` | code exchange (PKCE checked) and refresh (rotates both tokens) |
| `/revoke` | revokes an access or refresh token and its pair |

* Access tokens last 1 hour, refresh tokens 90 days (rotated on every refresh), codes 5 minutes
  (single use), sign-in pages 10 minutes. Tokens are bound to the resource URL (RFC 8707);
  `/authorize` rejects other `resource` values with `invalid_target`.
* After 5 wrong passwords in 15 minutes the page refuses all attempts until the window passes.
* Clients and tokens persist in `mcp-oauth-state.json` next to the index
  (`LUMITRACE_INDEX_PATH`'s folder, mode 0600, tokens stored only as SHA-256 hashes), so a
  restart does not disconnect the apps. Pending sign-ins and codes are in memory: run **one**
  MCP server process.
* Scope: `lumitrace` (the only one).

## Connecting AI apps

Replace `/path/to/lumitrace` (the folder you cloned the repository into, whatever it is called)
and `journal.example.com` with your own values. Never commit the token or password. The server
key `"lumitrace"` and the connector name `Lumitrace` are just labels; the server itself reports
the title **Lumitrace**.

### Public HTTPS (needed for phone apps and claude.ai / ChatGPT)

Put the MCP server behind a TLS reverse proxy, for example Caddy (automatic certificates):

```caddyfile
journal.example.com {
    reverse_proxy localhost:8002
}
```

`.env` on the server:

```bash
LUMITRACE_MCP_TRANSPORT=streamable-http
LUMITRACE_MCP_PUBLIC_URL=https://journal.example.com
LUMITRACE_MCP_AUTH_MODE=oauth
LUMITRACE_MCP_OWNER_PASSWORD=<long passphrase>
LUMITRACE_MCP_AUTH_TOKEN=<openssl rand -hex 32>   # optional, for Cursor / scripts
```

Check: `curl https://journal.example.com/health` and
`curl https://journal.example.com/.well-known/oauth-authorization-server`.

### Claude (web, iPhone, Android) and Claude Desktop as a connector

1. On claude.ai: **Settings → Connectors → Add custom connector**. Name `Lumitrace`, URL
   `https://journal.example.com/mcp`. (Custom connectors need a paid plan; on Team/Enterprise an
   owner adds them.)
2. Click **Connect**. Claude registers itself, then opens the Lumitrace sign-in page: type the
   owner password and press **Allow**.
3. The connector syncs to the Claude mobile apps and Claude Desktop. Enable it per chat from the
   tools menu.

### ChatGPT

1. **Settings → Apps & Connectors → Advanced settings**: turn on **Developer mode** (available
   on paid plans).
2. **Settings → Apps & Connectors → Create**: name `Lumitrace`, MCP server URL
   `https://journal.example.com/mcp`, authentication **OAuth**. Sign in on the Lumitrace page.
3. Choose the connector in a chat (developer mode) and ask. The ChatGPT UI changes often; check
   OpenAI's current docs if the menu names differ.

### Claude Desktop, local (stdio)

Use this when the laptop has the data (index file and storage access, e.g. local storage or the
Drive token). `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "lumitrace": {
      "command": "/path/to/lumitrace/.tools/bin/uv",
      "args": ["--directory", "/path/to/lumitrace", "run", "lumitrace-lens", "--transport", "stdio"],
      "env": {
        "UV_PYTHON_INSTALL_DIR": "/path/to/lumitrace/.tools/python",
        "UV_CACHE_DIR": "/path/to/lumitrace/.tools/cache"
      }
    }
  }
}
```

`--directory` makes the server read `/path/to/lumitrace/.env`. Restart Claude Desktop after
editing. Logs go to stderr (Claude Desktop shows them in its MCP log files).

To use the remote server from Claude Desktop instead, add it as a connector (above), or with a
static token through the `mcp-remote` bridge:

```json
{
  "mcpServers": {
    "lumitrace": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://journal.example.com/mcp",
               "--header", "Authorization: Bearer ${LUMITRACE_MCP_AUTH_TOKEN}"],
      "env": { "LUMITRACE_MCP_AUTH_TOKEN": "<token>" }
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project). Local:

```json
{
  "mcpServers": {
    "lumitrace": {
      "command": "/path/to/lumitrace/.tools/bin/uv",
      "args": ["--directory", "/path/to/lumitrace", "run", "lumitrace-lens", "--transport", "stdio"]
    }
  }
}
```

Remote with the static token (works in `token` mode, and in `oauth` mode when
`LUMITRACE_MCP_AUTH_TOKEN` is set):

```json
{
  "mcpServers": {
    "lumitrace": {
      "url": "https://journal.example.com/mcp",
      "headers": { "Authorization": "Bearer ${env:LUMITRACE_MCP_AUTH_TOKEN}" }
    }
  }
}
```

Or leave out `headers` in `oauth` mode and Cursor runs the OAuth sign-in itself.

## Privacy

* When a tool runs, the returned journal text goes to the AI app's provider. **Turn off training
  on your chats** in every app you connect: Claude: **Settings → Privacy → Help improve Claude**
  off. ChatGPT: **Settings → Data controls → Improve the model for everyone** off.
* `get_day` links to audio and photos are private Drive links: the AI provider sees the link,
  but only your Google account can open the file.
* Keep `mcp_auth_mode=none` for localhost only. Anyone with the token or the owner password can
  read the whole journal; rotate them as in `docs/runbook.md`.
* The MCP server never logs queries, answers or journal text (only ratings, ids and client
  names); a rejected tool call logs its error message (e.g. the unreadable date).

## Not verified yet / known limits

* The OAuth flow is tested end to end in-process with the SDK's own endpoints (registration,
  PKCE, password page, token exchange, refresh rotation, revocation) but **has not yet been
  tried against the real Claude and ChatGPT connectors**. First real connection: watch the MCP
  logs and note any client quirks in `docs/learnings.md`.
* The SDK's metadata advertises `client_secret_post` / `client_secret_basic` only; public
  clients registering with `token_endpoint_auth_method: none` are still accepted.
* Single process only (pending sign-ins and codes are in memory). Password only, no second
  factor. No per-tool consent screen.
* ChatGPT "deep research" expects `search`/`fetch` tools with a fixed shape; Lumitrace's tools are
  for developer-mode connectors and are not shaped for deep research.
