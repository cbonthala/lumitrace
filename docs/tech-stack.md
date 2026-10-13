# Tech stack

Everything Lumitrace is built with or depends on, grouped by module, and whether it is open source.
Versions are the ones locked in `uv.lock` (Python packages) or pinned in the `Dockerfile`.
Providers and services are swappable through config (`lumitrace/config.py`, decision 0005) unless
noted. Lumitrace itself is one Python package and one Docker image; `pyproject.toml` marks it
proprietary. Examples below use fictional data.

## Shared by all three programs

The foundation every program uses (`lumitrace/config.py`, `lumitrace/logging_setup.py`, the image).

| What | Version | Used for | Open source? |
|---|---|---|---|
| Python | 3.12 | The language all of Lumitrace is written in. The Prism, Spectrum and the Lens are three commands (`lumitrace-prism`, `lumitrace-spectrum`, `lumitrace-lens`) from the same package. | Yes (PSF License) |
| Pydantic | 2.14 | Describes and checks data shapes. Example: a day's facts (`DayFacts`) or a capture's status (`CaptureStatus`) are Pydantic models, so a wrong type is caught instead of silently written to a file. | Yes (MIT) |
| pydantic-settings | 2.15 | Reads configuration from environment variables. Example: `LUMITRACE_TIMEZONE=America/Chicago` in `.env` becomes `settings.timezone` in code. | Yes (MIT) |
| uv | 0.13 | Installs the Python libraries at exact versions from `uv.lock`, both on a laptop (`uv sync`) and inside the Docker image, so every machine runs the same code. | Yes (MIT / Apache-2.0) |
| hatchling | | Packages the `lumitrace` folder as an installable Python package so the commands above exist. | Yes (MIT) |
| Docker image `python:3.12-slim` (Debian) | | The small Linux base the Lumitrace image is built on. One image runs all three programs; Compose picks the command per service. | Yes (mixed free licenses) |
| tzdata, ca-certificates | | Time zone data, so a recording at 1 a.m. Chicago time lands on the right day (with the 4 a.m. rollover), and root certificates, so HTTPS calls to Google and OpenAI are trusted. | Yes (public domain / MPL-2.0) |

## Flash (iPhone capture)

| What | Version | Used for | Open source? |
|---|---|---|---|
| Apple Shortcuts | | The iPhone side of Lumitrace, with no app to install. Example: **Log My Day** records your voice and uploads it to the Prism; **Quick Note** sends a typed note; **Send pending** retries uploads that failed offline. Build guide: `docs/flash.md`. | No (Apple) |
| Tailscale iOS app | | Puts the iPhone on your private network so the shortcuts can reach the Prism at `https://lumitrace.<tailnet>.ts.net:8443`. With VPN On Demand it connects automatically. | Yes (BSD-3-Clause client) |

## Prism (recording API and pipeline)

`lumitrace/prism/`, `lumitrace/prism/pipeline/`, `prompts/`.

| What | Version | Used for | Open source? |
|---|---|---|---|
| FastAPI | 0.143 | The web framework for the Prism's API. Example: the shortcut sends `POST /recordings` with the audio; the Prism answers `202 Accepted` with a capture ID, and `GET /captures/{id}` later shows whether it was transcribed and written. | Yes (MIT) |
| Starlette | 1.7 | The lower-level web toolkit FastAPI is built on (requests, responses, routing). Not used directly. | Yes (BSD-3-Clause) |
| Uvicorn | 0.54 | The server process that listens on port 8000 and hands each HTTP request to FastAPI. | Yes (BSD-3-Clause) |
| python-multipart | 0.0.32 | Parses file uploads. Example: a recording plus two photos sent in one request arrive as separate files. | Yes (Apache-2.0) |
| AnyIO | 4.15 | Runs slow, blocking work in background threads so the API stays responsive. Example: saving an uploaded recording to disk, or starting the processing worker at startup. | Yes (MIT) |
| LiteLLM | 1.104 | One library to call any AI provider with the same code. The Prism uses it to transcribe audio, extract facts and write the journal; switching from OpenAI to Anthropic is a settings change, not a code change. | Yes (MIT; its separate enterprise folder is not used) |
| FFmpeg (Debian package) | | Converts audio. Example: a 6-minute recording is compressed to AAC `.m4a` at 32 kbps (about 1.5 MB) before it is stored in Drive (`pipeline/audio.py`). | Yes (LGPL / GPL) |
| Pillow | 12.3 | Image processing. Example: a 12-megapixel photo is resized so its longest side is 2048 px and saved as a JPEG at quality 85, keeping Drive small. | Yes (MIT-CMU / HPND) |
| pillow-heif | 1.8 | Lets Pillow open iPhone photos, which are saved in Apple's HEIC format by default. | Yes (BSD-3-Clause; bundled libheif is LGPL-3.0) |
| httpx | 0.28 | Makes HTTP calls from Python. Example: right after writing a day file, the Prism calls Spectrum's `/nudge` so the new entry is searchable within seconds instead of at the next 5-minute check (`lumitrace/nudge.py`). Also calls Sarvam's speech-to-text API when that provider is chosen. | Yes (BSD-3-Clause) |
| boto3 | 1.43 | The AWS library, used only if speech-to-text is switched to Amazon Transcribe (`LUMITRACE_STT_PROVIDER=aws_transcribe`). Installed but not used in production. | Yes (Apache-2.0) |

AI models (production uses OpenAI; where each is called: `docs/prism.md` → *Models and
fallback*):

| Task | Setting | Current model | What it does, with an example | Open source? |
|---|---|---|---|---|
| Speech to text | `LUMITRACE_STT_MODEL` | `openai/gpt-4o-transcribe` | Turns the recording into text. Example: "We took the kids to the park after lunch…" becomes the raw transcript kept in the day file. | No (OpenAI API) |
| Speech to text and English translation (option) | `LUMITRACE_STT_PROVIDER=sarvam`, `LUMITRACE_SARVAM_MODEL` | `saaras:v4` | For Indian languages mixed with English: the transcript keeps English words in English and Telugu in Telugu script, and a second job translates the audio to English. Called over HTTP with httpx (ADR 0015). | No (Sarvam API) |
| Extracting facts | `LUMITRACE_LLM_EXTRACT_FACTS_MODEL` | `openai/gpt-4o-mini` | Pulls structured facts out of the text for "At a glance". Example: Lunch: tacos; Places: City Park; Activities: walk, 40 min; Mood: happy. | No (OpenAI API) |
| Writing the journal and addendums | `LUMITRACE_LLM_WRITE_JOURNAL_MODEL` | `openai/gpt-4o` | Writes the readable journal (Summary, Morning, Afternoon, Evening, ...) and the day's headline. If you edited the day, it only adds a short passage under `## Later` instead. | No (OpenAI API) |
| Fallback | `LUMITRACE_LLM_FALLBACK_MODEL` | `openai/gpt-4o-mini` | Used when a task's model fails or returns badly formed output, so a recording is still processed. | No (OpenAI API) |

Any LiteLLM provider works for the chat models (Anthropic, Gemini, Bedrock, Groq, Azure, local
Ollama, ...); speech to text needs one that offers transcription (OpenAI, Groq, Azure), Amazon
Transcribe or Sarvam. Tests use `fake` providers.

## Frames (day files and storage)

`lumitrace/frames/dayfile.py`, `lumitrace/frames/storage/`.

| What | Version | Used for | Open source? |
|---|---|---|---|
| Markdown day files | | The source of truth: one plain-text file per day, readable without Lumitrace. Example: `2026/10/2026-10-10/2026-10-10.md` holds the title, "At a glance", the journal, your notes and the transcript (`docs/frames-format.md`). | Open format |
| PyYAML | 6.0 | Reads and writes the small header at the top of each day file. Example: `date`, `models_used` (which AI models wrote it) and `generated_hash`, which lets the Prism tell whether you edited the file. | Yes (MIT) |
| Google Drive | | Where everything is stored: day files, the audio and photos next to them, and records under `Lumitrace/_system/` (activity, reports, feedback, index backups). Lumitrace can only see files it created (`drive.file` scope). | No (Google service) |
| google-api-python-client | 2.201 | Talks to the Drive API. Example: upload a day file, list files changed since the last check, download a photo. | Yes (Apache-2.0) |
| google-auth, google-auth-oauthlib | 2.61, 1.5 | Google sign-in. `lumitrace-drive-login` opens the browser once and saves a token; the server then refreshes that token on its own. | Yes (Apache-2.0) |
| requests | 2.34 | The HTTP library Google's sign-in code uses under the hood (for example to refresh the token). | Yes (Apache-2.0) |
| Google Cloud project (Google Auth Platform) | | Registers "Lumitrace" as an app with Google so it is allowed to use your Drive. Published "In production" so the sign-in does not expire every 7 days. | No (Google service) |
| GitHub Pages | | Hosts a simple home page and privacy policy; Google requires both before an app can be published. | No (GitHub service) |
| Obsidian | | The app you read and edit the day files in. Edits are respected: the Prism never overwrites text you changed. | No (proprietary, free for personal use) |

The `local` storage backend (a folder on disk) is used for tests and local runs.

## Spectrum (indexer)

`lumitrace/spectrum/`; schema in `lumitrace/index/schema.py`.

| What | Version | Used for | Open source? |
|---|---|---|---|
| FastAPI, Uvicorn | 0.143, 0.54 | A tiny internal API with one endpoint, `POST /nudge`, which the Prism calls to say "a day changed, re-index now". Only reachable inside Docker. | Yes (MIT, BSD-3-Clause) |
| SQLite (Python `sqlite3`) | | A single-file database holding the search index: passages, facts, people, places, moods (`docs/index-schema.md`). It is disposable and can be rebuilt from the day files at any time. | Yes (public domain) |
| SQLite FTS5 | | Keyword search built into SQLite. Example: searching "pumpkin" finds every passage containing that word, ranked by relevance (bm25). | Yes (public domain) |
| sqlite-vec | 0.1.9 | Meaning search inside SQLite. Example: searching "pumpkin" can also find "we carved jack-o'-lanterns", which shares no words with the query. | Yes (MIT / Apache-2.0) |
| LiteLLM | 1.104 | Calls the embedding model for every passage when a day is indexed (`lumitrace/embeddings.py`). | Yes (MIT) |
| Embedding model `openai/text-embedding-3-small` | 1536 dims | Turns each passage into a list of 1536 numbers that represent its meaning; similar meanings get similar numbers. Changing the model requires `lumitrace-spectrum rebuild`. | No (OpenAI API) |

## Lens (MCP server)

`lumitrace/lens/`.

| What | Version | Used for | Open source? |
|---|---|---|---|
| MCP Python SDK (`mcp`) | 2.3 | Implements the Model Context Protocol, the standard AI apps use to call outside tools. It exposes Lumitrace's tools (`search`, `get_day`, `query_facts`, `on_this_day`, `feedback`) and the OAuth sign-in Claude and ChatGPT require. | Yes (MIT) |
| Starlette, Uvicorn | 1.7, 0.54 | The web layer under the MCP SDK: serves `/mcp`, `/health` and the password page you see when connecting an AI app. | Yes (BSD-3-Clause) |
| AnyIO | 4.15 | The async runtime the MCP SDK runs on. Example: the short pause after a wrong password on the sign-in page. | Yes (MIT) |
| SQLite, FTS5, sqlite-vec | | Reads the index Spectrum built. Example: "how many times did I run in September?" becomes a `query_facts` call answered from the index. Read-only, so Spectrum can rebuild at any time. | Yes (public domain, MIT / Apache-2.0) |
| LiteLLM + the same embedding model as Spectrum | | Embeds the question so `search` can find passages by meaning. It must be the same model Spectrum used, or the numbers don't compare. | Yes (MIT) / No (OpenAI API) |
| Claude, ChatGPT | | Where you ask questions. Example: "What did we do last Halloween?" Claude calls the Lens tools, then answers citing dates like 2025-10-31. | No (proprietary) |
| Claude Desktop, Cursor | | AI apps on your computer that can run the Lens locally (stdio) or connect with the static token. | No (proprietary) |

## Deployment and hosting

`deploy/lightsail/`, `Dockerfile`, `docker-compose.yml` (decision 0041).

| What | Version | Used for | Open source? |
|---|---|---|---|
| AWS Lightsail | | The server: one 2 GB virtual machine in `us-east-2` (about $12 a month) running all three programs, with daily snapshots as backups. | No (AWS service) |
| AWS CLI | | Command-line access to AWS. Example: `provision.sh` uses it to create the server, static IP and firewall; `deploy.sh` uses it to look up the server's address. | Yes (Apache-2.0) |
| Ubuntu | 24.04 | The server's operating system. | Yes (mixed free licenses) |
| Docker Engine and Docker Compose | | Run the three programs as containers from one image. Example: `docker compose up` starts `prism`, `spectrum` and `lens` with a shared data volume and restarts them if they crash. | Yes (Apache-2.0) |
| Tailscale client | | Connects the server to your private network and publishes it. Example: the Prism is at `https://lumitrace.<tailnet>.ts.net:8443` for your devices only; the Lens is public at `https://lumitrace.<tailnet>.ts.net/mcp` through Funnel. Also provides the HTTPS certificates. | Yes (BSD-3-Clause) |
| Tailscale coordination service and Funnel relays | | Tailscale's hosted part: the admin console, device sign-in, and relaying public internet traffic to the Lens. | No (Tailscale service, free plan) |
| jq | | Reads JSON on the command line. Example: `tailscale.sh` uses it to get the server's `*.ts.net` name from `tailscale status`. | Yes (MIT) |
| Git | | Version control. `deploy.sh` ships exactly the last commit, so uncommitted changes never reach the server. | Yes (GPL-2.0) |

## Development

| What | Version | Used for | Open source? |
|---|---|---|---|
| pytest | 9.1 | Runs the test suite. Example: `tests/e2e/test_full_flow.py` sends fake captures through the Prism, indexes the day file and asks the Lens tools about it, all offline with fake AI providers. | Yes (MIT) |
| Ruff | 0.17 | Checks code style and common mistakes, and formats the code (`ruff check .`, `ruff format .`). | Yes (MIT) |
| Cursor | | The editor and AI coding agent used to build Lumitrace. | No (proprietary) |
