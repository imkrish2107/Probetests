"""Meta MMS voices as a Pipecat TTS service (one per call, fixed language).

Replies carry a [lang] tag (see agent.build_prompt); the tag picks the voice when
present, else the call's default language. Synthesis runs in a worker thread so the
event loop never blocks on torch.
"""
import asyncio
import logging
from collections.abc import AsyncGenerator

from pipecat.frames.frames import Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService

log = logging.getLogger("voice_tts")

LANG_TAG = {"en": "en", "hi": "hi", "ta": "ta", "te": "te",
            "kn": "kn", "bn": "bn", "mr": "mr"}


class MMSTTSService(TTSService):
    def __init__(self, *, lang: str = "hi", sample_rate: int = 16000, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._lang = lang if lang in LANG_TAG else "hi"

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        from mms_tts import speak, strip_lang_tag
        tag, bare = strip_lang_tag(text)
        bare = bare.strip()
        if not bare:
            return
        lang = tag if tag in LANG_TAG else self._lang
        loop = asyncio.get_running_loop()
        try:
            pcm = await loop.run_in_executor(None, speak, bare, lang)
        except Exception as e:
            log.warning("tts synth failed (%s): %s", lang, e)
            return
        step = int(self.sample_rate * 2 * 0.5)  # half-second chunks
        for i in range(0, len(pcm), step):
            yield TTSAudioRawFrame(pcm[i:i + step], self.sample_rate, 1)


def selfcheck() -> None:
    """Offline: tag rule only (synthesis needs torch + downloaded voices)."""
    import subprocess
    r = subprocess.run(["python3", "mms_tts.py", "selfcheck"], capture_output=True, text=True)
    assert "PASS" in r.stdout, r.stdout + r.stderr
    print("voice_tts selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python voice_tts.py selfcheck")
