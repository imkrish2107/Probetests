"""Meta MMS voices as a Pipecat TTS service (one per call, fixed language).

The voice follows the call's language (set by code); the LLM's tag is only
checked, never obeyed. Synthesis runs in a worker thread so the event loop
never blocks on torch.
"""
from __future__ import annotations  # keep annotations lazy: pipecat may be absent for selfcheck
import asyncio
import logging
import time
from collections.abc import AsyncGenerator

try:
    from pipecat.frames.frames import Frame, TTSAudioRawFrame
    from pipecat.services.tts_service import TTSService
    _HAS_PIPECAT = True
except ImportError:  # bare interpreter: only the offline parts of selfcheck run
    _HAS_PIPECAT = False

log = logging.getLogger("voice_tts")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s voice_tts %(levelname)s %(message)s"))
    log.addHandler(_h)

LANG_TAG = {"en": "en", "hi": "hi", "ta": "ta", "te": "te",
            "kn": "kn", "bn": "bn", "mr": "mr"}

_CACHE: dict = {}  # (normalized text, lang) -> PCM; greetings replay instantly


def _norm(text: str) -> str:
    import unicodedata
    from mms_tts import strip_lang_tag
    _, bare = strip_lang_tag(text)
    # Letters, numbers and vowel-signs in every script: Hindi/Tamil replies
    # key apart (plain \w drops matras, merging काल and कल into one key).
    return "".join(ch for ch in bare.lower() if unicodedata.category(ch)[0] in "LNM")


def warm(text: str, lang: str) -> None:
    """Synth once and cache (blocking: call in an executor, at startup/call open)."""
    key = (_norm(text), lang)
    if key in _CACHE:
        return
    from mms_tts import speak, strip_lang_tag
    tag, bare = strip_lang_tag(text)
    if bare.strip():
        _CACHE[key] = speak(bare, tag if tag in LANG_TAG else lang)


class MMSTTSService(TTSService if _HAS_PIPECAT else object):  # else: selfcheck-only shell
    def __init__(self, *, lang: str = "hi", sample_rate: int = 16000, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._lang = lang if lang in LANG_TAG else "hi"
        self.last_audio_at = 0.0  # last chunk spoken; read by the silence watchdog

    def set_lang(self, tag: str) -> None:
        """Code owns the voice: the caller's language, not the LLM's tag."""
        if tag in LANG_TAG:
            self._lang = tag

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        from mms_tts import speak_one, split_sentences, strip_lang_tag
        tag, bare = strip_lang_tag(text)
        if not bare.strip():
            return
        if tag and tag != self._lang:
            log.warning("tts tag [%s] != call lang %s, using call lang", tag, self._lang)
        lang = self._lang
        loop = asyncio.get_running_loop()
        step = int(self.sample_rate * 2 * 1.0)  # 1s chunks: fewer boundary gaps
        key = (_norm(text), lang)
        if key in _CACHE:
            pcm = _CACHE[key]
            log.info("tts cache hit: %.1fs audio", len(pcm) / 32000)
            for i in range(0, len(pcm), step):
                self.last_audio_at = time.monotonic()
                yield TTSAudioRawFrame(pcm[i:i + step], self.sample_rate, 1)
            return
        # Synth + stream one sentence at a time: first audio out after one
        # sentence, not after the whole reply.
        full = bytearray()
        for sent in split_sentences(text):
            t0 = time.monotonic()
            try:
                pcm = await loop.run_in_executor(None, speak_one, sent, lang)
            except Exception as e:
                log.warning("tts synth failed (%s): %s", lang, e)
                return
            log.info("tts synth: %d chars -> %.1fs audio in %.2fs",
                     len(sent), len(pcm) / 32000, time.monotonic() - t0)
            full += pcm
            for i in range(0, len(pcm), step):
                self.last_audio_at = time.monotonic()
                yield TTSAudioRawFrame(pcm[i:i + step], self.sample_rate, 1)
        if len(_CACHE) >= 20:  # short replies only; bound the RAM
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = bytes(full)


def selfcheck() -> None:
    """Offline: tag rule only (synthesis needs torch + downloaded voices)."""
    import subprocess
    r = subprocess.run(["python3", "mms_tts.py", "selfcheck"], capture_output=True, text=True)
    assert "PASS" in r.stdout, r.stdout + r.stderr
    assert _norm("[hi] मसाला डोसा") != _norm("[hi] नमस्ते")  # native script survives the key
    assert _norm("[hi] काल आऊंगा") != _norm("[hi] कल आऊंगा")  # vowel-signs count too
    assert _norm("[ta] வணக்கம்") != _norm("[ta] நன்றி")
    if not _HAS_PIPECAT:
        print("voice_tts selfcheck: PASS (service asserts skipped: no pipecat)")
        return
    svc = MMSTTSService(lang="en")
    assert svc._lang == "en"
    svc.set_lang("ta")
    assert svc._lang == "ta"
    svc.set_lang("xx")
    assert svc._lang == "ta"  # bogus tags never switch the voice
    print("voice_tts selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python voice_tts.py selfcheck")
