"""Meta MMS voices: per-language TTS (offline-testable splitter + tag rule).

Live path (VPS): transformers VitsModel per business language, preloaded once,
sentence-by-sentence synthesis, 16kHz out. Voices: CC-BY-NC, demo-only.
"""
import re

# MMS model per Transcribe/template language
VOICES = {"en": "facebook/mms-tts-eng", "eng": "facebook/mms-tts-eng",
          "hi": "facebook/mms-tts-hin", "hin": "facebook/mms-tts-hin",
          "ta": "facebook/mms-tts-tam", "tam": "facebook/mms-tts-tam",
          "te": "facebook/mms-tts-tel", "tel": "facebook/mms-tts-tel",
          "kn": "facebook/mms-tts-kan", "kan": "facebook/mms-tts-kan",
          "bn": "facebook/mms-tts-ben", "ben": "facebook/mms-tts-ben",
          "mr": "facebook/mms-tts-mar", "mar": "facebook/mms-tts-mar"}

TAG = re.compile(r"^\[([a-z]{2,3})\]\s*")
SENT = re.compile(r"[^.!?।…]+[.!?।…]+|[^.!?।…]+$")


def strip_lang_tag(text: str) -> tuple[str, str]:
    """'[hi] namaste' -> ('hi', 'namaste'); missing tag -> ('', text)."""
    m = TAG.match(text)
    return (m.group(1), text[m.end():]) if m else ("", text)


def split_sentences(text: str) -> list[str]:
    """Native script in, no romanising; keeps danda and ellipsis as boundaries."""
    _, bare = strip_lang_tag(text)
    return [s.strip() for s in SENT.findall(bare) if s.strip()]


_voices: dict = {}


def get_voice(lang: str):
    """Load once per language (150MB each); thread-safe enough for one process."""
    code = VOICES.get(lang.lower())
    if not code:
        raise ValueError(f"no MMS voice for {lang}")
    if code not in _voices:
        from transformers import AutoTokenizer, VitsModel  # type: ignore
        import torch  # type: ignore
        torch.set_num_threads(2)
        _voices[code] = (VitsModel.from_pretrained(code),
                         AutoTokenizer.from_pretrained(code))
    return _voices[code]


def speak(text: str, lang: str) -> bytes:
    """Full text -> 16kHz PCM bytes, sentence by sentence (first chunk returns fast)."""
    import torch  # type: ignore
    model, tok = get_voice(lang)
    out = bytearray()
    with torch.inference_mode():
        for sent in split_sentences(text):
            ids = tok(sent, return_tensors="pt").input_ids
            wav = model(ids).waveform.squeeze().cpu().numpy()
            out += (wav * 32767).astype("<i2").tobytes()
    return bytes(out)


def selfcheck() -> None:
    assert strip_lang_tag("[hi] namaste") == ("hi", "namaste")
    assert strip_lang_tag("hello") == ("", "hello")
    assert split_sentences("[hi] haan. ek minute!") == ["haan.", "ek minute!"]
    assert split_sentences("मसाला डोसा। दाम १२०।") == ["मसाला डोसा।", "दाम १२०।"]
    assert split_sentences("வணக்கம்! எப்படி இருக்கீங்க?") == ["வணக்கம்!", "எப்படி இருக்கீங்க?"]
    assert len(VOICES["hi"]) > 0 and VOICES["eng"].endswith("eng")
    print("mms_tts selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python mms_tts.py selfcheck")
