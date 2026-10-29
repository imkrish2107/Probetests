"""Live call wiring: WhatsApp client registry + per-call Pipecat pipeline.

Inbound call -> connection_callback -> pipeline (transport/STT/LLM/TTS) runs in a
background task until the caller hangs up -> transcript dump -> post_call.
shortcut: transcript persists at call end from LLM context, not per turn;
upgrade to per-turn save_turn once calls are green.
"""
import asyncio
import logging
import os
import time

import agent
import automation
import call_bot
import db

log = logging.getLogger("voice_call")
log.setLevel(logging.INFO)
if not log.handlers:  # uvicorn hides stdlib INFO by default; show our call lines
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s voice_call %(levelname)s %(message)s"))
    log.addHandler(_h)

_clients: dict = {}
_RUNNING: set = set()  # wa_call.id -> True; Meta retries connect webhooks
_session = None  # shared aiohttp session, set from lifespan

FIRST_LANG = {"English": "en", "Hindi": "hi", "Tamil": "ta", "Telugu": "te",
              "Kannada": "kn", "Bengali": "bn", "Marathi": "mr"}


def set_session(sess) -> None:
    global _session
    _session = sess


def voice_available() -> bool:
    return bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID"))


def get_client(phone_number_id: str):
    """One WhatsAppClient per business number; token/secret shared from env."""
    from pipecat.transports.whatsapp.client import WhatsAppClient
    if phone_number_id not in _clients:
        token = os.getenv("WHATSAPP_TOKEN", "")
        if not token:
            raise RuntimeError("WHATSAPP_TOKEN missing: cannot answer calls")
        if _session is None:
            import aiohttp
            set_session(aiohttp.ClientSession())
        _clients[phone_number_id] = WhatsAppClient(
            whatsapp_token=token,
            phone_number_id=phone_number_id,
            session=_session,
            whatsapp_secret=os.getenv("WHATSAPP_APP_SECRET", "") or None,
        )
    return _clients[phone_number_id]


async def handle_calls_entry(business: dict, entry: dict, raw: bytes, signature: str) -> bool:
    """Route one calls-field webhook entry through Pipecat. True if handled."""
    from pipecat.transports.whatsapp.api import WhatsAppWebhookRequest
    client = get_client(business["wa_phone_number_id"])

    async def on_call(connection, wa_call):
        await _run_voice_call(business, connection, wa_call)

    req = WhatsAppWebhookRequest.model_validate(
        {"object": "whatsapp_business_account", "entry": [entry]})
    return await client.handle_webhook_request(
        req, connection_callback=on_call, raw_body=raw, sha256_signature=signature)


async def warm_greetings() -> None:
    """Pre-synth every business greeting at startup (blocking work in executor)."""
    import json
    from voice_tts import warm as _warm
    with db.connect() as conn:
        rows = conn.execute("SELECT name, languages, greeting FROM businesses").fetchall()
    loop = asyncio.get_running_loop()
    for r in rows:
        try:
            langs = json.loads(r["languages"]) if isinstance(r["languages"], str) else r["languages"]
        except ValueError:
            langs = ["English"]
        first_lang = (langs or ["English"])[0]
        line = (r["greeting"] or "").strip() or call_bot.greeting(r["name"] or "", first_lang)
        try:
            await loop.run_in_executor(None, _warm, line, FIRST_LANG.get(first_lang, "hi"))
        except Exception as e:
            log.warning("greeting warm failed for %s: %s", r["name"], e)


def _voice_contact(business_id: int, wa_user_id: str, phone: str = "") -> int:
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM contacts WHERE business_id = ? AND wa_user_id = ?",
                           (business_id, wa_user_id)).fetchone()
        if row:
            conn.execute("UPDATE contacts SET last_inbound_at = ? WHERE id = ?", (now, row["id"]))
            conn.commit()
            return row["id"]
        cur = conn.execute("INSERT INTO contacts (business_id, wa_user_id, phone,"
                           " last_inbound_at, first_call_at) VALUES (?,?,?,?,?)",
                           (business_id, wa_user_id, phone, now, now))
        conn.commit()
        return cur.lastrowid


def _refresh_audio_track(transport, connection) -> str:
    """Re-point the transport at the live audio track after a mid-call swap.

    Meta renegotiates the caller audio track mid-call; Pipecat's reader keeps
    the stale wrapper forever (Timeout every 2s, caller unheard). Dropping the
    connection's cached wrapper makes the next read wrap the live receiver.
    All private access is guarded: worst case the refresh is a no-op.
    """
    try:
        get_track = getattr(connection, "audio_input_track", None)
        if get_track is None:
            return "no audio_input_track on connection"
        track_map = getattr(connection, "_track_map", None)
        if isinstance(track_map, dict):
            track_map.clear()
        fresh = get_track()
        if fresh is None:
            return "no live audio track"
        # The reader lives two levels down: transport -> client -> track slot.
        client = getattr(transport, "_client", None)
        if client is None or not hasattr(client, "_audio_input_track"):
            return "transport client has no audio slot"
        client._audio_input_track = fresh
        inner = getattr(fresh, "_track", None)
        detail = "{}/{}/{}".format(
            getattr(inner, "kind", "?"),
            str(getattr(inner, "id", "?"))[:8],
            getattr(inner, "readyState", "?"))
        return f"switched to live track ({detail})"
    except Exception as e:
        return f"refresh failed: {e}"


async def _run_voice_call(business: dict, connection, wa_call) -> None:
    """Full duplex loop for one answered call. Never raises into the webhook."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.worker import PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.frames.frames import LLMTextFrame, TranscriptionFrame
    from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from voice_stt import MuseSTTService
    from voice_tts import MMSTTSService
    from voice_tts import warm as _warm_greeting

    caller = getattr(wa_call, "from_", "") or ""
    wa_id = getattr(wa_call, "id", "") or caller
    if wa_id in _RUNNING:
        log.info("call %s already handled, skipping duplicate webhook", wa_id)
        return
    _RUNNING.add(wa_id)
    try:
        biz = agent._biz(business["id"])
        langs = biz.get("languages") or ["English"]
        first = FIRST_LANG.get(langs[0], "hi")
        cid = _voice_contact(business["id"], caller or f"call-{wa_call.id}")
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO calls (business_id, contact_id, direction, source,"
                " started_at) VALUES (?, ?, 'inbound', 'call', datetime('now'))",
                (business["id"], cid))
            conn.commit()
            call_id = cur.lastrowid
        with db.connect() as conn:
            name = conn.execute("SELECT name FROM contacts WHERE id = ?",
                                (cid,)).fetchone()[0] or caller
        call_bot.register_live(call_id, name, langs[0])
        greet_text = ((biz.get("greeting") or "").strip()
                      or call_bot.greeting(biz.get("name", ""), langs[0]))

        key = os.getenv("MODEL_API_KEY", "")
        stt_langs = [FIRST_LANG.get(l, "en") for l in langs]
        stt = MuseSTTService(api_key=key, languages=stt_langs, keywords=[biz.get("name", "")])
        llm = OpenAILLMService(
            api_key=key, base_url="https://api.meta.ai/v1",
            settings=OpenAILLMService.Settings(
                model=os.getenv("LLM_MODEL", "muse-spark-1.3"),
                # Spark over-thinks (300+ tokens for "hello"): cap it so speech
                # stays fast; the big room is burnable safety, per owner.
                max_completion_tokens=3000,
                extra={"extra_body": {"reasoning_effort": "minimal"}},
                system_instruction=agent.build_prompt(biz)))
        tts = MMSTTSService(lang=first)
        context = LLMContext()
        user_agg, asst_agg = LLMContextAggregatorPair(
            context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
        transport = SmallWebRTCTransport(
            webrtc_connection=connection,
            params=TransportParams(audio_in_enabled=True, audio_out_enabled=True))

        # Last-heard clock for the 10s silence rule. Caller speech is stamped
        # in the STT service (transcripts get buffered in the user aggregator
        # and never reach this timer); bot audio is stamped in the TTS service
        # (it sits downstream of this timer). Both reset the clock, so we only
        # hang up on true dead air, never mid-reply.
        voice_state = {"last_heard": time.monotonic(), "goodbye": False}

        class _LLMTimer(FrameProcessor):
            """Log brain time per reply: user-final -> first LLM token."""

            def __init__(self):
                super().__init__()
                self._t0 = None

            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, (TranscriptionFrame, UserStartedSpeakingFrame)):
                    voice_state["last_heard"] = time.monotonic()
                elif isinstance(frame, UserStoppedSpeakingFrame):
                    # Caller finished: this is the honest start of brain time.
                    self._t0 = time.monotonic()
                    voice_state["last_heard"] = self._t0
                elif isinstance(frame, LLMRunFrame):
                    self._t0 = None  # fresh run, fresh clock (stale _t0 lies)
                elif isinstance(frame, LLMTextFrame) and self._t0 is not None:
                    log.info("llm first token in %.2fs", time.monotonic() - self._t0)
                    self._t0 = None
                    voice_state["last_heard"] = time.monotonic()
                await self.push_frame(frame, direction)

        pipeline = Pipeline([transport.input(), stt, user_agg, llm, _LLMTimer(),
                             tts, transport.output(), asst_agg])
        worker = PipelineWorker(
            pipeline,
            # Dead air must never hang up on a caller; calls end on hangup/crash.
            cancel_on_idle_timeout=False,
            cancel_runner_on_idle_timeout=False,
        )
        runner = PipelineRunner()
        await runner.add_workers(worker)

        greeted = {"via": None}

        async def _greet(via: str):
            # on_client_connected may never fire: WhatsApp connects audio
            # before our transport attaches, so the watchdog covers that case.
            if greeted["via"] is None:
                greeted["via"] = via
                # Meta rejects a run with no user/tool message, so the greet
                # trigger rides on a caller "Hello"; the opening line itself is
                # fixed (custom greeting or the Meera default), pre-synthed.
                context.add_message({
                    "role": "user",
                    "content": f"Hello. Open with exactly this line and nothing else: {greet_text}",
                })
                await worker.queue_frames([LLMRunFrame()])
                log.info("call %s greeting via %s", call_id, via)

        @transport.event_handler("on_client_connected")
        async def _connected(transport, client):
            try:
                await _greet("event")
            except Exception as e:
                log.warning("call %s greet event failed: %s", call_id, e)

        @transport.event_handler("on_client_disconnected")
        async def _gone(transport, client):
            try:
                await runner.cancel()
            except Exception:
                pass

        try:  # caller audio track died = caller talking unheard; say so loudly
            @transport.event_handler("track-ended")
            async def _track_ended(transport, track):
                log.warning("call %s: caller %s track ended — caller unheard from here",
                            call_id, getattr(track, "kind", "audio"))
        except Exception:
            pass  # transport doesn't re-emit track events; audio watchdog covers it

        async def _greet_watchdog():
            await asyncio.sleep(3)
            try:
                await _greet("watchdog")
            except Exception as e:
                log.warning("call %s greet watchdog failed: %s", call_id, e)

        watchdog = asyncio.create_task(_greet_watchdog())

        async def _warm():
            await asyncio.get_running_loop().run_in_executor(
                None, _warm_greeting, greet_text, first)  # greeting audio ready early
        warm_task = asyncio.create_task(_warm())

        async def _silence_watchdog():
            # Goodbye ONLY when neither side has spoken for 10s. Bot audio and
            # caller speech both reset the clock. The first quiet stretch gets
            # a spoken nudge ("still there?"); only a second quiet stretch
            # after the nudge gets goodbye. Caller speech re-arms the nudge.
            try:
                while True:
                    await asyncio.sleep(1)
                    if voice_state["goodbye"]:
                        return
                    if stt.last_voice_at > voice_state.get("nudge_at", 0):
                        voice_state["nudged"] = False
                    now = time.monotonic()
                    if (now - stt.last_audio_chunk_at > 8
                            and now - voice_state.get("audio_warned_at", 0) > 10):
                        voice_state["audio_warned_at"] = now
                        log.warning("call %s: no inbound caller audio for %.0fs —"
                                    " caller may be talking unheard",
                                    call_id, now - stt.last_audio_chunk_at)
                    if (now - stt.last_audio_chunk_at > 8
                            and now - voice_state.get("track_refreshed_at", 0) > 10):
                        # Dead voice pipe on a live call = stale track after a
                        # mid-call swap (or one still arriving). Re-point the
                        # reader; retry while dead in case the live track lands late.
                        voice_state["track_refreshed_at"] = now
                        log.warning("call %s: refreshing audio track: %s",
                                    call_id, _refresh_audio_track(transport, connection))
                    quiet = now - max(voice_state["last_heard"],
                                      stt.last_voice_at, tts.last_audio_at)
                    if quiet < 10.0:
                        continue
                    if voice_state.get("nudged"):
                        nudge_at = voice_state.get("nudge_at", 0)
                        if tts.last_audio_at <= nudge_at and now - nudge_at < 20:
                            continue  # nudge still generating/speaking; don't pile on
                    else:
                        voice_state["nudged"] = True
                        voice_state["nudge_at"] = now
                        log.info("call %s: %.0fs silence, nudging", call_id, quiet)
                        try:
                            context.add_message({
                                "role": "user",
                                "content": "The caller has gone quiet. Say one very short"
                                           " check-in like 'Are you still there?' in the call"
                                           " language and nothing else.",
                            })
                            await worker.queue_frames([LLMRunFrame()])
                        except Exception as e:
                            log.warning("call %s nudge failed: %s", call_id, e)
                        continue
                    voice_state["goodbye"] = True
                    log.info("call %s: %.0fs silence, saying goodbye", call_id, quiet)
                    try:
                        context.add_message({
                            "role": "user",
                            "content": "The caller has gone quiet. Say one short goodbye"
                                       " sentence in the call language and nothing else.",
                        })
                        await worker.queue_frames([LLMRunFrame()])
                        await asyncio.sleep(8)  # let the goodbye play
                    except Exception as e:
                        log.warning("call %s goodbye failed: %s", call_id, e)
                    if stt.last_voice_at > now:
                        # Caller spoke during the goodbye: stay on the call.
                        voice_state["goodbye"] = False
                        log.info("call %s: caller came back, staying", call_id)
                        continue
                    for step in ("disconnect", "cancel"):
                        try:
                            if step == "disconnect":
                                await connection.disconnect()
                            else:
                                await runner.cancel()
                        except Exception:
                            pass
                    return
            except asyncio.CancelledError:
                pass
        silence_task = asyncio.create_task(_silence_watchdog())

        try:
            await runner.run()
        except (asyncio.CancelledError, Exception):
            log.exception("call %s pipeline ended", call_id)
        watchdog.cancel()
        warm_task.cancel()
        silence_task.cancel()
        _RUNNING.discard(wa_id)
        _finish_call(business["id"], call_id, context)
    except Exception as e:
        _RUNNING.discard(wa_id)
        log.warning("voice call failed: %s", e)


def _finish_call(business_id: int, call_id: int, context) -> None:
    """Dump context turns to transcripts, then run the normal post-call chain."""
    try:
        msgs = context.get_messages()
    except Exception as e:
        log.warning("context dump failed: %s", e)
        msgs = []
    empties = sum(1 for m in msgs
                  if m.get("role") == "assistant" and not (m.get("content") or "").strip())
    if empties:
        log.warning("call %s: %d empty assistant turn(s), thinking likely blew the budget",
                    call_id, empties)
    turns = [(m.get("role", ""), (m.get("content") or "").strip()) for m in msgs]
    with db.connect() as conn:
        for role, text in turns:
            if role in ("user", "assistant") and text:
                conn.execute("INSERT INTO transcripts (call_id, role, text, at)"
                             " VALUES (?, ?, ?, datetime('now'))",
                             (call_id, "caller" if role == "user" else "bot", text))
        conn.execute("UPDATE calls SET duration_s = (strftime('%s','now') -"
                     " strftime('%s',started_at)) WHERE id = ?", (call_id,))
        conn.commit()
    call_bot.unregister_live(call_id)
    try:
        automation.post_call(call_id)
    except Exception as e:
        log.warning("post_call failed: %s", e)
