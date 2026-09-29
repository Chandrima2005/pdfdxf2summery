"""Provider-agnostic LLM wrapper.

Each client exposes the same two methods:
  complete(system, user, image_png=None) -> str
  run_tool_loop(system, user, tools, executor, max_steps) -> (text, trace)

Providers: 'openai' (any OpenAI-compatible endpoint, e.g. Gemini via OpenRouter) or
'heuristic' (offline, no LLM).
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Callable

from cad_copilot import config

Executor = Callable[[str, dict], dict]


class LLMClient:
    name = "base"
    supports_vision = True

    def complete(self, system: str, user: str, image_png: bytes | None = None) -> str:
        raise NotImplementedError

    def run_tool_loop(self, system: str, user: str, tools: list[dict], executor: Executor,
                      max_steps: int = 6) -> tuple[str, list[dict]]:
        raise NotImplementedError


def _dump(result: Any) -> str:
    s = json.dumps(result, default=str)
    return s if len(s) < 12000 else s[:12000] + '..."truncated"'


def _retry(fn, tries: int = 3):
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # rate limits / transient network errors
            if i == tries - 1:
                raise
            msg = str(exc).lower()
            if not any(k in msg for k in ("rate", "overloaded", "timeout", "529", "503", "connection")):
                raise
            time.sleep(2 ** (i + 1))


class OpenAICompatClient(LLMClient):
    """Works with OpenRouter (Gemini), OpenAI, Groq, Ollama... anything speaking the Chat Completions API."""
    name = "openai"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        from openai import OpenAI
        self.model = model or config.OPENAI_MODEL
        if not self.model:
            raise ValueError("Set LLM_MODEL (or OPENAI_MODEL) for the openai provider (a model your endpoint serves).")
        self.client = OpenAI(base_url=base_url or config.OPENAI_BASE_URL)  # reads OPENAI_API_KEY

    def complete(self, system, user, image_png=None):
        content: Any = user
        if image_png:
            content = [{"type": "text", "text": user},
                       {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image_png).decode()}}]
        resp = _retry(lambda: self.client.chat.completions.create(
            model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": content}]))
        return resp.choices[0].message.content or ""

    def run_tool_loop(self, system, user, tools, executor, max_steps=6):
        otools = [{"type": "function", "function": t} for t in tools]
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        trace: list[dict] = []
        for _ in range(max_steps):
            resp = _retry(lambda: self.client.chat.completions.create(model=self.model, messages=messages, tools=otools))
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return msg.content or "", trace
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = executor(tc.function.name, args)
                trace.append({"tool": tc.function.name, "args": args, "result": out})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": _dump(out)})
        return "Stopped: too many tool steps without a final answer.", trace


def get_client(provider: str | None = None, model: str | None = None) -> LLMClient | None:
    """Return a client, or None for the offline 'heuristic' mode."""
    provider = (provider or config.LLM_PROVIDER or "heuristic").lower()
    if provider == "openai":
        return OpenAICompatClient(model)
    return None
