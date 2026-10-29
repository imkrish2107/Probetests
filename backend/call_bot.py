"""One live call: Pipecat pipeline glue (wired at step 3 on the VPS).

Seams: transport adapter (WhatsApp WebRTC audio in/out), STT (muse_stt),
LLM (Muse Spark, OpenAI-compatible), TTS (mms_tts per-language voice).
This file owns turn persistence + cost accounting; audio transport plugs in.
"""
import logging
import os
from datetime import datetime, timezone

import db

log = logging.getLogger("call_bot")

LLM_BASE_URL = "https://api.meta.ai/v1"
MAX_TOKENS = 120  # spoken replies stay short (credit rule)

LIVE: dict[int, dict] = {}  # call_id -> {contact, started_at, language}; read by GET /api/live


def register_live(call_id: int, contact_name: str, language: str) -> None:
    LIVE[call_id] = {"call_id": call_id, "contact": contact_name,
                     "started_at": datetime.now(timezone.utc).isoformat(),
                     "language": language}


def unregister_live(call_id: int) -> None:
    LIVE.pop(call_id, None)


def live_calls() -> list[dict]:
    return list(LIVE.values())


def llm_config() -> dict:
    return {"base_url": LLM_BASE_URL, "model": os.getenv("LLM_MODEL", "muse-spark-1.3"),
            "max_completion_tokens": MAX_TOKENS, "reasoning_effort": "minimal",
            "stream": True}


def greeting(business_name: str, first_lang: str) -> str:
    tag = {"English": "en", "Hindi": "hi", "Tamil": "ta"}.get(first_lang, "en")
    line = {"en": f"Hi, this is {business_name}'s AI assistant. How can I help?",
            "hi": f"नमस्ते, मैं {business_name} का AI सहायक हूँ। मैं आपकी क्या मदद कर सकता हूँ?",
            "ta": f"வணக்கம், நான் {business_name}-இன் AI உதவியாளர். உங்களுக்கு எப்படி உதவலாம்?"}.get(tag, "")
    return f"[{tag}] {line}"


def save_turn(call_id: int, role: str, text: str, language: str = "",
              tokens_in: int = 0, tokens_out: int = 0, audio_s: float = 0.0) -> None:
    """Persist each turn as it happens; roll token/audio cost into the call."""
    from models import PRICE_IN_PER_1K, PRICE_OUT_PER_1K  # prices in one place
    cost = tokens_in / 1000 * PRICE_IN_PER_1K + tokens_out / 1000 * PRICE_OUT_PER_1K \
        + audio_s * 0.18 / 3600
    at = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        conn.execute("INSERT INTO transcripts (call_id, role, text, language, at)"
                     " VALUES (?,?,?,?,?)", (call_id, role, text, language, at))
        conn.execute("UPDATE calls SET tokens_in = tokens_in + ?, tokens_out = tokens_out + ?,"
                     " audio_seconds = audio_seconds + ?, cost_usd = cost_usd + ? WHERE id = ?",
                     (tokens_in, tokens_out, audio_s, cost, call_id))
        conn.commit()


async def run_call(business: dict, contact: dict, transport) -> None:
    """Full duplex loop. Transport = WhatsApp WebRTC adapter (step 3).

    Loop: caller audio -> muse_stt (barge-in on speechStart) -> Spark streaming
    (+ run_tool via agent.TOOLS, last 8 turns) -> mms_tts sentence by sentence.
    Silence 10s -> nudge; 10s more -> goodbye + terminate. end_call tool or
    hang-up -> terminate webhook finishes via automation.post_call.
    """
    raise NotImplementedError("transport adapter lands at step 3 (VPS + Pipecat WhatsApp docs)")


def selfcheck() -> None:
    """Offline: greeting tags + turn persistence/cost math on a temp DB."""
    import tempfile
    tmp = tempfile.mkdtemp()
    db.DB_PATH = db.Path(tmp) / "t.db"
    db.init_db()
    with db.connect() as c:
        c.execute("INSERT INTO businesses (slug, name) VALUES (?,?)", ("cafe", "Your Cafe"))
        c.execute("INSERT INTO contacts (business_id, wa_user_id) VALUES (?,?)", (1, "u1"))
        c.execute("INSERT INTO calls (business_id, contact_id) VALUES (?,?)", (1, 1))
        c.commit()
    assert greeting("Your Cafe", "Hindi").startswith("[hi]")
    assert "AI assistant" in greeting("Your Cafe", "English")
    save_turn(1, "caller", "hello", "en", tokens_in=10, tokens_out=5, audio_s=3.0)
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 1
        r = c.execute("SELECT tokens_in, tokens_out, audio_seconds FROM calls WHERE id=1").fetchone()
        assert tuple(r) == (10, 5, 3.0), tuple(r)
    assert llm_config()["reasoning_effort"] == "minimal"
    print("call_bot selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python call_bot.py selfcheck")
