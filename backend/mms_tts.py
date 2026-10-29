"""Meta MMS voices: per-language TTS (offline-testable splitter + tag rule).

Live path (VPS): transformers VitsModel per business language, preloaded once,
sentence-by-sentence synthesis, 16kHz out. Voices: CC-BY-NC, demo-only.
"""
import os
import re

# MMS ships one fixed voice per language (male-sounding for en); shift the pitch
# up to feminize. Tune by ear: VOICE_PITCH_SEMITONES=0 is the raw voice.
PITCH_SEMITONES = float(os.getenv("VOICE_PITCH_SEMITONES", "3"))

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
        torch.set_num_threads(max(2, os.cpu_count() or 2))  # synth speed scales
        _voices[code] = (VitsModel.from_pretrained(code),
                         AutoTokenizer.from_pretrained(code))
    return _voices[code]


def pitch_shift(pcm: bytes, semitones: float) -> bytes:
    """Phase-vocoder pitch shift, duration preserved; 0 returns input as-is.

    shortcut: formants shift with pitch (chipmunk past +5); upgrade to a
    formant-preserving shifter if voices sound unnatural.
    """
    if not semitones:
        return pcm
    import numpy as np
    rate = 2.0 ** (semitones / 12.0)
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    n_in = len(x)
    N, H = 2048, 512
    win = np.hanning(N + 1)[:-1].astype(np.float32)
    pad = N // 2
    xp = np.concatenate([np.zeros(pad, dtype=np.float32), x,
                         np.zeros(pad + (-(n_in + pad) % H), dtype=np.float32)])
    n_frames = max(2, 1 + (len(xp) - N) // H)
    need = (n_frames - 1) * H + N
    if len(xp) < need:
        xp = np.concatenate([xp, np.zeros(need - len(xp), dtype=np.float32)])
    frames = xp[(np.arange(n_frames) * H)[:, None] + np.arange(N)] * win
    spec = np.fft.rfft(frames, axis=1)
    mag, phase = np.abs(spec), np.angle(spec)
    omega = (2 * np.pi * H * np.arange(spec.shape[1]) / N).astype(np.float32)
    dphi = np.diff(phase, axis=0) - omega
    dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
    inst = np.vstack([omega, omega + dphi])  # true freq per input frame
    n_out = max(2, int(round(n_frames / rate)))
    pos = np.minimum(np.arange(n_out) * rate, n_frames - 1.001)
    i0 = pos.astype(int)
    frac = (pos - i0)[:, None].astype(np.float32)
    i1 = np.minimum(i0 + 1, n_frames - 1)
    out_mag = mag[i0] * (1 - frac) + mag[i1] * frac
    adv = inst[i0] * (1 - frac) + inst[i1] * frac
    out_ph = np.empty_like(out_mag)
    out_ph[0] = phase[i0[0]]
    out_ph[1:] = out_ph[0] + np.cumsum(adv[1:], axis=0)
    y_frames = np.fft.irfft(out_mag * np.exp(1j * out_ph), n=N, axis=1) * win
    y_len = (n_out - 1) * H + N
    y = np.zeros(y_len, dtype=np.float32)
    wsum = np.zeros(y_len, dtype=np.float32)
    for t in range(n_out):
        s = t * H
        y[s:s + N] += y_frames[t]
        wsum[s:s + N] += win * win
    nz = wsum > 1e-6
    y[nz] /= wsum[nz]
    y = y[pad:]  # drop leading pad; resample back to original length
    y = np.interp(np.linspace(0, 1, n_in), np.linspace(0, 1, len(y)), y)
    return (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()


def speak_one(sent: str, lang: str) -> bytes:
    """One sentence -> 16kHz PCM bytes (voice cached; worker-thread safe)."""
    import torch  # type: ignore
    model, tok = get_voice(lang)
    with torch.inference_mode():
        wav = model(tok(sent, return_tensors="pt").input_ids).waveform.squeeze().cpu().numpy()
    return pitch_shift((wav * 32767).astype("<i2").tobytes(), PITCH_SEMITONES)


def speak(text: str, lang: str) -> bytes:
    """Full text -> 16kHz PCM bytes, sentence by sentence (see speak_one)."""
    out = bytearray()
    for sent in split_sentences(text):
        out += speak_one(sent, lang)
    return bytes(out)


def selfcheck() -> None:
    assert strip_lang_tag("[hi] namaste") == ("hi", "namaste")
    assert strip_lang_tag("hello") == ("", "hello")
    assert split_sentences("[hi] haan. ek minute!") == ["haan.", "ek minute!"]
    assert split_sentences("मसाला डोसा। दाम १२०।") == ["मसाला डोसा।", "दाम १२०।"]
    assert split_sentences("வணக்கம்! எப்படி இருக்கீங்க?") == ["வணக்கம்!", "எப்படி இருக்கீங்க?"]
    assert len(VOICES["hi"]) > 0 and VOICES["eng"].endswith("eng")
    try:
        import numpy as np
    except ImportError:
        print("mms_tts selfcheck: PASS (pitch test skipped: no numpy)")
        return
    sr = 16000
    t = np.arange(sr // 2) / sr
    sine = (np.sin(2 * np.pi * 440 * t) * 20000).astype(np.int16).tobytes()

    def peak_hz(pcm: bytes) -> float:
        spec = np.abs(np.fft.rfft(np.frombuffer(pcm, dtype=np.int16).astype(np.float32)))
        return float(np.argmax(spec[1:]) + 1) * sr / (sr // 2)

    assert pitch_shift(sine, 0) == sine  # no-op path is bit-exact
    assert abs(peak_hz(pitch_shift(sine, 12)) - 880) < 60, peak_hz(pitch_shift(sine, 12))
    assert abs(peak_hz(pitch_shift(sine, -12)) - 220) < 60
    assert len(pitch_shift(sine, 5)) == len(sine)  # duration preserved
    print("mms_tts selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python mms_tts.py selfcheck")
