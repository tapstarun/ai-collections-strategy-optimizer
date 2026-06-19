"""Central configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # loads .env if present; safe no-op otherwise

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "borrowers.json"

# --- LLM wrapper (from ai-interview-docs.txt) ---
LLM_API_TOKEN: str = os.getenv("LLM_API_TOKEN", "").strip()
LLM_API_URL: str = os.getenv(
    "LLM_API_URL",
    "https://llm-wrapper-741152993481.asia-south1.run.app/llm/query",
).strip()
LLM_TIMEOUT_S: int = int(os.getenv("LLM_TIMEOUT_S", "15"))

# --- Abuse / reliability controls ---
RATE_LIMIT: str = os.getenv("RATE_LIMIT", "30/minute")

# Optional shared API key. When set, all protected endpoints require a matching
# `X-API-Key` header. This is a coarse gate on top of the (mocked) role headers; real
# identity would come from OAuth2/OIDC + JWT. Leave unset to keep local dev frictionless.
API_KEY: str = os.getenv("API_KEY", "").strip()

# When no token is configured we run fully offline using safe templates.
LLM_ENABLED: bool = bool(LLM_API_TOKEN)
