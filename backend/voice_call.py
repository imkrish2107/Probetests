"""Live call wiring: WhatsApp client registry + per-call Pipecat pipeline.

Inbound call -> connection_callback -> pipeline (transport/STT/LLM/TTS) runs in a
background task until the caller hangs up -> transcript dump -> post_call.
shortcut: transcript persists at call end from LLM context, not per turn;
upgrade to per-turn save_turn once calls are green.
"""
import asyncio
import logging
import os

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
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from voice_stt import MuseSTTService
    from voice_tts import MMSTTSService

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
        pipeline = Pipeline([transport.input(), stt, user_agg, llm, tts,
                             transport.output(), asst_agg])
        worker = PipelineWorker(pipeline)
        runner = PipelineRunner()
        await runner.add_workers(worker)

        greeted = {"via": None}

        async def _greet(via: str):
            # on_client_connected may never fire: WhatsApp connects audio
            # before our transport attaches, so the watchdog covers that case.
            if greeted["via"] is None:
                greeted["via"] = via
                # Meta rejects a run with no user/tool message, so the greet
                # trigger is a plain "Hello" from the caller side.
                context.add_message({"role": "user", "content": "Hello"})
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

        async def _greet_watchdog():
            await asyncio.sleep(3)
            try:
                await _greet("watchdog")
            except Exception as e:
                log.warning("call %s greet watchdog failed: %s", call_id, e)

        watchdog = asyncio.create_task(_greet_watchdog())

        try:
            await runner.run()
        except (asyncio.CancelledError, Exception) as e:
            log.info("call %s pipeline ended: %s", call_id, e)
        watchdog.cancel()
        _RUNNING.discard(wa_id)
        _finish_call(business["id"], call_id, context)
    except Exception as e:
        _RUNNING.discard(wa_id)
        log.warning("voice call failed: %s", e)


def _finish_call(business_id: int, call_id: int, context) -> None:
    """Dump context turns to transcripts, then run the normal post-call chain."""
    try:
        turns = [(m.get("role", ""), (m.get("content") or "").strip())
                 for m in context.get_messages()]
    except Exception as e:
        log.warning("context dump failed: %s", e)
        turns = []
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
