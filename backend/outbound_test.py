"""STORE_BUILD Phase 1: prove a business-initiated call works, then STOP.

Run on the VPS (venv has aiortc via pipecat, torch for MMS):
  cd /home/wa/Probetests/backend
  .venv/bin/python outbound.py selfcheck
  .venv/bin/python outbound_test.py +9198XXXXXXX [--text "Hi from ESCAPE!"]

What it does: checks call permission (requests it if missing and allowed),
places `connect` with an aiortc SDP offer, waits for the SDP answer webhook
(main.py stashes it in /tmp), plays one MMS line, sends `terminate`.

Before running: message the business number from the test phone once, so the
24h service window is open for a free-form permission request.
"""
import asyncio
import audioop
import json
import os
import sys
from fractions import Fraction

import outbound

LINE = "Hi! This is ESCAPE calling with a quick test. If you can hear this, our calls work. Goodbye!"


def synth_line(text: str) -> bytes:
    """MMS English 16kHz -> 48kHz mono (WebRTC clock)."""
    import mms_tts
    pcm16 = mms_tts.speak(text, "en")
    pcm48, _ = audioop.ratecv(pcm16, 2, 1, 16000, 48000, None)
    return pcm48


def wait_for_answer(call_id: str, timeout: int = 60) -> dict | None:
    import time
    path = outbound.answer_path(call_id)
    for _ in range(timeout):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        time.sleep(1)
    return None


async def main(to: str, text: str) -> int:
    perm = outbound.permission_status(to)
    status = (perm.get("permission") or {}).get("status", "")
    print("permission:", status or perm)
    if status not in ("temporary", "permanent"):
        ok, reason = outbound.limits_ok()
        if not ok:
            print("BLOCKED:", reason)
            return 2
        try:
            r = outbound.request_permission(
                to, "Hi, this is ESCAPE. May we call you about your order? Reply on the phone to allow.")
        except outbound.GraphError as e:
            print("permission request failed:", e)
            print("Message the business number from the test phone first (opens the 24h window), then rerun.")
            return 1
        print("request sent:", r)
        print("Approve the request on the phone, then rerun this command.")
        return 0
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from aiortc.mediastreams import MediaStreamTrack
    except ImportError:
        print("no aiortc on this machine; run this script on the VPS venv")
        return 1

    class LineTrack(MediaStreamTrack):
        kind = "audio"

        def __init__(self, pcm48: bytes):
            super().__init__()
            self._pcm = pcm48
            self._pos = 0
            self._ts = 0

        async def recv(self):
            from av import AudioFrame
            n = 960  # 20ms at 48kHz
            if pc.connectionState == "connected" and self._pos < len(self._pcm):
                chunk = self._pcm[self._pos:self._pos + n * 2]
                self._pos += n * 2
            else:
                chunk = b"\x00" * n * 2
            if len(chunk) < n * 2:
                chunk += b"\x00" * (n * 2 - len(chunk))
            frame = AudioFrame(format="s16", layout="mono", samples=n)
            frame.planes[0].update(chunk)
            frame.sample_rate = 48000
            frame.pts = self._ts
            frame.time_base = Fraction(1, 48000)
            self._ts += n
            await asyncio.sleep(0.02)
            return frame

    print("synthesising test line...")
    pcm48 = synth_line(text)
    pc = RTCPeerConnection()
    pc.addTrack(LineTrack(pcm48))
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    try:
        call_id = outbound.place_call(to, pc.localDescription.sdp)
    except outbound.GraphError as e:
        print("connect failed:", e)
        await pc.close()
        return 1
    print("call placed:", call_id, "- waiting for SDP answer webhook...")
    ans = await asyncio.get_event_loop().run_in_executor(None, wait_for_answer, call_id)
    if not ans:
        print("no SDP answer in 60s (webhook missing?). terminating.")
        try:
            outbound.terminate_call(call_id)
        except Exception as e:
            print("terminate also failed:", e)
        await pc.close()
        return 1
    await pc.setRemoteDescription(RTCSessionDescription(sdp=ans["sdp"], type=ans.get("sdp_type", "answer")))
    for _ in range(100):  # up to ~20s for ICE/DTLS
        if pc.connectionState in ("connected", "completed"):
            break
        await asyncio.sleep(0.2)
    print("connection:", pc.connectionState)
    play_s = len(pcm48) / 96000
    await asyncio.sleep(play_s + 2)
    try:
        outbound.terminate_call(call_id)
        print("terminated.")
    except Exception as e:
        print("terminate failed:", e)
    await pc.close()
    try:
        os.remove(outbound.answer_path(call_id))
    except OSError:
        pass
    print("done. OWNER: did the phone ring and play the line?")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        print("usage: python outbound_test.py +<countrycode><number> [--text ...]")
        sys.exit(0)
    to = sys.argv[1] if len(sys.argv) > 1 else ""
    if not to.startswith("+"):
        print('usage: python outbound_test.py +<countrycode><number> [--text "..."]')
        sys.exit(2)
    text = LINE
    if "--text" in sys.argv:
        text = sys.argv[sys.argv.index("--text") + 1]
    sys.exit(asyncio.run(main(to, text)))
