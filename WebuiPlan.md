# Fusion Orchestrator – Enhancement Plan

A roadmap for adding **Web UI**, **Dynamic Model Discovery**, and **Query History** to the existing orchestrator, without breaking any existing endpoints.

---

## Overview

| Feature               | Purpose | Status |
|-----------------------|---------|--------|
| Web UI                | Real-time dashboard for swapping configurations and sending test queries while the server runs | ❌ Not started |
| Dynamic Model Discovery | Query each provider’s API for available models/capabilities to populate a model picker with toggles | ❌ Not started |
| Query History         | In-memory ring buffer recording every query, worker responses, judge’s thought (if applicable), and final answer | ❌ Not started |

---

## Architecture

- **No breaking changes** – existing `/v1/normal`, `/v1/advanced`, and their streaming `/chat/completions` endpoints remain untouched.
- A new **global configuration object** replaces hardcoded `NORMAL_WORKERS` / `ADVANCED_WORKERS`, letting the UI update them live via a `PUT /api/council/config` endpoint.
- Static files for the UI are served from a `webui/` directory mounted under `/ui`.
- History is managed by a dedicated `history.py` module and exposed through read/clear REST endpoints.

---

## File Structure (planned)

```
.
├── orchestrator.py          # existing file – add model discovery, history routes, live config
├── history.py               # new module – QueryHistory class
├── webui/
│   ├── index.html           # main dashboard layout
│   ├── style.css            # dark‑theme styling
│   └── app.js               # frontend logic: fetch models, apply config, send queries, display history
└── README.md                # update with new endpoints
```

---

## Feature 1: Web UI

### Backend (`orchestrator.py`)
- Mount `webui/` as static files at `/ui` via `FastAPI`'s `StaticFiles`.
- Add `PUT /api/council/config` that accepts a JSON body with workers/judge definitions and updates the in‑memory council configuration.
- Existing `NORMAL_WORKERS` / `ADVANCED_WORKERS` become presets; the UI can select a preset or define a custom council.

### Frontend (`webui/index.html`, `style.css`, `app.js`)
- Single-page dark‑theme dashboard with three panels:
  - **Left panel** – Model picker populated from `/api/models`, per‑worker model dropdowns, thinking toggle (for judge), temperature/max‑tokens sliders, and “Apply Config” button.
  - **Center panel** – Chat-style input with conversation history, “Send” button that calls the streaming endpoint, and a live output area.
  - **Right panel (collapsible)** – Query history table with timestamp, user query, expandable worker responses, judge thought, and final answer.

---

## Feature 2: Dynamic Model Discovery

### Endpoint `GET /api/models`
For each configured provider (OpenAI, DeepSeek, Gemini), query their models list endpoint:

| Provider  | URL                                                              |
|-----------|------------------------------------------------------------------|
| OpenAI    | `https://api.openai.com/v1/models`                               |
| DeepSeek  | `https://api.deepseek.com/v1/models`                              |
| Gemini    | `https://generativelanguage.googleapis.com/v1beta/models?key=...` |

- **Caching** – results cached for 5 minutes (in‑memory dict with expiry).
- **Fallback** – if a provider’s endpoint fails, fall back to static lists defined in `orchestrator.py`.

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
  - Judge’s thought (extracted from `choices[0].message` – DeepSeek Pro returns a `reasoning_content` field when `extra_body` includes `{"thinking": {"type": "enabled"}}`)
  - Final answer and model name
- Expose `GET /api/history` (returns last N entries) and `DELETE /api/history` (clears history).

---

## API Specification (New)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/models` | Returns available models per provider. |
| `GET` | `/api/history` | Returns the latest 100 queries. |
| `DELETE` | `/api/history` | Clears the in‑memory history. |
| `PUT` | `/api/council/config` | Updates current runtime worker/judge config. |

---

## Implementation Steps

### Step 1 – Backend scaffolding
- [ ] Create `history.py` with the `QueryHistory` class.
- [ ] In `orchestrator.py`:
  - [ ] Create global history instance.
  - [ ] Add `/api/models` endpoint with provider‑specific model fetching and caching.
  - [ ] Add `GET /api/history` and `DELETE /api/history` routes.
  - [ ] Modify `run_council()` to capture and return the judge’s thought as an additional field.
  - [ ] Modify existing endpoints to log history after each execution.

### Step 2 – Web UI static files
- [ ] Create `webui/index.html`.
- [ ] Create `webui/style.css`.
- [ ] Create `webui/app.js`.
- [ ] Serve them via `StaticFiles` mount at `/ui`.
- [ ] Add a root redirect (`/` → `/ui/index.html`).

### Step 3 – Frontend–backend integration
- [ ] On page load, fetch `/api/models` to populate dropdowns.
- [ ] “Apply Config” sends `PUT /api/council/config` with current selections.
- [ ] “Send” button calls the streaming endpoint and renders output in chat area.
- [ ] Poll `/api/history` every 2 seconds (or use SSE) to update the history panel.

### Step 4 – Polish
- [ ] Add loading spinners and error handling for API failures.
- [ ] Ensure responsive layout for mobile.
- [ ] Update `README.md` documenting new endpoints and UI usage.

---

## What stays the same

- All existing endpoints (`/v1/normal`, `/v1/advanced`, their streaming variants, and `/health`).
- Core `run_council()` logic – only its return value is extended to include the judge’s thought.
- Environment variables and API keys.

---

## Effort estimate

| Area                | Estimated lines |
|---------------------|-----------------|
| `history.py`        | ~70             |
| `orchestrator.py` changes | ~80       |
| `webui/index.html`  | ~150            |
| `webui/style.css`   | ~200            |
| `webui/app.js`      | ~350            |
| **Total**           | **~850**        |