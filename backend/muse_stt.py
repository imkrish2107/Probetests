"""Muse Voice Transcribe realtime: protocol pieces (offline-testable) + thin service.

Live path (needs MODEL_API_KEY): one WebSocket per call, ENDPOINTING mode,
first frame carries the key, binary PCM_16KHZ frames paced at realtime.
"""
import time

WS_URL = "wss://api.meta.ai/v1/asr/realtime"
MODEL = "muse-voice-transcribe-1.0"
SAMPLE_RATE = 16000
BYTES_PER_SEC = SAMPLE_RATE * 2  # 16-bit mono
MAX_AHEAD_SEC = 5  # never send more than 5s of audio ahead of realtime


def build_auth_frame(key: str, languages: list[str], keywords: list[str]) -> dict:
    return {"authorization": {"accessToken": f"Bearer {key}"}, "model": MODEL,
            "audioEncoding": "PCM_16KHZ", "mode": "ENDPOINTING",
            "partialMode": "CUMULATIVE", "languageBias": languages, "keywords": keywords}


def parse_event(msg: dict) -> tuple[str, dict]:
    """Map a server frame to (kind, payload). Kinds: session/start/partial/end/final/unknown.

    shortcut: exact Meta field names unverified; confirm against the docs on first live run.
    """
    if "sessionId" in msg:
        return "session", {"id": msg["sessionId"]}
    kind = msg.get("type", "")
    if kind == "audioProgress":
        return "progress", {"ms": msg.get("audioProcessedMs")}
    if kind == "speechStart":
        return "start", {"turnId": msg.get("turnId")}
    if kind == "speechEnd":
        return "end", {"turnId": msg.get("turnId")}
    if kind in ("transcript", "partial"):
        return "partial", {"text": msg.get("text", ""), "turnId": msg.get("turnId")}
    if kind in ("speechComplete", "final"):
        return "final", {"text": msg.get("text", ""), "turnId": msg.get("turnId")}
    return "unknown", {}


class AudioPacer:
    """Cap send-ahead at MAX_AHEAD_SEC of audio. Clock injectable for tests."""

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.start = self.clock()
        self.sent = 0

    def allow(self, nbytes: int) -> int:
        """Bytes of a chunk we may send right now (0 = wait)."""
        budget = int((self.clock() - self.start) * BYTES_PER_SEC) + MAX_AHEAD_SEC * BYTES_PER_SEC
        ok = max(0, min(nbytes, budget - self.sent))
        self.sent += ok
        return ok


def create_service(on_final, on_start=None):
    """Build the Pipecat STT service (import here so selfcheck needs no deps)."""
    try:
        from pipecat.services.stt_service import STTService  # type: ignore
    except ImportError as e:
        raise RuntimeError("pip install pipecat-ai (VPS setup, backend.md)") from e
    raise NotImplementedError("wire to Pipecat STTService at step 4: auth frame, "
                              "paced PCM frames, parse_event -> on_final/on_start")


def selfcheck() -> None:
    f = build_auth_frame("k", ["English", "Hindi"], ["Cafe"])
    assert f["authorization"] == {"accessToken": "Bearer k"}
    assert f["mode"] == "ENDPOINTING" and f["partialMode"] == "CUMULATIVE"
    assert parse_event({"sessionId": "s"}) == ("session", {"id": "s"})
    assert parse_event({"type": "speechStart", "turnId": 3}) == ("start", {"turnId": 3})
    assert parse_event({"type": "transcript", "text": "nam", "turnId": 3})[0] == "partial"
    assert parse_event({"type": "speechComplete", "text": "namaste", "turnId": 3}) == (
        "final", {"text": "namaste", "turnId": 3})
    assert parse_event({"nope": 1})[0] == "unknown"
    now = [0.0]
    p = AudioPacer(clock=lambda: now[0])
    assert p.allow(10 * BYTES_PER_SEC) == 5 * BYTES_PER_SEC  # capped at 5s ahead
    now[0] = 10.0  # 10s elapsed: budget 15s, sent 5s
    assert p.allow(20 * BYTES_PER_SEC) == 10 * BYTES_PER_SEC
    print("muse_stt selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python muse_stt.py selfcheck")
