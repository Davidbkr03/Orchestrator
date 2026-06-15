import os
import asyncio
import time
import uuid
import json
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
# Model‑specific token limits
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
# Normal Council (all thinking OFF)
# -------------------------------------------------------------------------
NORMAL_WORKERS = [
    {"client": gemini_client, "model": "gemini-3.1-flash-lite"},
    {"client": openai_client, "model": "gpt-5-nano"},
    {"client": deepseek_client, "model": "deepseek-v4-flash"}
]
NORMAL_JUDGE = {"client": deepseek_client, "model": "deepseek-v4-flash", "thinking": False}

# -------------------------------------------------------------------------
# Advanced Council (workers no thinking, judge DeepSeek Pro with thinking)
# -------------------------------------------------------------------------
ADVANCED_WORKERS = [
    {"client": gemini_client, "model": "gemini-3.5-flash"},
    {"client": openai_client, "model": "gpt-5-mini"},
    {"client": deepseek_client, "model": "deepseek-v4-flash"}
]
ADVANCED_JUDGE = {"client": deepseek_client, "model": "deepseek-v4-pro", "thinking": True}

import time as time_module
SERVER_START_TIME = time_module.time()

@app.get("/api/info")
async def api_info():
    return {
        "normal_workers": [
            {"provider": "Gemini", "model": "gemini-3.1-flash-lite"},
            {"provider": "OpenAI", "model": "gpt-5-nano"},
            {"provider": "DeepSeek", "model": "deepseek-v4-flash"}
        ],
        "normal_judge": {"provider": "DeepSeek", "model": "deepseek-v4-flash", "thinking": False},
        "advanced_workers": [
            {"provider": "Gemini", "model": "gemini-3.5-flash"},
            {"provider": "OpenAI", "model": "gpt-5-mini"},
            {"provider": "DeepSeek", "model": "deepseek-v4-flash"}
        ],
        "advanced_judge": {"provider": "DeepSeek", "model": "deepseek-v4-pro", "thinking": True},
        "server_start_time": SERVER_START_TIME,
        "uptime_seconds": time_module.time() - SERVER_START_TIME,
        "server_time": time_module.time(),
        "routes": ["/v1/normal", "/v1/advanced", "/v1/normal/chat/completions", "/v1/advanced/chat/completions", "/health", "/api/info", "/"]
    }

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

    # Step 2: Synthesis prompt (includes the original conversation and the worker responses)
    # Build a summary of the conversation for the judge
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
    return await run_council(NORMAL_WORKERS, NORMAL_JUDGE, request)

@app.post("/v1/advanced")
async def advanced_route(request: CouncilRequest):
    return await run_council(ADVANCED_WORKERS, ADVANCED_JUDGE, request)

# -------------------------------------------------------------------------
# OpenAI‑compatible streaming endpoints (for LiteLLM / Open WebUI)
# -------------------------------------------------------------------------
@app.post("/v1/normal/chat/completions")
async def normal_chat_completions(request: Request):
    body = await request.json()
    stream = body.get("stream", False)
    messages = body.get("messages", [])
    # Extract system prompt from messages if present, otherwise use default
    system_prompt = "You are a helpful assistant."
    filtered_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
        else:
            filtered_messages.append(msg)
    max_tokens = body.get("max_tokens", 128000)
    temperature = body.get("temperature", 0.7)

    result = await run_council(NORMAL_WORKERS, NORMAL_JUDGE, CouncilRequest(
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

    result = await run_council(ADVANCED_WORKERS, ADVANCED_JUDGE, CouncilRequest(
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