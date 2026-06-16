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
import httpx  # NEW: for direct HTTP model queries

load_dotenv()

# ... (all existing code up to fetch_available_models) ...

async def fetch_available_models():
    """Query each provider's models endpoint directly via HTTP and return a dict."""
    results = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        # --- DeepSeek ---
        try:
            resp = await client.get(
                "https://api.deepseek.com/v1/models",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                results["DeepSeek"] = sorted(models)
            else:
                results["DeepSeek"] = [f"error: HTTP {resp.status_code}"]
        except Exception as e:
            results["DeepSeek"] = [f"error: {str(e)}"]

        # --- OpenAI ---
        try:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                results["OpenAI"] = sorted(models)
            else:
                results["OpenAI"] = [f"error: HTTP {resp.status_code}"]
        except Exception as e:
            results["OpenAI"] = [f"error: {str(e)}"]

        # --- Gemini --- (special handling)
        try:
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": GEMINI_API_KEY}
            )
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    short_name = name.replace("models/", "", 1) if name.startswith("models/") else name
                    supported = m.get("supportedGenerationMethods", [])
                    # Include only models that can generate chat content
                    if "generateContent" in supported:
                        models.append(short_name)
                results["Gemini"] = sorted(models) if models else ["No chat models found"]
            else:
                results["Gemini"] = [f"error: HTTP {resp.status_code}"]
        except Exception as e:
            results["Gemini"] = [f"error: {str(e)}"]

    return results

# ... (rest of file unchanged) ...