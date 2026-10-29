"""Muse Voice Transcribe realtime STT as a Pipecat service (one per call).

Design: persistent websocket in ENDPOINTING mode (server finds turn ends, so no
local finalize needed). run_stt ships caller audio paced to realtime; the receive
loop maps server frames via muse_stt.parse_event into Interim/Transcription frames.
"""
import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    FrameDirection,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.services.stt_service import STTService

import muse_stt

log = logging.getLogger("voice_stt")


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
        if self._ws is not None:
            try:
                ok = self._pacer.allow(len(audio))
                if ok:
                    await self._ws.send_bytes(audio[:ok])
            except Exception as e:
                log.warning("stt send failed, dropping socket: %s", e)
                self._ws = None
        yield None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

    async def _connect(self):
        import aiohttp
        log.info("stt connecting: %s", muse_stt.MODEL)
        self._pacer = muse_stt.AudioPacer()
        self._sess = aiohttp.ClientSession()
        self._ws = await self._sess.ws_connect(muse_stt.WS_URL)
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
                    break
                continue
            try:
                kind, payload = muse_stt.parse_event(json.loads(msg.data))
            except ValueError:
                continue
            text = (payload.get("text") or "").strip()
            if kind == "partial" and text:
                await self.push_frame(InterimTranscriptionFrame(
                    text, self._user_id, _now(), None, result={"text": text}))
            elif kind == "final" and text:
                await self.push_frame(TranscriptionFrame(
                    text, self._user_id, _now(), None, result={"text": text}))
            elif kind == "unknown":
                log.debug("stt unknown frame: %.120s", msg.data)


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
