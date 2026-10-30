"""FastAPI backend: webhook, auth, business, dashboard data, buttons, scheduler."""
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import auth
import automation
import call_bot
import db
import httpx
from argon2.exceptions import HashingError
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from whatsapp import iter_value_items, verify_signature

load_dotenv()
log = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()

    async def loop():
        while True:
            await asyncio.sleep(300)
            try:
                automation.scheduler_tick()
            except Exception as e:
                log.warning("scheduler tick failed: %s", e)

    task = asyncio.create_task(loop())
    try:  # shared HTTP session for the voice client; voice stays off without it
        import aiohttp
        import voice_call
        app.state.wa_session = aiohttp.ClientSession()
        voice_call.set_session(app.state.wa_session)
    except ImportError:
        app.state.wa_session = None
    try:  # warm every MMS voice any business may need, so replies never wait on load
        import mms_tts
        import voice_call
        tags = set()
        with db.connect() as conn:
            rows = conn.execute("SELECT languages FROM businesses").fetchall()
        for r in rows:
            try:
                langs = json.loads(r["languages"]) if isinstance(r["languages"], str) else r["languages"]
            except ValueError:
                langs = ["English"]
            for l in langs or ["English"]:
                t = voice_call.FIRST_LANG.get(l, "")
                if t and t in mms_tts.VOICES:
                    tags.add(t)
        loop = asyncio.get_running_loop()
        for t in sorted(tags):
            await loop.run_in_executor(None, mms_tts.get_voice, t)
    except Exception as e:
        log.warning("tts preload failed: %s", e)
    try:  # pre-synth greetings so calls open instantly, no first-line stutter
        import voice_call
        await voice_call.warm_greetings()
    except Exception as e:
        log.warning("greeting warm failed: %s", e)
    yield
    task.cancel()
    if getattr(app.state, "wa_session", None):
        await app.state.wa_session.close()


app = FastAPI(lifespan=lifespan)

_templates_cache: dict = {"at": 0.0, "items": []}


def api_error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def require_api_key(request: Request):
    expected = os.getenv("BACKEND_API_KEY", "")
    if expected and request.headers.get("x-api-key") != expected:
        return api_error("unauthorized", "bad api key", 401)
    return None


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    return None


def current_user(request: Request) -> dict | None:
    token = bearer_token(request.headers.get("authorization"))
    return auth.user_from_token(token) if token else None


def need_login(request: Request):
    u = current_user(request)
    if not u:
        return None, api_error("unauthorized", "not logged in", 401)
    return u, None


def mask_phone(phone: str) -> str:
    if not phone:
        return ""
    if len(phone) >= 9:
        return phone[:5] + "xxxxx" + phone[-3:]
    return "****"


def page_params(before: str | None, limit: int) -> tuple[int | None, int]:
    try:
        b = int(before) if before else None
    except ValueError:
        b = None
    return b, max(1, min(limit, 100))


def paginate(rows: list[dict], limit: int) -> dict:
    extra = len(rows) > limit
    items = rows[:limit]
    return {"items": items, "next_before": items[-1]["id"] if extra else None}


def stub_send(kind: str, business_id: int, contact_id: int, body: str = "",
              call_id: int | None = None, booking_id: int | None = None,
              task_id: int | None = None, template: str = "") -> int:
    """Log a send instead of hitting WhatsApp; real send lands with keys."""
    log.info("stub send %s to contact %s: %.200s", kind, contact_id, body or template)
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO messages
               (business_id, contact_id, call_id, booking_id, task_id, kind, template, body, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')""",
            (business_id, contact_id, call_id, booking_id, task_id, kind, template, body),
        )
        conn.commit()
        return cur.lastrowid


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/webhook")
def verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WHATSAPP_VERIFY_TOKEN", ""):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="forbidden", status_code=403)


async def _maybe_voice_call(event: dict, raw: bytes, sig: str) -> bool:
    """Hand calls-field entries to the voice pipeline. False = not handled."""
    handled = False
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "calls":
                continue
            value = change.get("value") or {}
            pnid = (value.get("metadata") or {}).get("phone_number_id", "")
            with db.connect() as conn:
                row = conn.execute("SELECT * FROM businesses WHERE wa_phone_number_id = ?",
                                   (pnid,)).fetchone()
            if not row:
                log.info("webhook: unknown phone_number_id %s, ignored", pnid)
                continue
            try:
                import voice_call
            except ImportError as e:
                log.warning("voice unavailable: %s", e)
                return False
            try:
                if await voice_call.handle_calls_entry(dict(row), entry, raw, sig):
                    handled = True
            except Exception as e:
                log.warning("voice call failed: %s", e)
    return handled


@app.post("/webhook")
async def receive(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-hub-signature-256", "")
    if not verify_signature(raw, sig, os.getenv("WHATSAPP_APP_SECRET", "")):
        return Response(content="bad signature", status_code=403)
    try:
        event = json.loads(raw)
    except ValueError:
        log.info("webhook non-JSON event: %.200s", raw.decode("utf-8", "replace"))
        return Response(content="ok")
    voice_done = await _maybe_voice_call(event, raw, sig)
    for pnid, kind, item in iter_value_items(event):
        with db.connect() as conn:
            biz = conn.execute("SELECT id FROM businesses WHERE wa_phone_number_id = ?",
                               (pnid,)).fetchone()
        if not biz:
            log.info("webhook: unknown phone_number_id %s, ignored", pnid)
            continue
        try:
            if kind == "status":
                _apply_status(biz["id"], item)
            elif kind == "message":
                _handle_inbound(biz["id"], item)
            else:
                if kind != "call" or not voice_done:
                    log.info("webhook call event: %s", json.dumps(item)[:300])
        except Exception as e:
            log.warning("webhook handler failed: %s", e)
    return Response(content="ok")  # 200 at once; work happens in background


def _apply_status(business_id: int, item: dict) -> None:
    wid, status = item.get("id"), item.get("status")
    if not wid or not status:
        return
    with db.connect() as conn:
        conn.execute("UPDATE messages SET status = ? WHERE wa_message_id = ? AND business_id = ?",
                     (status, wid, business_id))
        conn.commit()


def _ensure_contact(business_id: int, wa_user_id: str, phone: str) -> int:
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


def _handle_inbound(business_id: int, item: dict) -> None:
    """One Call Now auto-reply per contact per day (queued until real sends land)."""
    wa_id = item.get("from", "")
    if not wa_id:
        return
    cid = _ensure_contact(business_id, wa_id, "")
    import datetime as dt
    day_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    with db.connect() as conn:
        row = conn.execute("SELECT auto_reply_at FROM contacts WHERE id = ?", (cid,)).fetchone()
    if row and row["auto_reply_at"] and row["auto_reply_at"] > day_ago:
        return
    stub_send("auto_reply", business_id, cid, template="call_us")
    with db.connect() as conn:
        conn.execute("UPDATE contacts SET auto_reply_at = datetime('now') WHERE id = ?", (cid,))
        conn.commit()


@app.post("/api/auth/signup", status_code=201)
async def signup(request: Request):
    if denied := require_api_key(request):
        return denied
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    business_name = (body.get("business_name") or "").strip()
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    need_code = os.getenv("SIGNUP_CODE", "")
    if need_code and body.get("signup_code") != need_code:
        return api_error("unauthorized", "bad signup code", 401)
    if not business_name or not name or not email or len(password) < 8:
        return api_error("invalid", "business_name, name, email and 8+ char password required", 422)
    if not auth.check_rate_limit(email):
        return api_error("rate_limited", "too many tries", 429)
    with db.connect() as conn:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return api_error("exists", "email already registered", 409)
    try:
        pw_hash = auth.hash_password(password)
    except HashingError:
        return api_error("invalid", "password hashing failed", 500)
    slug = auth.slugify(business_name)
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO businesses (slug, name) VALUES (?, ?)", (slug, business_name)
        )
        business_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO users (business_id, name, email, password_hash, role)"
            " VALUES (?, ?, ?, ?, 'owner')",
            (business_id, name, email, pw_hash),
        )
        user_id = cur.lastrowid
        conn.commit()
    token = auth.new_session(user_id)
    user = {"id": user_id, "name": name, "email": email, "role": "owner"}
    return {"token": token, "user": user, "business": {"id": business_id, "name": business_name, "slug": slug}}


@app.post("/api/auth/login")
async def login(request: Request):
    if denied := require_api_key(request):
        return denied
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not auth.check_rate_limit(email):
        return api_error("rate_limited", "too many tries", 429)
    with db.connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.business_id, u.name, u.email, u.password_hash, u.role,
                      b.name AS business_name, b.slug AS business_slug
               FROM users u JOIN businesses b ON b.id = u.business_id WHERE u.email = ?""",
            (email,),
        ).fetchone()
    if not row or not auth.verify_password(row["password_hash"], password):
        return api_error("unauthorized", "wrong email or password", 401)
    with db.connect() as conn:
        conn.execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (row["id"],))
        conn.commit()
    token = auth.new_session(row["id"])
    user = {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}
    business = {"id": row["business_id"], "name": row["business_name"], "slug": row["business_slug"]}
    return {"token": token, "user": user, "business": business}


@app.post("/api/auth/logout", status_code=204)
async def logout(request: Request, authorization: str | None = Header(default=None)):
    if denied := require_api_key(request):
        return denied
    token = bearer_token(authorization)
    if not token or not auth.user_from_token(token):
        return api_error("unauthorized", "not logged in", 401)
    auth.delete_session(token)
    return Response(status_code=204)


@app.get("/api/auth/me")
async def me(request: Request, authorization: str | None = Header(default=None)):
    if denied := require_api_key(request):
        return denied
    token = bearer_token(authorization)
    u = auth.user_from_token(token) if token else None
    if not u:
        return api_error("unauthorized", "not logged in", 401)
    return {
        "user": {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]},
        "business": {"id": u["business_id"], "name": u["business_name"], "slug": u["business_slug"]},
    }


BUSINESS_FIELDS = ["name", "wa_phone_number_id", "wa_display_number", "timezone",
                   "hours", "slot_minutes", "seats_per_slot", "menu", "prices",
                   "faqs", "languages", "greeting", "owner_whatsapp", "crm_webhook_url"]
JSON_FIELDS = {"hours", "menu", "faqs", "languages"}

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
BIZ_LANGS = {"English", "Hindi", "Tamil", "Telugu", "Kannada", "Bengali", "Marathi"}


def validate_business(updates: dict):
    """422 naming the field on a bad shape; None when fine."""
    if "timezone" in updates:
        try:
            ZoneInfo(updates["timezone"])
        except Exception:
            return api_error("invalid", "timezone: unknown IANA name", 422)
    if "hours" in updates:
        h = updates["hours"]
        if not isinstance(h, dict) or any(k not in DAY_KEYS for k in h):
            return api_error("invalid", "hours: keys must be mon..sun", 422)
        for day, spans in h.items():
            if not isinstance(spans, list):
                return api_error("invalid", f"hours: {day} must be a list", 422)
            last = ""
            for span in spans:
                if (not isinstance(span, list) or len(span) != 2
                        or span[0] >= span[1] or span[0] < last):
                    return api_error("invalid", f"hours: {day} overlapping or bad span", 422)
                last = span[1]
    if "languages" in updates:
        langs = updates["languages"]
        if not isinstance(langs, list) or not langs or any(l not in BIZ_LANGS for l in langs):
            return api_error("invalid", "languages: unknown language", 422)
    if "menu" in updates:
        if not isinstance(updates["menu"], list) or any(
                not isinstance(m, dict) or not m.get("name") for m in updates["menu"]):
            return api_error("invalid", "menu: items need a name", 422)
    if "faqs" in updates:
        if not isinstance(updates["faqs"], list) or any(
                not isinstance(f, dict) or "q" not in f or "a" not in f
                for f in updates["faqs"]):
            return api_error("invalid", "faqs: items need q and a", 422)
    if "greeting" in updates:
        g = updates["greeting"]
        if not isinstance(g, str) or not g.strip() or len(g) > 300:
            return api_error("invalid", "greeting: 1-300 chars of text", 422)
    for f in ("slot_minutes", "seats_per_slot"):
        if f in updates and (not isinstance(updates[f], int) or isinstance(updates[f], bool)
                             or updates[f] <= 0):
            return api_error("invalid", f"{f}: must be a positive integer", 422)
    return None


def business_to_json(row) -> dict:
    d = dict(row)
    for f in JSON_FIELDS:  # TEXT columns -> parsed JSON for the dashboard
        try:
            d[f] = json.loads(d[f]) if isinstance(d[f], str) else d[f]
        except (ValueError, TypeError):
            pass
    num = d.get("wa_display_number") or ""
    d["call_link"] = f"https://wa.me/call/{num}" if num else ""
    return d


@app.get("/api/business")
async def get_business(request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM businesses WHERE id = ?", (u["business_id"],)).fetchone()
    if not row:
        return api_error("not_found", "no business", 404)
    return business_to_json(row)


@app.put("/api/business")
async def put_business(request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    if u["role"] != "owner":
        return api_error("forbidden", "owner only", 403)
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    updates = {f: body[f] for f in BUSINESS_FIELDS if f in body}
    if err := validate_business(updates):
        return err
    for f in JSON_FIELDS & updates.keys():  # must be objects/lists, stored as TEXT
        if not isinstance(updates[f], (dict, list)):
            return api_error("invalid", f"{f} must be an object or list", 422)
        updates[f] = json.dumps(updates[f])
    if not updates:
        return api_error("invalid", "nothing to update", 422)
    sets = ", ".join(f"{k} = ?" for k in updates) + ", updated_at = datetime('now')"
    with db.connect() as conn:
        conn.execute(
            f"UPDATE businesses SET {sets} WHERE id = ?", (*updates.values(), u["business_id"])
        )
        conn.commit()
        row = conn.execute("SELECT * FROM businesses WHERE id = ?", (u["business_id"],)).fetchone()
    return business_to_json(row)


@app.get("/api/stats")
async def stats(request: Request, date: str | None = None):
    """Totals for a day in the business's timezone."""
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    import datetime as dt
    with db.connect() as conn:
        tzname = conn.execute("SELECT timezone FROM businesses WHERE id = ?",
                              (u["business_id"],)).fetchone()[0] or "Asia/Kolkata"
    try:
        day = date or dt.datetime.now(ZoneInfo(tzname)).date().isoformat()
    except Exception:
        day = date or dt.datetime.now(dt.timezone.utc).date().isoformat()
    with db.connect() as conn:
        calls = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM calls"
            " WHERE business_id = ? AND started_at LIKE ?",
            (u["business_id"], day + "%"),
        ).fetchone()
        bookings = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE business_id = ? AND slot LIKE ?"
            " AND status != 'cancelled'",
            (u["business_id"], day + "%"),
        ).fetchone()
        open_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE business_id = ? AND status = 'open'",
            (u["business_id"],),
        ).fetchone()
        urgent = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE business_id = ? AND status = 'open'"
            " AND urgency = 'urgent'",
            (u["business_id"],),
        ).fetchone()
    return {"calls": calls[0], "bookings": bookings[0], "open_tasks": open_tasks[0],
            "urgent_tasks": urgent[0], "cost_usd": calls[1]}


@app.get("/api/calls")
async def list_calls(request: Request, before: str | None = None, limit: int = 50):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    b, limit = page_params(before, limit)
    q = """SELECT c.id, c.direction, c.source, c.language, c.started_at, c.duration_s,
                  c.outcome, c.cost_usd, ct.id AS cid, ct.name, ct.phone
           FROM calls c LEFT JOIN contacts ct ON ct.id = c.contact_id
           WHERE c.business_id = ?"""
    args: list = [u["business_id"]]
    if b:
        q += " AND c.id < ?"
        args.append(b)
    q += " ORDER BY c.id DESC LIMIT ?"
    args.append(limit + 1)
    with db.connect() as conn:
        rows = conn.execute(q, args).fetchall()
    items = [{
        "id": r["id"], "direction": r["direction"], "source": r["source"],
        "language": r["language"], "started_at": r["started_at"],
        "duration_s": r["duration_s"], "outcome": r["outcome"], "cost_usd": r["cost_usd"],
        "contact": {"id": r["cid"], "name": r["name"] or "", "phone_masked": mask_phone(r["phone"] or "")},
    } for r in rows]
    return paginate(items, limit)


@app.get("/api/calls/{call_id}")
async def call_detail(call_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    with db.connect() as conn:
        call = conn.execute(
            "SELECT * FROM calls WHERE id = ? AND business_id = ?", (call_id, u["business_id"])
        ).fetchone()
        if not call:
            return api_error("not_found", "no call", 404)
        d = dict(call)
        try:
            d["crm_changes"] = json.loads(d["crm_changes"]) if d["crm_changes"] else {}
        except ValueError:
            d["crm_changes"] = {}
        d["transcript"] = [dict(r) for r in conn.execute(
            "SELECT role, text, language, at FROM transcripts WHERE call_id = ? ORDER BY id", (call_id,))]
        d["bookings"] = [dict(r) for r in conn.execute(
            "SELECT * FROM bookings WHERE call_id = ?", (call_id,))]
        d["tasks"] = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE call_id = ?", (call_id,))]
        d["messages"] = [dict(r) for r in conn.execute(
            "SELECT * FROM messages WHERE call_id = ?", (call_id,))]
    return d


@app.get("/api/bookings")
async def list_bookings(request: Request, date: str | None = None):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    import datetime as dt
    with db.connect() as conn:
        tzname = conn.execute("SELECT timezone FROM businesses WHERE id = ?",
                              (u["business_id"],)).fetchone()[0] or "Asia/Kolkata"
    try:
        day = date or dt.datetime.now(ZoneInfo(tzname)).date().isoformat()
    except Exception:
        day = date or dt.datetime.now(dt.timezone.utc).date().isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT id, contact_id, name, party_size, slot, note, status, reminder_sent_at
               FROM bookings WHERE business_id = ? AND slot LIKE ? ORDER BY slot""",
            (u["business_id"], day + "%"),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.patch("/api/bookings/{booking_id}")
async def patch_booking(booking_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ? AND business_id = ?", (booking_id, u["business_id"])
        ).fetchone()
        if not row:
            return api_error("not_found", "no booking", 404)
        if "slot" in body:  # normalize naive datetimes into the business timezone
            import datetime as dt
            tzname = conn.execute("SELECT timezone FROM businesses WHERE id = ?",
                                  (u["business_id"],)).fetchone()[0] or "Asia/Kolkata"
            try:
                slot_dt = dt.datetime.fromisoformat(body["slot"])
            except ValueError:
                return api_error("invalid", "slot: bad ISO datetime", 422)
            if slot_dt.tzinfo is None:
                try:
                    slot_dt = slot_dt.replace(tzinfo=ZoneInfo(tzname))
                except Exception:
                    return api_error("invalid", "timezone: unknown IANA name", 422)
            body["slot"] = slot_dt.isoformat()
            conn.execute(
                "UPDATE bookings SET slot = ?, status = 'changed', updated_at = datetime('now')"
                " WHERE id = ?", (body["slot"], booking_id))
        elif body.get("status") == "cancelled":
            conn.execute(
                "UPDATE bookings SET status = 'cancelled', updated_at = datetime('now')"
                " WHERE id = ?", (booking_id,))
        else:
            return api_error("invalid", "send {slot} or {status: 'cancelled'}", 422)
        conn.commit()
        updated = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    stub_send("booking_changed", u["business_id"], row["contact_id"],
              body=f"booking {booking_id} updated", booking_id=booking_id)
    return dict(updated)


@app.get("/api/tasks")
async def list_tasks(request: Request, status: str = "open",
                     before: str | None = None, limit: int = 50):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    if status not in ("open", "done"):
        return api_error("invalid", "status must be open or done", 422)
    b, limit = page_params(before, limit)
    q = """SELECT t.id, t.type, t.details, t.urgency, t.status, t.call_id, t.created_at,
                  c.id AS cid, c.name AS cname
           FROM tasks t LEFT JOIN contacts c ON c.id = t.contact_id
           WHERE t.business_id = ? AND t.status = ?"""
    args: list = [u["business_id"], status]
    if b:
        q += " AND t.id < ?"
        args.append(b)
    # urgent first, then newest
    q += " ORDER BY CASE t.urgency WHEN 'urgent' THEN 0 ELSE 1 END, t.id DESC LIMIT ?"
    args.append(limit + 1)
    with db.connect() as conn:
        rows = conn.execute(q, args).fetchall()
    items = [{
        "id": r["id"], "type": r["type"], "details": r["details"], "urgency": r["urgency"],
        "status": r["status"], "call_id": r["call_id"], "created_at": r["created_at"],
        "contact": {"id": r["cid"], "name": r["cname"] or ""},
    } for r in rows]
    return paginate(items, limit)


@app.patch("/api/tasks/{task_id}")
async def patch_task(task_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    if body.get("status") != "done":
        return api_error("invalid", "send {status: 'done', note}", 422)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND business_id = ?", (task_id, u["business_id"])
        ).fetchone()
        if not row:
            return api_error("not_found", "no task", 404)
        conn.execute(
            "UPDATE tasks SET status = 'done', done_note = ?, done_by = ?, done_at = datetime('now')"
            " WHERE id = ?", (body.get("note", ""), u["id"], task_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    stub_send("task_done", u["business_id"], row["contact_id"],
              body=body.get("note", ""), task_id=task_id)
    return dict(updated)


@app.get("/api/contacts")
async def list_contacts(request: Request, q: str = "",
                        before: str | None = None, limit: int = 50):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    b, limit = page_params(before, limit)
    sql = """SELECT id, name, phone, language, stage, tags, last_call_at, calls_count
             FROM contacts WHERE business_id = ?"""
    args: list = [u["business_id"]]
    if q:
        sql += " AND (name LIKE ? OR phone LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if b:
        sql += " AND id < ?"
        args.append(b)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit + 1)
    with db.connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    items = []
    for r in rows:
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
        except ValueError:
            tags = []
        items.append({"id": r["id"], "name": r["name"], "phone_masked": mask_phone(r["phone"] or ""),
                      "language": r["language"], "stage": r["stage"], "tags": tags,
                      "last_call_at": r["last_call_at"], "calls_count": r["calls_count"]})
    return paginate(items, limit)


@app.get("/api/contacts/{contact_id}")
async def contact_detail(contact_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    with db.connect() as conn:
        c = conn.execute(
            "SELECT * FROM contacts WHERE id = ? AND business_id = ?", (contact_id, u["business_id"])
        ).fetchone()
        if not c:
            return api_error("not_found", "no contact", 404)
        d = dict(c)
        try:
            d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        except ValueError:
            d["tags"] = []
        d["calls"] = [dict(r) for r in conn.execute(
            "SELECT * FROM calls WHERE contact_id = ? ORDER BY id DESC", (contact_id,))]
        d["bookings"] = [dict(r) for r in conn.execute(
            "SELECT * FROM bookings WHERE contact_id = ? ORDER BY id DESC", (contact_id,))]
        d["tasks"] = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE contact_id = ? ORDER BY id DESC", (contact_id,))]
        d["messages"] = [dict(r) for r in conn.execute(
            "SELECT * FROM messages WHERE contact_id = ? ORDER BY id DESC", (contact_id,))]
    return d


@app.patch("/api/contacts/{contact_id}")
async def patch_contact(contact_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    allowed = {"name", "stage", "tags", "notes"}
    updates = {k: body[k] for k in allowed if k in body}
    if "stage" in updates and updates["stage"] not in ("new", "lead", "booked", "customer"):
        return api_error("invalid", "bad stage", 422)
    if "tags" in updates:
        if not isinstance(updates["tags"], list):
            return api_error("invalid", "tags must be a list", 422)
        updates["tags"] = json.dumps(updates["tags"])
    if not updates:
        return api_error("invalid", "nothing to update", 422)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM contacts WHERE id = ? AND business_id = ?", (contact_id, u["business_id"])
        ).fetchone()
        if not row:
            return api_error("not_found", "no contact", 404)
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE contacts SET {sets} WHERE id = ?", (*updates.values(), contact_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    out = dict(updated)
    try:
        out["tags"] = json.loads(out["tags"]) if out["tags"] else []
    except ValueError:
        out["tags"] = []
    return out


@app.post("/api/contacts/{contact_id}/call-button")
async def call_button(contact_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, last_inbound_at FROM contacts WHERE id = ? AND business_id = ?",
            (contact_id, u["business_id"]),
        ).fetchone()
    if not row:
        return api_error("not_found", "no contact", 404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    import datetime as dt
    kind, template = "template", "call_us"  # outside the 24h window: template
    if row["last_inbound_at"]:
        try:
            last = dt.datetime.fromisoformat(row["last_inbound_at"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=dt.timezone.utc)
            if (dt.datetime.now(dt.timezone.utc) - last).total_seconds() < 24 * 3600:
                kind, template = "interactive", ""  # inside window: voice_call button
        except ValueError:
            pass
    mid = stub_send("call_button", u["business_id"], contact_id,
                    body=body.get("message", ""), template=template)
    return {"message_id": mid, "kind": kind}


@app.post("/api/contacts/{contact_id}/callback", status_code=202)
async def callback(contact_id: int, request: Request):
    """Stretch: AI calls the customer. Real connect lands with WhatsApp keys."""
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ? AND business_id = ?",
            (contact_id, u["business_id"]),
        ).fetchone()
    if not row:
        return api_error("not_found", "no contact", 404)
    if not row["call_permission"]:
        return api_error("no_permission", "customer never allowed calls", 409)
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO calls (business_id, contact_id, direction) VALUES (?, ?, 'outbound')",
            (u["business_id"], contact_id),
        )
        conn.commit()
        return JSONResponse({"call_id": cur.lastrowid}, status_code=202)


@app.get("/api/live")
async def live(request: Request):
    """Calls in progress, from the call-bot registry (empty when no live calls)."""
    if denied := require_api_key(request):
        return denied
    _, err = need_login(request)
    if err:
        return err
    return {"items": getattr(call_bot, "live_calls", lambda: [])()}


@app.get("/api/public/businesses/{slug}")
async def public_business(slug: str, request: Request):
    if denied := require_api_key(request):
        return denied
    with db.connect() as conn:
        row = conn.execute(
            "SELECT name, hours, wa_display_number FROM businesses WHERE slug = ?", (slug,)
        ).fetchone()
    if not row:
        return api_error("not_found", "no business", 404)
    num = row["wa_display_number"] or ""
    return {"name": row["name"], "call_link": f"https://wa.me/call/{num}" if num else "",
            "hours": json.loads(row["hours"]) if row["hours"] else {}}


@app.get("/api/templates")
async def templates(request: Request):
    """Template approval status from Meta, cached 5 min. Empty without a token."""
    if denied := require_api_key(request):
        return denied
    _, err = need_login(request)
    if err:
        return err
    if time.time() - _templates_cache["at"] < 300 and _templates_cache["items"]:
        return {"items": _templates_cache["items"]}
    token, waba = os.getenv("WHATSAPP_TOKEN", ""), os.getenv("WHATSAPP_WABA_ID", "")
    if not token or not waba:
        return {"items": []}
    try:
        # shortcut: Graph version unpinned; pin when templates go live
        r = httpx.get(f"https://graph.facebook.com/v21.0/{waba}/message_templates",
                      params={"fields": "name,language,status",
                              "access_token": token}, timeout=15)
        r.raise_for_status()
        items = [{"name": t["name"], "language": t.get("language"),
                  "status": t.get("status")} for t in r.json().get("data", [])]
        _templates_cache.update(at=time.time(), items=items)
        return {"items": items}
    except Exception as e:
        log.warning("templates fetch failed: %s", e)
        return {"items": _templates_cache["items"]}


@app.get("/api/users")
async def list_users(request: Request):
    """Stretch: team. Owner only."""
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    if u["role"] != "owner":
        return api_error("forbidden", "owner only", 403)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, name, email, role, last_login_at FROM users WHERE business_id = ?",
            (u["business_id"],)).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.post("/api/users", status_code=201)
async def create_user(request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    if u["role"] != "owner":
        return api_error("forbidden", "owner only", 403)
    try:
        body = await request.json()
    except Exception:
        return api_error("invalid", "bad json", 422)
    name, email, password = (body.get("name") or "").strip(), \
        (body.get("email") or "").strip().lower(), body.get("password") or ""
    if not name or not email or len(password) < 8:
        return api_error("invalid", "name, email and 8+ char password required", 422)
    with db.connect() as conn:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return api_error("exists", "email already registered", 409)
        cur = conn.execute(
            "INSERT INTO users (business_id, name, email, password_hash, role)"
            " VALUES (?, ?, ?, ?, 'staff')",
            (u["business_id"], name, email, auth.hash_password(password)))
        conn.commit()
    return JSONResponse({"id": cur.lastrowid, "name": name, "email": email, "role": "staff"},
                        status_code=201)


@app.delete("/api/users/{user_id}", status_code=204)
async def delete_user(user_id: int, request: Request):
    if denied := require_api_key(request):
        return denied
    u, err = need_login(request)
    if err:
        return err
    if u["role"] != "owner":
        return api_error("forbidden", "owner only", 403)
    if user_id == u["id"]:
        return api_error("invalid", "can't delete yourself", 422)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ? AND business_id = ?", (user_id, u["business_id"])
        ).fetchone()
        if not row:
            return api_error("not_found", "no user", 404)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return Response(status_code=204)
