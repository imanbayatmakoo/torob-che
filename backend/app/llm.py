"""Minimal async client for the BoxAPI OpenAI-compatible endpoint."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


def _load_env():
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
BASE = os.environ.get("BOXAPI_BASE_URL", "https://ai.boxapi.ir/ai/v1").rstrip("/")
KEY = os.environ.get("BOXAPI_API_KEY", "")
AGENT_MODEL = os.environ.get("AGENT_MODEL", "gpt-5.4-mini")
SHOP_MODEL = os.environ.get("SHOP_MODEL", "gpt-5.4-mini")

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
    return _client


async def chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None,
               max_tokens: int = 900, temperature: float | None = None) -> dict:
    body: dict = {"model": model or AGENT_MODEL, "messages": messages, "max_completion_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if temperature is not None:
        body["temperature"] = temperature
    last = None
    for _ in range(2):
        try:
            r = await client().post(f"{BASE}/chat/completions", json=body,
                                    headers={"Authorization": f"Bearer {KEY}"})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]
            last = f"{r.status_code}: {r.text[:300]}"
        except httpx.HTTPError as e:
            last = repr(e)
    raise RuntimeError(f"LLM error {last}")


def parse_args(tc: dict) -> dict:
    try:
        return json.loads(tc["function"]["arguments"] or "{}")
    except json.JSONDecodeError:
        return {}
