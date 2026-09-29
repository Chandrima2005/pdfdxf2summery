"""Settings from environment variables (see .env.example)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    # Look in the project root (not the cwd), and accept ".env.txt" too - Windows Explorer
    # often saves ".env" as ".env.txt", which plain load_dotenv() silently ignores.
    for _name in (".env", ".env.txt"):
        if (ROOT / _name).is_file():
            load_dotenv(ROOT / _name)
            break
except ImportError:
    pass


def get(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v.strip().strip('"').strip("'") if v not in (None, "") else default


LLM_PROVIDER = (get("LLM_PROVIDER", "heuristic") or "heuristic").lower()  # openai | heuristic
LLM_MODEL = get("LLM_MODEL")
OPENAI_BASE_URL = get("OPENAI_BASE_URL")          # e.g. OpenRouter, Groq or Ollama endpoint
OPENAI_API_KEY = get("OPENAI_API_KEY")
EMBEDDING_MODEL = get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
CHUNK_STRATEGY = get("CHUNK_STRATEGY", "structure")
OPENAI_MODEL = get("OPENAI_MODEL") or LLM_MODEL

# web = hosted in a browser: always online.  desktop = installed copy (run.bat / run.sh sets it):
# the user may also choose the offline rule-based mode.
APP_MODE = (get("APP_MODE", "web") or "web").lower()
