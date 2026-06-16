import os
import asyncio
import time
import uuid
import json
from typing import Optional
from fastapi import FastAPI, HTTPException, Request

from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Fusion Orchestrator")

app.mount("/ui", StaticFiles(directory="webui", html=True), name="ui")

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/ui/index.html")

# -------------------------------------------------------------------------
# Direct API clients
# -------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY missing")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY missing")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY missing")

deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url="https://api.openai.com/v1")
gemini_client = AsyncOpenAI(api_key=GEMINI_API_KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")

# -------------------------------------------------------------------------
# Provider -> client mapping
# -------------------------------------------------------------------------
PROVIDER_CLIENTS = {
    "DeepSeek": deepseek_client,
    "OpenAI": openai_client,
    "Gemini": gemini_client,
}
PROVIDER_BASE_URLS = {
    "DeepSeek": "https://api.deepseek.com/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

# -------------------------------------------------------------------------
# Model-specific token limits
# -------------------------------------------------------------------------
MODEL_LIMITS = {
    "deepseek-v4-flash": 256_000,
    "deepseek-v4-pro":   256_000,
    "gpt-5-nano": 128_000,
    "gpt-5-mini": 128_000,
    "gemini-3.1-flash-lite": 128_000,
    "gemini-3.5-flash":      128_000,
}

def get_max_tokens_for_model(model_name: str, requested: int) -> int:
    limit = MODEL_LIMITS.get(model_name, 128_000)
    return min(requested, limit)

# -------------------------------------------------------------------------
# Mutable council configurations (defaults)
# -------------------------------------------------------------------------
NORMAL_WORKERS = [
    {"provider": "Gemini", "model": "gemini-3.1-flash-lite"},
    {"provider": "OpenAI", "model": "gpt-5-nano"},
    {"provider": "DeepSeek", "model": "deepseek-v4-flash"}
]
NORMAL_JUDGE = {"provider": "DeepSeek", "model": "deepseek-v4-flash", "thinking": False}

ADVANCED_WORKERS = [
    {"provider": "Gemini", "model": "gemini-3.5-flash"},
    {"provider": "OpenAI", "model": "gpt-5-mini"},
    {"provider": "DeepSeek", "model": "deepseek-v4-flash"}
]
ADVANCED_JUDGE = {"provider": "DeepSeek", "model": "deepseek-v4-pro", "thinking": True}

# Deep copies of defaults for resetting
DEFAULT_NORMAL_WORKERS = [w.copy() for w in NORMAL_WORKERS]
DEFAULT_NORMAL_JUDGE = dict(NORMAL_JUDGE)
DEFAULT_ADVANCED_WORKERS = [w.copy() for w in ADVANCED_WORKERS]
DEFAULT_ADVANCED_JUDGE = dict(ADVANCED_JUDGE)

# Helpers to convert config dicts to the runtime structure used by run_council
def worker_to_runtime(w: dict) -> dict:
    return {
        "client": PROVIDER_CLIENTS[w["provider"]],
        "model": w["model"],
    }

def judge_to_runtime(j: dict) -> dict:
    return {
        "client": PROVIDER_CLIENTS[j["provider"]],
        "model": j["model"],
        "thinking": j.get("thinking", False),
    }

# -------------------------------------------------------------------------
# Model cache (from API queries)
# -------------------------------------------------------------------------
_models_cache = None
_models_cache_time = 0
MODEL_CACHE_TTL = 300  # 5 minutes

async def fetch_available_models():
    """Query each provider's /models endpoint and return a dict."""
    results = {}
    for provider, client in PROVIDER_CLIENTS.items():
        try:
            resp = await client.models.list()
            models = [m.id for m in resp.data]
            results[provider] = sorted(models)
        except Exception as e:
            results[provider] = [f"error: {str(e)}"]
    return results

# -------------------------------------------------------------------------
import time as time_module
SERVER_START_TIME = time_module.time()

def serialize_worker(workers: list) -> list:
    return [{"provider": w["provider"], "model": w["model"]} for w in workers]

def serialize_judge(judge: dict) -> dict:
    return {
        "provider": judge["provider"],
        "model": judge["model"],
        "thinking": judge.get("thinking", False),
    }

@app.get("/api/info")
async def api_info():
    return {
        "normal_workers": serialize_worker(NORMAL_WORKERS),
        "normal_judge": serialize_judge(NORMAL_JUDGE),
        "advanced_workers": serialize_worker(ADVANCED_WORKERS),
        "advanced_judge": serialize_judge(ADVANCED_JUDGE),
        "server_start_time": SERVER_START_TIME,
        "uptime_seconds": time_module.time() - SERVER_START_TIME,
        "server_time": time_module.time(),
        "routes": ["/v1/normal", "/v1/advanced", "/v1/normal/chat/completions",
                   "/v1/advanced/chat/completions", "/health", "/api/info",
                   "/api/models", "/api/swap-models", "/api/reset-models", "/"]
    }

# -------------------------------------------------------------------------
# Models endpoint
# -------------------------------------------------------------------------
@app.get("/api/models")
async def api_models():
    global _models_cache, _models_cache_time
    now = time_module.time()
    if _models_cache is None or (now - _models_cache_time) > MODEL_CACHE_TTL:
        _models_cache = await fetch_available_models()
        _models_cache_time = now
    return _models_cache

# -------------------------------------------------------------------------
# Swap models endpoint
# -------------------------------------------------------------------------
class SwapModelsRequest(BaseModel):
    council: str  # "normal" or "advanced"
    slot_type: str  # "worker" or "judge"
    slot_index: Optional[int] = None  # index for workers, None for judge
    provider: str
    model: str
    thinking: bool = False

@app.post("/api/swap-models")
async def swap_models(req: SwapModelsRequest):
    if req.council not in ("normal", "advanced"):
        raise HTTPException(400, "Invalid council. Use 'normal' or 'advanced'.")

    if req.slot_type == "worker":
        if req.slot_index is None:
            raise HTTPException(400, "slot_index required for worker slots")
        if req.council == "normal":
            if req.slot_index < 0 or req.slot_index >= len(NORMAL_WORKERS):
                raise HTTPException(400, "Invalid worker index")
            NORMAL_WORKERS[req.slot_index] = {"provider": req.provider, "model": req.model}
        else:
            if req.slot_index < 0 or req.slot_index >= len(ADVANCED_WORKERS):
                raise HTTPException(400, "Invalid worker index")
            ADVANCED_WORKERS[req.slot_index] = {"provider": req.provider, "model": req.model}
    elif req.slot_type == "judge":
        if req.council == "normal":
            NORMAL_JUDGE["provider"] = req.provider
            NORMAL_JUDGE["model"] = req.model
            NORMAL_JUDGE["thinking"] = req.thinking
        else:
            ADVANCED_JUDGE["provider"] = req.provider
            ADVANCED_JUDGE["model"] = req.model
            ADVANCED_JUDGE["thinking"] = req.thinking
    else:
        raise HTTPException(400, "Invalid slot_type. Use 'worker' or 'judge'.")

    return {"status": "ok", "message": f"{req.council} {req.slot_type} updated"}

# -------------------------------------------------------------------------
# Reset models endpoint
# -------------------------------------------------------------------------
@app.post("/api/reset-models")
async def reset_models():
    global NORMAL_WORKERS, NORMAL_JUDGE, ADVANCED_WORKERS, ADVANCED_JUDGE
    NORMAL_WORKERS = [w.copy() for w in DEFAULT_NORMAL_WORKERS]
    NORMAL_JUDGE = dict(DEFAULT_NORMAL_JUDGE)
    ADVANCED_WORKERS = [w.copy() for w in DEFAULT_ADVANCED_WORKERS]
    ADVANCED_JUDGE = dict(DEFAULT_ADVANCED_JUDGE)
    return {"status": "ok", "message": "Models reset to defaults"}

# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------
class CouncilRequest(BaseModel):
    messages: list  # Full conversation history
    system_prompt: str = "You are a helpful assistant."
    max_tokens: int = Field(128_000, description="Maximum tokens to generate")
    temperature: float = 0.7

class CouncilResponse(BaseModel):
    content: str
    model_used: str

# -------------------------------------------------------------------------
# Core council execution logic (now accepts full messages)
# -------------------------------------------------------------------------
async def run_council(workers: list, judge: dict, request: CouncilRequest) -> CouncilResponse:
    # Prepare the messages for workers: add system prompt at the beginning if not already present
    full_messages = []
    if request.system_prompt:
        full_messages.append({"role": "system", "content": request.system_prompt})
    full_messages.extend(request.messages)

    # Step 1: Call all workers in parallel with the full conversation history
    async def call_worker(worker):
        model_name = worker["model"]
        effective_max = get_max_tokens_for_model(model_name, request.max_tokens)
        try:
            resp = await worker["client"].chat.completions.create(
                model=model_name,
                messages=full_messages,
                max_tokens=effective_max,
                temperature=request.temperature
            )
            return {"model": model_name, "response": resp.choices[0].message.content}
        except Exception as e:
            return {"model": model_name, "response": f"ERROR: {str(e)}"}

    tasks = [call_worker(w) for w in workers]
    worker_responses = await asyncio.gather(*tasks)

    for wr in worker_responses:
        print(f"[Council] Worker: {wr['model']} (max_tokens: {get_max_tokens_for_model(wr['model'], request.max_tokens)})")

    # Step 2: Synthesis prompt
    conv_text = "\n".join([f"{m['role']}: {m['content']}" for m in request.messages])
    synthesis_prompt = f"""
Original conversation history:
{conv_text}

System instruction: {request.system_prompt}

Multiple responses were generated for the last user message. Your task is to analyze all responses and produce a single, final answer that synthesizes the best aspects of each:

{worker_responses[0]['model']}: {worker_responses[0]['response']}
{worker_responses[1]['model']}: {worker_responses[1]['response']}
{worker_responses[2]['model']}: {worker_responses[2]['response']}

Instructions:
1. Identify the most accurate, relevant, and helpful information from each response.
2. Combine them into a single, coherent, final answer.
3. Do NOT mention that multiple responses were fused. Present the answer as a unified response.
4. Ensure the final answer directly addresses the original conversation.
5. Use tool calling as you normally would, you still decide the final output but with assistance from the other models.
    """

    # Step 3: Judge synthesis
    try:
        judge_model_name = judge["model"]
        judge_effective_max = get_max_tokens_for_model(judge_model_name, request.max_tokens)
        judge_kwargs = {
            "model": judge_model_name,
            "messages": [
                {"role": "system", "content": "You are a world-class expert at synthesizing information from multiple sources into a single, accurate, and helpful response."},
                {"role": "user", "content": synthesis_prompt}
            ],
            "max_tokens": judge_effective_max,
            "temperature": 0.3
        }
        if judge.get("thinking"):
            judge_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            print(f"[Council] Judge: {judge_model_name} (thinking: ON, max_tokens: {judge_effective_max})")
        else:
            print(f"[Council] Judge: {judge_model_name} (thinking: OFF, max_tokens: {judge_effective_max})")

        judge_response = await judge["client"].chat.completions.create(**judge_kwargs)
        final_answer = judge_response.choices[0].message.content
        return CouncilResponse(content=final_answer, model_used=f"council-{judge_model_name}")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------------------------------------------------
# Simple test endpoints (direct curl) - now accept messages
# -------------------------------------------------------------------------
@app.post("/v1/normal")
async def normal_route(request: CouncilRequest):
    workers_runtime = [worker_to_runtime(w) for w in NORMAL_WORKERS]
    judge_runtime = judge_to_runtime(NORMAL_JUDGE)
    return await run_council(workers_runtime, judge_runtime, request)

@app.post("/v1/advanced")
async def advanced_route(request: CouncilRequest):
    workers_runtime = [worker_to_runtime(w) for w in ADVANCED_WORKERS]
    judge_runtime = judge_to_runtime(ADVANCED_JUDGE)
    return await run_council(workers_runtime, judge_runtime, request)

# -------------------------------------------------------------------------
# OpenAI-compatible streaming endpoints
# -------------------------------------------------------------------------
@app.post("/v1/normal/chat/completions")
async def normal_chat_completions(request: Request):
    body = await request.json()
    stream = body.get("stream", False)
    messages = body.get("messages", [])
    system_prompt = "You are a helpful assistant."
    filtered_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
        else:
            filtered_messages.append(msg)
    max_tokens = body.get("max_tokens", 128000)
    temperature = body.get("temperature", 0.7)

    workers_runtime = [worker_to_runtime(w) for w in NORMAL_WORKERS]
    judge_runtime = judge_to_runtime(NORMAL_JUDGE)
    result = await run_council(workers_runtime, judge_runtime, CouncilRequest(
        messages=filtered_messages,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature
    ))
    if not stream:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "normal-council",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": result.content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    async def generate():
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'normal-council', 'choices': [{'index': 0, 'delta': {'content': result.content}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'normal-council', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/v1/advanced/chat/completions")
async def advanced_chat_completions(request: Request):
    body = await request.json()
    stream = body.get("stream", False)
    messages = body.get("messages", [])
    system_prompt = "You are a helpful assistant."
    filtered_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
        else:
            filtered_messages.append(msg)
    max_tokens = body.get("max_tokens", 128000)
    temperature = body.get("temperature", 0.7)

    workers_runtime = [worker_to_runtime(w) for w in ADVANCED_WORKERS]
    judge_runtime = judge_to_runtime(ADVANCED_JUDGE)
    result = await run_council(workers_runtime, judge_runtime, CouncilRequest(
        messages=filtered_messages,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature
    ))
    if not stream:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "advanced-council",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": result.content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    async def generate():
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'advanced-council', 'choices': [{'index': 0, 'delta': {'content': result.content}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'advanced-council', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok"}