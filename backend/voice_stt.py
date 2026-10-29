"""Muse Voice Transcribe realtime STT as a Pipecat service (one per call).

Design: persistent websocket in ENDPOINTING mode (server finds turn ends, so no
local finalize needed). run_stt ships caller audio paced to realtime; the receive
loop maps server frames via muse_stt.parse_event into Interim/Transcription frames.
"""
import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.stt_service import STTService

import muse_stt

log = logging.getLogger("voice_stt")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s voice_stt %(levelname)s %(message)s"))
    log.addHandler(_h)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MuseSTTService(STTService):
    def __init__(self, *, api_key: str, languages: list[str],
                 keywords: list[str] | None = None,
                 sample_rate: int = 16000, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        if not api_key:
            raise RuntimeError("MODEL_API_KEY missing: voice STT cannot start")
        self._api_key = api_key
        self._languages = languages
        self._keywords = keywords or []
        self._sess = None
        self._ws = None
        self._rx_task = None
        self._pacer = muse_stt.AudioPacer()
        self._sent_bytes = 0
        self._peak = 0
        self._chunks = 0
        self._reconnecting = False
        self._last_reconnect = 0.0
        self.last_voice_at = time.monotonic()  # read by the silence watchdog
        self.last_audio_chunk_at = time.monotonic()  # inbound audio heartbeat
        self._pending = bytearray()  # caller audio held across socket blips
        self._max_pending = 10 * 32000  # ~10s; older than that is dropped

    async def setup(self, setup: FrameProcessorSetup):
        await super().setup(setup)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def cleanup(self):
        await super().cleanup()
        await self._disconnect()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """Ship caller audio (paced); transcripts arrive via the receive loop."""
        self.last_audio_chunk_at = time.monotonic()
        if self._ws is None and not self._reconnecting:
            # Socket died mid-call (question two goes nowhere without this).
            if time.monotonic() - self._last_reconnect > 3.0:
                self._reconnecting = True
                self._last_reconnect = time.monotonic()
                try:
                    await self._disconnect()
                    await self._connect()
                    log.info("stt reconnected mid-call")
                except Exception as e:
                    log.warning("stt reconnect failed: %s", e)
                finally:
                    self._reconnecting = False
        if self._ws is not None:
            try:
                # One paced queue: live audio joins the backlog, the backlog
                # drains at realtime pace, so blips delay words instead of
                # eating them. Cap bounds the memory.
                self._pending += audio
                if len(self._pending) > self._max_pending:
                    del self._pending[:len(self._pending) - self._max_pending]
                ok = self._pacer.allow(len(self._pending))
                if ok:
                    sent = bytes(self._pending[:ok])
                    await self._ws.send_bytes(sent)
                    del self._pending[:ok]
                    self._sent_bytes += ok
                    import audioop
                    try:
                        peak = audioop.max(sent, 2)
                    except Exception:
                        peak = -1
                    if peak > self._peak:
                        self._peak = peak
                    self._chunks += 1
                    if self._chunks % 250 == 0:  # ~5s of 20ms chunks
                        log.info("stt audio in: %d bytes, peak %d (0 = dead air)",
                                 self._sent_bytes, self._peak)
            except Exception as e:
                log.warning("stt send failed, dropping socket: %s", e)
                self._ws = None
        else:
            # Socket down: hold the words (capped) instead of dropping them.
            self._pending += audio
            if len(self._pending) > self._max_pending:
                del self._pending[:len(self._pending) - self._max_pending]
        yield None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

    async def _connect(self):
        import aiohttp
        log.info("stt connecting: %s", muse_stt.MODEL)
        self._pacer = muse_stt.AudioPacer()
        self._sess = aiohttp.ClientSession()
        try:
            self._ws = await self._sess.ws_connect(muse_stt.WS_URL)
        except Exception as e:
            log.warning("stt socket failed: %s", e)
            raise
        log.info("stt socket open")
        await self._ws.send_json(muse_stt.build_auth_frame(
            self._api_key, self._languages, self._keywords))
        self._rx_task = self.create_task(self._rx_loop())

    async def _disconnect(self):
        if self._rx_task:
            await self.cancel_task(self._rx_task)
            self._rx_task = None
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        sess, self._sess = self._sess, None
        if sess is not None:
            try:
                await sess.close()
            except Exception:
                pass

    async def _rx_loop(self):
        import aiohttp
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.ERROR):
                    log.warning("stt socket closed: %s", msg.type)
                    self._ws = None  # run_stt reconnects on the next chunk
                    break
                continue
            try:
                kind, payload = muse_stt.parse_event(json.loads(msg.data))
            except ValueError:
                continue
            text = (payload.get("text") or "").strip()
            if kind in ("start", "partial", "final", "end"):
                self.last_voice_at = time.monotonic()  # caller is talking now
            if kind == "session":
                log.info("stt session: %s", payload.get("id"))
            elif kind == "progress":
                pass  # audioProgress heartbeat; run_stt already reports volume
            elif kind == "partial" and text:
                log.info("stt partial: %.80s", text)
                await self.push_frame(InterimTranscriptionFrame(
                    text, self._user_id, _now(), None, result={"text": text}))
            elif kind == "final" and text:
                log.info("stt final: %.80s", text)
                await self.push_frame(TranscriptionFrame(
                    text, self._user_id, _now(), None, result={"text": text}))
            elif kind == "start":
                # Meta says the caller started talking: tell the pipeline so the
                # user aggregator opens a turn (and the bot can barge in).
                log.info("stt speech start (turn %s)", payload.get("turnId"))
                await self.push_frame(UserStartedSpeakingFrame())
            elif kind == "end":
                # Meta found the end of the turn: close it so the LLM fires.
                log.info("stt speech end (turn %s)", payload.get("turnId"))
                await self.push_frame(UserStoppedSpeakingFrame())
            elif kind == "unknown":
                log.info("stt unknown frame: %.200s", msg.data)


def selfcheck() -> None:
    """Offline: helpers only (live socket needs MODEL_API_KEY + network)."""
    import subprocess
    r = subprocess.run(["python3", "muse_stt.py", "selfcheck"], capture_output=True, text=True)
    assert "PASS" in r.stdout, r.stdout + r.stderr
    print("voice_stt selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python voice_stt.py selfcheck")
