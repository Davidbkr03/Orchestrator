# Fusion Orchestrator – Enhancement Plan

A roadmap for adding **Web UI**, **Dynamic Model Discovery**, **Query History**, **Self-Update via Webhook**, and **Live .env Management** to the existing orchestrator, without breaking any existing endpoints.

---

## Overview

| Feature | Purpose | Status |
|---------|---------|--------|
| Web UI | Real-time dashboard for seeing council configs, sending test queries, and viewing system info while the server runs | ✅ Done |
| Dynamic Model Discovery | Query each provider's API for available models/capabilities to populate a model picker with toggles | ❌ Not started |
| Query History | In-memory ring buffer recording every query, worker responses, judge's thought (if applicable), and final answer | ❌ Not started |
| Self-Update via Webhook | Allow the server to pull the latest code from git and restart itself, or use a Docker sidecar for zero-downtime updates | 🟡 Partially done |
| Live .env Management | UI to read/write `.env` file, validate and re-initialize API keys without restarting the server | ❌ Not started |

---

## Current Implementation Summary

- **Web UI**: Fully functional. The FastAPI server serves the `webui/` folder, and the dashboard is accessible at `/ui`. It provides server info, council configuration visualization, and test query capabilities.
- **Self-Update**: The `restart.sh` script is implemented, providing the mechanism to perform a `git pull`, install dependencies, and restart the `uvicorn` process via HUP signal. The `POST /api/update` endpoint and Docker-based auto-update are not yet implemented.

---

## Architecture

- **No breaking changes** – existing `/v1/normal`, `/v1/advanced`, and their streaming `/chat/completions` endpoints remain untouched.
- The Web UI is served directly by the FastAPI server via `StaticFiles` mount at `/ui` – no separate frontend build step.
- A **global configuration object** will replace hardcoded `NORMAL_WORKERS` / `ADVANCED_WORKERS`, letting the UI update them live via a `PUT /api/council/config` endpoint.
- History is managed by a dedicated `history.py` module and exposed through read/clear REST endpoints.
- The `.env` file is managed through `PUT /api/env` endpoints, not by reading/writing files directly from the frontend (for security).

---

## File Structure (current + planned)

```
.
├── orchestrator.py          # main app – routes, council logic, UI mount
├── history.py               # new module – QueryHistory class
├── .env                     # API keys and config (gitignored)
├── .env.example             # template with placeholder values
├── requirements.txt         # Python dependencies
├── Dockerfile               # Docker build for deployment
├── docker-compose.yml       # planned – Watchtower sidecar for auto-updates
├── restart.sh               # script triggered by update webhook ✅ already exists
├── .gitignore
├── webui/
│   ├── index.html           # main dashboard layout (done)
│   ├── style.css            # dark-theme styling (done)
│   └── app.js               # frontend logic (done – basic info + test query)
├── README.md                # documentation
└── WebuiPlan.md             # this file
```

---

## Feature 1: Web UI — ✅ Complete

### Backend (`orchestrator.py`)
- Mounts `webui/` as static files at `/ui`.
- Root redirect `GET /` → `/ui/index.html`.
- `GET /api/info` returns council definitions, server start time, uptime, and active routes.

### Frontend (`webui/index.html`, `style.css`, `app.js`)
- Three-panel dashboard (Council Config, Test Query, System Info).
- Dark theme matching terminal aesthetic.
- Fetches `/api/info` on load, displays worker/judge models.
- Test Query sends to `/v1/normal` or `/v1/advanced` and shows the response.
- Live uptime counter.

### Remaining work for Feature 1
- [ ] Add `PUT /api/council/config` so the UI can swap workers/judge live.
- [ ] Add model dropdowns to the left panel (depends on Feature 2).

---

## Feature 2: Dynamic Model Discovery

### Endpoint `GET /api/models`
For each configured provider (OpenAI, DeepSeek, Gemini), query their models list endpoint:

| Provider | URL |
|----------|-----|
| OpenAI | `https://api.openai.com/v1/models` |
| DeepSeek | `https://api.deepseek.com/v1/models` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/models?key=...` |

- **Caching** – results cached for 5 minutes (in-memory dict with expiry).
- **Fallback** – if a provider's endpoint fails, fall back to static lists defined in `orchestrator.py`.

### Response shape
```json
{
  "openai": {
    "models": ["gpt-4o", "gpt-5-nano"],
    "supports_thinking": false,
    "supports_streaming": true
  },
  "deepseek": {
    "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro"],
    "supports_thinking": true,
    "supports_streaming": true
  },
  "gemini": {
    "models": ["gemini-2.0-flash", "gemini-3.5-flash"],
    "supports_thinking": false,
    "supports_streaming": true
  }
}
```

### Implementation
- [ ] Add `GET /api/models` to `orchestrator.py`.
- [ ] Use `httpx.AsyncClient` to query each provider.
- [ ] Implement in-memory cache with 5-minute TTL.
- [ ] Add rate-limit fallback to static lists.
- [ ] Frontend: populate dropdowns from this endpoint.

---

## Feature 3: Query History

### New module `history.py`
```python
class QueryHistory:
    def __init__(self, max_entries: int = 500)
    def add(self, *, request, worker_responses, judge_thought, judge_response, model_used)
    def get_history(self, limit: int = 100) -> list[dict]
    def clear(self)
```

- Ring buffer – oldest entries are dropped when `max_entries` is exceeded.
- Each entry stores: `timestamp`, `request` (original user messages + system prompt), `worker_responses` (list of `{"model": ..., "response": ...}`), `judge_thought` (optional string), `judge_response` (final answer), `model_used` (e.g., `council-deepseek-v4-pro`).

### Integration in `orchestrator.py`
- Instantiate global `history = QueryHistory()`.
- After `run_council()` returns, call `history.add(...)` with:
  - The request data
  - Worker responses (captured inside `run_council`)
  - Judge's thought (extracted from `choices[0].message` – DeepSeek Pro returns a `reasoning_content` field when `extra_body` includes `{"thinking": {"type": "enabled"}}`)
  - Final answer and model name
- Expose `GET /api/history` (returns last N entries) and `DELETE /api/history` (clears history).

### Implementation
- [ ] Create `history.py` with the `QueryHistory` class.
- [ ] Add `GET /api/history` and `DELETE /api/history` routes.
- [ ] Modify `run_council()` to capture and return the judge's thought as an additional field.
- [ ] Modify existing endpoints to log history after each execution.
- [ ] Frontend: add collapsible history panel (right panel) with expandable worker/judge details.

---

## Feature 4: Self-Update via Webhook — 🟡 Partially Done

### Problem
The user must manually copy code from their laptop to the Ubuntu server VM. This is error-prone and slow.

### What's implemented so far
- **`restart.sh`** — A shell script that:
  - Runs `git pull origin main` to fetch the latest code.
  - Installs any new Python dependencies via `pip install -r requirements.txt --quiet`.
  - Finds the running `uvicorn orchestrator:app` process and sends a `SIGHUP` signal to gracefully restart it.
  - Falls back to starting a fresh instance if no process is found.
  - Logs each step to stdout for debugging.

### Proposed Solution (two-tier)
**Tier A – Non-Docker (git-based):**
- A protected endpoint `POST /api/update` that:
  1. Requires a secret token in the request body (configured via `UPDATE_SECRET` in `.env`).
  2. Runs `git pull origin main` in the app directory.
  3. Runs `pip install -r requirements.txt --quiet`.
  4. Restarts the uvicorn process (via subprocess or a `restart.sh` script).
- A `restart.sh` script that gracefully restarts the server. ✅ **Already implemented**
- Security risks: RCE if the secret leaks. Mitigated by token auth and optional IP allow-listing.

**Tier B – Docker (recommended for production):**
- Use [Watchtower](https://github.com/containrrr/watchtower) as a sidecar container that polls a Docker registry for new images and restarts the orchestrator container automatically.
- The user pushes updated images to Docker Hub / GHCR from their laptop.
- The VM runs `docker-compose up -d` with both the orchestrator and Watchtower.
- No manual `POST /api/update` endpoint needed – fully automated.

### Remaining work
- [ ] Add `UPDATE_SECRET` to `.env.example`.
- [ ] Add `POST /api/update` endpoint (non-Docker path) — calls `restart.sh` via `subprocess`.
- [ ] Create `docker-compose.yml` with Watchtower sidecar (Docker path).
- [ ] Update `Dockerfile` if needed for production readiness.

---

## Feature 5: Live .env Management

### Problem
The user must SSH into the VM or edit files manually to change API keys. The server must be restarted to pick up changes.

### Proposed Solution
- A protected endpoint `GET /api/env` that returns which keys are set (masked) vs missing.
- A protected endpoint `PUT /api/env` that accepts a JSON body with new key-value pairs and writes them to `.env`.
- After writing, the server re-initializes the affected API clients **without restarting**.

### Security
- Require `ENV_SECRET` token (set in `.env.example`) for any env-modifying request.
- Optionally require a confirmation step (read current keys first, then confirm overwrite).
- Never expose key values in responses – only show `"DEEPSEEK_API_KEY": "set"` or `"missing"`.

### UI Integration
- A Settings modal in the left or right panel triggered by a gear icon.
- Shows key status (set/missing) for each provider.
- Input fields to paste new keys.
- "Apply" button sends `PUT /api/env` and updates the dashboard status.

### Implementation
- [ ] Add `ENV_SECRET` to `.env.example`.
- [ ] Add `GET /api/env` endpoint (returns masked status).
- [ ] Add `PUT /api/env` endpoint (writes `.env` + re-initializes clients).
- [ ] Make API client initialization lazy/refreshable (e.g., a `get_client(provider)` function instead of module-level globals).
- [ ] Frontend: add Settings modal with key inputs and status indicators.
- [ ] Update dashboard to reflect whether each provider is properly configured.

---

## API Specification (All New Endpoints)

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/models` | None | Returns available models per provider (cached). |
| `GET` | `/api/history` | None | Returns the latest 100 queries. |
| `DELETE` | `/api/history` | None | Clears the in-memory history. |
| `PUT` | `/api/council/config` | None | Updates current runtime worker/judge config. |
| `POST` | `/api/update` | `UPDATE_SECRET` | Triggers git pull + restart (non-Docker). |
| `GET` | `/api/env` | `ENV_SECRET` | Returns which API keys are set/missing. |
| `PUT` | `/api/env` | `ENV_SECRET` | Writes new keys to `.env` and re-initializes clients. |

---

## Implementation Steps

### Step 1 – Backend scaffolding ✅ (partial)
- [x] Create webui files (index.html, style.css, app.js).
- [x] Serve webui via StaticFiles mount at `/ui`.
- [x] Add root redirect `/` → `/ui/index.html`.
- [x] Add `GET /api/info` with council configs, uptime, routes.
- [ ] Create `history.py` with the `QueryHistory` class.
- [ ] Add `GET /api/history` and `DELETE /api/history` routes.
- [ ] Add `GET /api/models` with provider model fetching and caching.
- [ ] Modify `run_council()` to return judge's thought.

### Step 2 – Dynamic Council Config
- [ ] Add `PUT /api/council/config` endpoint.
- [ ] Replace module-level `NORMAL_WORKERS` / `ADVANCED_WORKERS` with a mutable global config.
- [ ] Update frontend to allow model selection and config application.

### Step 3 – Query History UI
- [ ] Integrate history into `run_council()` and all endpoints.
- [ ] Add history panel to frontend (collapsible right panel).
- [ ] Show expandable worker responses and judge thought.

### Step 4 – Dynamic Model Discovery
- [ ] Implement `GET /api/models` with httpx and caching.
- [ ] Populate frontend dropdowns from this endpoint.

### Step 5 – .env Management
- [ ] Make API client initialization lazy (function-based).
- [ ] Add `GET /api/env` and `PUT /api/env` endpoints.
- [ ] Add Settings modal to frontend.

### Step 6 – Self-Update
- [x] Create `restart.sh`.
- [ ] Add `POST /api/update` endpoint.
- [ ] Create `docker-compose.yml` with Watchtower.

### Step 7 – Polish
- [ ] Add loading spinners and error handling for all API failures.
- [ ] Ensure responsive layout for mobile.
- [ ] Update `README.md` documenting all new endpoints and UI usage.

---

## What stays the same

- All existing endpoints (`/v1/normal`, `/v1/advanced`, their streaming variants, and `/health`).
- Core `run_council()` logic – only its return value is extended to include the judge's thought.
- Environment variables as the source of truth for API keys.

---

## Effort estimate

| Area | Estimated lines |
|------|-----------------|
| `history.py` | ~70 |
| `orchestrator.py` changes (all features) | ~250 |
| `webui/index.html` updates | ~80 |
| `webui/style.css` updates | ~60 |
| `webui/app.js` updates (all features) | ~400 |
| `restart.sh` | ~15 |
| `docker-compose.yml` | ~30 |
| **Total** | **~905** |