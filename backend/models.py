"""Muse Spark chat via Meta Model API (OpenAI-compatible)."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.meta.ai/v1"
# Price per 1k tokens in USD; update when Meta publishes pricing.
# Stays 0 until then so cost math never lies.
PRICE_IN_PER_1K = float(os.getenv("PRICE_IN_PER_1K", "0"))
PRICE_OUT_PER_1K = float(os.getenv("PRICE_OUT_PER_1K", "0"))


def reply(prompt: str, model: str | None = None, max_tokens: int = 120) -> dict:
    """Send one chat prompt, return reply + token counts + cost."""
    key = os.getenv("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY missing in backend/.env")
    model = model or os.getenv("LLM_MODEL", "muse-spark-1.3")
    resp = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            # Spark over-thinks; cap it so short replies survive the budget.
            "reasoning_effort": "minimal",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    cost = tin / 1000 * PRICE_IN_PER_1K + tout / 1000 * PRICE_OUT_PER_1K
    return {"text": text, "tokens_in": tin, "tokens_out": tout, "cost_usd": cost}
