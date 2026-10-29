"""Business brain: prompt builder + the 8 agent tools (offline-testable).

Tools run against SQLite directly; Pipecat calls run_tool() live later.
Pure logic here, no network, no keys.
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import db

log = logging.getLogger("agent")

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TASK_TYPES = {"catering_quote", "pickup_order", "complaint", "refund",
              "callback", "message", "other"}
BOOKED_STATES = ("booked", "changed")


def _biz(business_id: int) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if not row:
        raise ValueError("no business")
    d = dict(row)
    for f in ("hours", "menu", "faqs", "languages"):
        try:
            d[f] = json.loads(d[f]) if isinstance(d[f], str) else d[f]
        except ValueError:
            d[f] = {} if f == "hours" else []
    return d


def build_prompt(biz: dict) -> str:
    """Fixed per call (byte-stable so the prefix caches); date goes in the suffix."""
    langs = biz.get("languages") or ["English"]
    menu = "\n".join(
        f"- {m.get('name')}: {m.get('price')}"
        f"{' (veg)' if m.get('veg') else ''}"
        f"{' [contains: ' + ','.join(m.get('allergens', [])) + ']' if m.get('allergens') else ''}"
        for m in (biz.get("menu") or [])) or "Ask the team for today's menu."
    faqs = "\n".join(f"Q: {f.get('q')} A: {f.get('a')}" for f in (biz.get("faqs") or []))
    days = []
    for k in DAY_KEYS:
        spans = (biz.get("hours") or {}).get(k, [])
        days.append(f"{k}: " + (", ".join(f"{a}-{b}" for a, b in spans) if spans else "closed"))
    return f"""You are {biz.get('name')}'s AI assistant on a WhatsApp voice call. Say so in your greeting.
Speak {langs[0]} first; then reply in the caller's language, native script, starting every reply with a tag like [hi].
Hours: {'; '.join(days)}. Tables: {biz.get('slot_minutes', 30)}-min slots, {biz.get('seats_per_slot', 10)} seats each.
Menu:\n{menu}\nPrices: {biz.get('prices') or '-'}\n{('FAQs:\n' + faqs) if faqs else ''}
Rules: keep every reply to 1-2 short sentences (under 40 words); this is a voice call, not chat. Allergy/ingredient questions ONLY from the menu above, else make a task. Complaints and refunds are always urgent tasks. "Let me talk to someone" means an urgent callback task (no live transfer exists). If closed, say so and still take bookings/messages. Use tools for every booking or task; read bookings back before ending; then end_call."""


def context_suffix(today_iso: str, weekday: str, tz: str) -> str:
    return (f"Today is {today_iso} ({weekday}), business timezone {tz}. "
            "Resolve relative dates against it; tools take strict ISO datetimes with offset.")


def _slots_for(biz: dict, day_iso: str, party_size: int) -> tuple[list[str], dict]:
    """Free slot ISO strings for a day. Raises ValueError on bad date/closed day."""
    tz = ZoneInfo(biz.get("timezone") or "Asia/Kolkata")
    day = datetime.fromisoformat(day_iso).date() if "T" in day_iso else date_from(day_iso)
    key = DAY_KEYS[day.weekday()]
    spans = (biz.get("hours") or {}).get(key, [])
    if not spans:
        raise ValueError("closed")
    minutes, seats = biz.get("slot_minutes", 30), biz.get("seats_per_slot", 10)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT slot, party_size FROM bookings WHERE business_id = ? AND slot LIKE ?"
            f" AND status IN {BOOKED_STATES}".replace(str(BOOKED_STATES), "(?,?)"),
            (biz["id"], day.isoformat() + "%", *BOOKED_STATES),
        ).fetchall()
    used: dict[str, int] = {}
    for r in rows:
        try:
            k = datetime.fromisoformat(r["slot"]).isoformat()
        except ValueError:
            continue
        used[k] = used.get(k, 0) + (r["party_size"] or 0)
    free = []
    for o, c in spans:
        t = datetime.combine(day, _hm(o), tz)
        end = datetime.combine(day, _hm(c), tz)
        while (t_min := t.hour * 60 + t.minute) + minutes <= end.hour * 60 + end.minute:
            iso = t.isoformat()
            if used.get(iso, 0) + party_size <= seats:
                free.append(iso)
            t = t + _delta(minutes)
    return free, used


def date_from(s: str):
    from datetime import date as d
    return d.fromisoformat(s)


def _hm(s: str):
    from datetime import time as t
    h, m = s.split(":")
    return t(int(h), int(m))


def _delta(minutes: int):
    from datetime import timedelta as td
    return td(minutes=minutes)


def check_slots(ctx: dict, date: str, party_size: int) -> dict:
    try:
        free, _ = _slots_for(_biz(ctx["business_id"]), date, party_size)
    except ValueError:
        return {"error": "closed", "free": []}
    return {"date": date, "free": free}


def book_table(ctx: dict, name: str, party_size: int, slot: str, note: str = "") -> dict:
    biz = _biz(ctx["business_id"])
    try:
        want = datetime.fromisoformat(slot)
    except ValueError:
        return {"error": "bad_slot"}
    tz = ZoneInfo(biz.get("timezone") or "Asia/Kolkata")
    now = datetime.now(tz)
    if want.tzinfo is None:
        want = want.replace(tzinfo=tz)
    if want <= now:
        return {"error": "past"}
    try:
        free, _ = _slots_for(biz, want.date().isoformat(), party_size)
    except ValueError:
        return {"error": "closed", "free": []}
    if want.isoformat() not in free:
        return {"error": "full", "free": free}  # caller offers alternatives
    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")  # re-check inside one transaction
        used = conn.execute(
            "SELECT COALESCE(SUM(party_size),0) FROM bookings WHERE business_id = ?"
            " AND slot = ? AND status IN (?,?)",
            (biz["id"], want.isoformat(), *BOOKED_STATES)).fetchone()[0]
        if used + party_size > biz.get("seats_per_slot", 10):
            conn.execute("ROLLBACK")
            return {"error": "full", "free": [f for f in free if f != want.isoformat()]}
        cur = conn.execute(
            """INSERT INTO bookings (business_id, contact_id, call_id, name, party_size, slot, note)
               VALUES (?,?,?,?,?,?,?)""",
            (biz["id"], ctx.get("contact_id"), ctx.get("call_id"), name, party_size,
             want.isoformat(), note))
        conn.commit()
        return {"id": cur.lastrowid, "slot": want.isoformat(), "status": "booked"}
    finally:
        conn.close()


def _next_booking(ctx: dict):
    biz = _biz(ctx["business_id"])
    tz = ZoneInfo(biz.get("timezone") or "Asia/Kolkata")
    now_iso = datetime.now(tz).isoformat()
    with db.connect() as conn:
        return conn.execute(
            """SELECT * FROM bookings WHERE business_id = ? AND contact_id = ?
               AND status IN (?,?) AND slot >= ? ORDER BY slot LIMIT 1""",
            (ctx["business_id"], ctx.get("contact_id"), *BOOKED_STATES, now_iso)).fetchone()


def reschedule_booking(ctx: dict, new_slot: str) -> dict:
    row = _next_booking(ctx)
    if not row:
        return {"error": "no_booking"}
    try:
        want = datetime.fromisoformat(new_slot)
    except ValueError:
        return {"error": "bad_slot"}
    biz = _biz(ctx["business_id"])
    tz = ZoneInfo(biz.get("timezone") or "Asia/Kolkata")
    if want.tzinfo is None:
        want = want.replace(tzinfo=tz)
    try:
        free, _ = _slots_for(biz, want.date().isoformat(), row["party_size"])
    except ValueError:
        return {"error": "closed", "free": []}
    if want.isoformat() not in free:
        return {"error": "full", "free": free}
    with db.connect() as conn:
        conn.execute("UPDATE bookings SET slot = ?, status = 'changed', updated_at = datetime('now')"
                     " WHERE id = ?", (want.isoformat(), row["id"]))
        conn.commit()
    return {"id": row["id"], "slot": want.isoformat(), "status": "changed"}


def cancel_booking(ctx: dict, reason: str = "") -> dict:
    row = _next_booking(ctx)
    if not row:
        return {"error": "no_booking"}
    with db.connect() as conn:
        conn.execute("UPDATE bookings SET status = 'cancelled', note = note || ?,"
                     " updated_at = datetime('now') WHERE id = ?",
                     (f" [cancel: {reason}]" if reason else "", row["id"]))
        conn.commit()
    return {"id": row["id"], "status": "cancelled"}


def create_task(ctx: dict, type: str, details: str, urgency: str = "normal") -> dict:
    if type not in TASK_TYPES:
        return {"error": "bad_type"}
    if type in ("complaint", "refund"):
        urgency = "urgent"  # never a normal complaint
    if urgency not in ("normal", "urgent"):
        urgency = "normal"
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (business_id, contact_id, call_id, type, details, urgency)
               VALUES (?,?,?,?,?,?)""",
            (ctx["business_id"], ctx.get("contact_id"), ctx.get("call_id"),
             type, details, urgency))
        conn.commit()
        return {"id": cur.lastrowid, "type": type, "urgency": urgency, "status": "open"}


def take_message(ctx: dict, name: str, message: str) -> dict:
    return create_task(ctx, "message", f"{name}: {message}")


def request_callback(ctx: dict, reason: str = "") -> dict:
    return create_task(ctx, "callback", reason or "caller asked for a person", "urgent")


def end_call(ctx: dict, reason: str = "") -> dict:
    return {"ended": True, "reason": reason}


TOOLS = [
    {"type": "function", "function": {"name": "check_slots", "description": "Free table slots (ISO with offset) for a day.",
     "parameters": {"type": "object", "properties": {"date": {"type": "string"}, "party_size": {"type": "integer"}}, "required": ["date", "party_size"]}}},
    {"type": "function", "function": {"name": "book_table", "description": "Save a booking; read the slot back to the caller.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "party_size": {"type": "integer"}, "slot": {"type": "string"}, "note": {"type": "string"}}, "required": ["name", "party_size", "slot"]}}},
    {"type": "function", "function": {"name": "reschedule_booking", "description": "Move the caller's next booking.",
     "parameters": {"type": "object", "properties": {"new_slot": {"type": "string"}}, "required": ["new_slot"]}}},
    {"type": "function", "function": {"name": "cancel_booking", "description": "Cancel the caller's next booking.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "take_message", "description": "Take a message for the team.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "message": {"type": "string"}}, "required": ["name", "message"]}}},
    {"type": "function", "function": {"name": "request_callback", "description": "Caller wants a person; urgent callback task.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "create_task", "description": "Task needing a person.",
     "parameters": {"type": "object", "properties": {"type": {"type": "string"}, "details": {"type": "string"}, "urgency": {"type": "string"}}, "required": ["type", "details"]}}},
    {"type": "function", "function": {"name": "end_call", "description": "Say goodbye then hang up.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": []}}},
]

_FUNCS = {"check_slots": check_slots, "book_table": book_table,
          "reschedule_booking": reschedule_booking, "cancel_booking": cancel_booking,
          "take_message": take_message, "request_callback": request_callback,
          "create_task": create_task, "end_call": end_call}


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    fn = _FUNCS.get(name)
    if not fn:
        return {"error": "unknown_tool"}
    try:
        return fn(ctx, **args)
    except TypeError:
        return {"error": "bad_args"}
    except Exception as e:  # tools must never crash the call
        log.warning("tool %s failed: %s", name, e)
        return {"error": "tool_failed"}


def selfcheck() -> None:
    """Offline check with a temp DB: slots, booking race, tasks, prompt budget."""
    import tempfile
    tmp = tempfile.mkdtemp()
    db.DB_PATH = db.Path(tmp) / "t.db"
    db.init_db()
    with db.connect() as c:
        c.execute("INSERT INTO businesses (slug, name, timezone, hours, slot_minutes,"
                  " seats_per_slot, menu, languages) VALUES (?,?,?,?,?,?,?,?)",
                  ("cafe", "Your Cafe", "Asia/Kolkata",
                   json.dumps({"sat": [["18:00", "22:00"]]}), 60, 4,
                   json.dumps([{"name": "Dosa", "price": 120, "veg": True,
                                "allergens": ["gluten"]}]), '["Hindi","English"]'))
        c.execute("INSERT INTO contacts (business_id, wa_user_id, phone, name) VALUES (?,?,?,?)",
                  (1, "u1", "+911234567890", "Priya"))
        c.commit()
    ctx = {"business_id": 1, "contact_id": 1, "call_id": None}
    assert len(build_prompt(_biz(1)).split()) < 400, "prompt over budget"
    sat = "2026-10-31"  # a Saturday
    free = check_slots(ctx, sat, 4)["free"]
    assert len(free) == 4, free  # 18,19,20,21
    b = book_table(ctx, "Priya", 4, free[0])
    assert b["status"] == "booked", b
    assert book_table(ctx, "Ravi", 4, free[0])["error"] == "full"  # second caller loses
    assert book_table(ctx, "Ravi", 2, free[1])["status"] == "booked"
    r = reschedule_booking(ctx, free[2])
    assert r["status"] == "changed" and r["id"] == b["id"], r
    assert cancel_booking(ctx, "change of plans")["status"] == "cancelled"
    assert cancel_booking(ctx)["error"] == "no_booking"  # nothing left
    t = create_task(ctx, "complaint", "cold food", "normal")
    assert t["urgency"] == "urgent", t  # forced
    assert create_task(ctx, "bogus", "x")["error"] == "bad_type"
    assert run_tool("nope", {}, ctx)["error"] == "unknown_tool"
    assert end_call(ctx)["ended"] is True
    print("agent selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python agent.py selfcheck")
