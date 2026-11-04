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
    if biz.get("slug") == "escape":
        return build_support_prompt(biz)
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
Speak {langs[0]} first. Reply only in the language named in the latest [reply in: X] note, native script. Start with that language's tag, e.g. [ta].
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


# ---- ESCAPE store: confirmation tools use the call's order, never another ID ----

def _call_order(ctx: dict) -> dict:
    import store
    return store.get_order(ctx["business_id"], ctx.get("order_id") or 0) or {}


def get_order_for_call(ctx: dict) -> dict:
    o = _call_order(ctx)
    if not o:
        return {"error": "no_order"}
    items = ", ".join(f"{i['qty']}x {i['name']} ({i['size']})" for i in o["items"])
    return {"id": o["id"], "items": items, "total": o["items_total_paise"],
            "name": o["name"], "address": o["address"], "status": o["status"]}


def _order_act(ctx: dict, action: str, note: str = "") -> dict:
    import store
    o = _call_order(ctx)
    if not o:
        return {"error": "no_order"}
    return store.order_action(ctx["business_id"], o["id"], o["phone"], action, note)


def confirm_order(ctx: dict) -> dict:
    return _order_act(ctx, "confirmed")


def request_change(ctx: dict, note: str = "") -> dict:
    return _order_act(ctx, "change_requested", note)


def cancel_order(ctx: dict, order_id: int = 0, reason: str = "") -> dict:
    """Confirmation call: no id, cancels the call's order. Support call: id plus
    verified same-phone, before shipping only. Unverified callers get
    not_verified so no order data leaks."""
    if order_id:
        import store
        o = _support_order(ctx, order_id)
        if not o:
            return {"error": "not_verified" if not ctx.get("verified_phone") else "not_found"}
        if o["status"] not in store.PRE_SHIP:
            return {"error": "too_late", "status": o["status"]}
        return store.order_action(ctx["business_id"], o["id"], o["phone"], "cancelled", reason)
    return _order_act(ctx, "cancelled", reason)


def send_otp(ctx: dict, phone: str) -> dict:
    """Send the login code to the order phone. Same reply either way."""
    import store
    return store.request_otp(ctx["business_id"], phone)


def verify_otp(ctx: dict, phone: str, code: str) -> dict:
    import store
    ok, reason = store.verify_otp(ctx["business_id"], phone, code)
    if ok:
        ctx["verified_phone"] = phone  # dict persists for the rest of the call
        return {"verified": True}
    return {"verified": False, "reason": reason}


def _support_order(ctx: dict, order_id: int) -> dict:
    import store
    phone = ctx.get("verified_phone") or ""
    if not phone:
        return {}
    o = store.get_order(ctx["business_id"], order_id)
    if not o or not store.same_phone(o["phone"], phone):
        return {}
    return o


def get_order_status(ctx: dict, order_id: int = 0) -> dict:
    import store
    phone = ctx.get("verified_phone") or ""
    if not phone:
        return {"error": "not_verified"}
    if order_id:
        o = _support_order(ctx, order_id)
        return {"id": o["id"], "status": o["status"],
                "total": o["items_total_paise"]} if o else {"error": "not_found"}
    out = []
    for o in store.orders_for_phone(ctx["business_id"], phone):
        items = ", ".join(f"{i['qty']}x {i['name']}" for i in
                          store.get_order(ctx["business_id"], o["id"])["items"])
        out.append({"id": o["id"], "status": o["status"],
                    "total": o["items_total_paise"], "items": items})
    return {"orders": out}


def request_address_change(ctx: dict, order_id: int, address: str) -> dict:
    import store
    o = _support_order(ctx, order_id)
    if not o:
        return {"error": "not_verified" if not ctx.get("verified_phone") else "not_found"}
    if o["status"] not in store.PRE_SHIP:
        return {"error": "too_late", "status": o["status"]}
    address = (address or "").strip()
    if len(address) < 8:
        return {"error": "bad_address"}
    with db.connect() as conn:
        conn.execute("UPDATE orders SET address = ?, updated_at = datetime('now') WHERE id = ?",
                     (address, order_id))
        conn.commit()
    return {"id": order_id, "status": o["status"], "address": address}


def create_return_request(ctx: dict, order_id: int, reason: str = "") -> dict:
    o = _support_order(ctx, order_id)
    if not o:
        return {"error": "not_verified" if not ctx.get("verified_phone") else "not_found"}
    return create_task(ctx, "other", f"RETURN order {order_id}: {reason or 'no reason given'}")


def request_human_callback(ctx: dict, reason: str = "") -> dict:
    return request_callback(ctx, reason)


def build_support_prompt(biz: dict) -> str:
    langs = biz.get("languages") or ["English"]
    return f"""You are {biz.get('name')}'s AI assistant on a WhatsApp voice call. Say so in your greeting.
Speak {langs[0]} first. Reply only in the language the caller last spoke, native script.
Ask for the phone number on their order. Read back its last 4 digits, then call send_otp.
Say the same line whether or not it exists: "If that number has an order, I've sent a code."
When verify_otp returns verified, ask for their query. Tools work only after verification:
get_order_status, request_address_change (before shipping only), cancel_order (before shipping
only), create_return_request, request_human_callback. Refunds always become a human task.
Never reveal order details before verification. Keep every reply to 1-2 short sentences
(under 40 words); this is a voice call, not chat. Use end_call when done."""


def build_confirm_prompt(biz: dict, order: dict) -> str:
    items = ", ".join(f"{i['qty']}x {i['name']} ({i['size']})" for i in order.get("items", []))
    return (f"You are {biz.get('name')}'s AI assistant confirming order #{order['id']} on a WhatsApp call. Say so."
            f" Check you are speaking to {order['name']}. Items: {items}."
            f" Total {order['items_total_paise'] // 100} rupees, cash on delivery."
            f" Address: {order['address']}. Use get_order_for_call, then confirm_order,"
            " request_change or cancel_order, then end_call. 1-2 short sentences per reply.")


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
          "create_task": create_task, "end_call": end_call,
          "get_order_for_call": get_order_for_call, "confirm_order": confirm_order,
          "request_change": request_change, "cancel_order": cancel_order,
          "send_otp": send_otp, "verify_otp": verify_otp,
          "get_order_status": get_order_status,
          "request_address_change": request_address_change,
          "create_return_request": create_return_request,
          "request_human_callback": request_human_callback}


def _schema(name: str, desc: str, props: dict, req: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}}


STORE_TOOLS = [
    _schema("get_order_for_call", "Read the call's order: items, total, address.",
            {}, []),
    _schema("confirm_order", "Confirm the call's order.", {}, []),
    _schema("request_change", "Mark change requested with a note.",
            {"note": {"type": "string"}}, []),
    _schema("cancel_order", "Cancel the call's order, or a verified order id before shipping.",
            {"order_id": {"type": "integer"}, "reason": {"type": "string"}}, []),
    _schema("send_otp", "Text a login code to the order phone.",
            {"phone": {"type": "string"}}, ["phone"]),
    _schema("verify_otp", "Check the spoken code. Sets verification on success.",
            {"phone": {"type": "string"}, "code": {"type": "string"}}, ["phone", "code"]),
    _schema("get_order_status", "Orders for the verified phone; optional one order.",
            {"order_id": {"type": "integer"}}, []),
    _schema("request_address_change", "New address, before shipping only.",
            {"order_id": {"type": "integer"}, "address": {"type": "string"}},
            ["order_id", "address"]),
    _schema("create_return_request", "Return request becomes a human task.",
            {"order_id": {"type": "integer"}, "reason": {"type": "string"}},
            ["order_id"]),
    _schema("request_human_callback", "Caller wants a person; urgent callback task.",
            {"reason": {"type": "string"}}, []),
    [t for t in TOOLS if t["function"]["name"] == "end_call"][0],
]


def tools_for(biz: dict) -> list[dict]:
    """ESCAPE calls get store tools; every other business keeps cafe tools."""
    return STORE_TOOLS if biz.get("slug") == "escape" else TOOLS


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
    import datetime as _dt
    _today = _dt.date.today()
    sat = (_today + _dt.timedelta(days=(5 - _today.weekday()) % 7 or 7)).isoformat()  # next Saturday
    free = check_slots(ctx, sat, 4)["free"]
    assert len(free) == 4, free  # 18,19,20,21
    b = book_table(ctx, "Priya", 4, free[0])
    assert b["status"] == "booked", b
    assert book_table(ctx, "Ravi", 4, free[0])["error"] == "full"  # second caller loses
    assert book_table(ctx, "Ravi", 2, free[1])["status"] == "booked"
    r = reschedule_booking(ctx, free[2])
    assert r["status"] == "changed" and r["id"] == b["id"], r
    assert cancel_booking(ctx, "change of plans")["status"] == "cancelled"
    assert cancel_booking(ctx)["status"] == "cancelled"  # two bookings exist; earliest cancels first
    assert cancel_booking(ctx)["error"] == "no_booking"  # nothing left
    t = create_task(ctx, "complaint", "cold food", "normal")
    assert t["urgency"] == "urgent", t  # forced
    assert create_task(ctx, "bogus", "x")["error"] == "bad_type"
    assert run_tool("nope", {}, ctx)["error"] == "unknown_tool"
    import store
    store.ensure_tables()
    assert tools_for({"slug": "escape"}) is STORE_TOOLS
    assert tools_for({"slug": "cafe"}) is TOOLS
    assert run_tool("get_order_status", {}, {"business_id": 1})["error"] == "not_verified"
    assert run_tool("verify_otp", {"phone": "+911234567890", "code": "000000"},
                    {"business_id": 1}) == {"verified": False, "reason": "no_code"}
    assert run_tool("get_order_for_call", {},
                    {"business_id": 1, "order_id": 0})["error"] == "no_order"
    assert run_tool("cancel_order", {"order_id": 1},
                    {"business_id": 1})["error"] == "not_verified"
    with db.connect() as conn:
        conn.execute("INSERT INTO businesses (slug, name) VALUES ('escape','ESCAPE')")
        conn.execute("INSERT INTO products (business_id, slug, name, price_paise)"
                     " VALUES (2,'tee','Tee',99900)")
        conn.commit()
    so = store.create_order("escape", [{"product_id": 1, "qty": 1}], "Sam", "+916666666666",
                            "5 Sea Rd, Kochi", True)
    vctx = {"business_id": 2, "verified_phone": "+916666666666"}
    assert run_tool("cancel_order", {"order_id": so["id"]}, vctx)["status"] == "cancelled"
    with db.connect() as conn:
        conn.execute("UPDATE orders SET status = 'shipped' WHERE id = ?", (so["id"],))
        conn.commit()
    r = run_tool("cancel_order", {"order_id": so["id"]}, vctx)
    assert r["error"] == "too_late" and r["status"] == "shipped", r
    assert end_call(ctx)["ended"] is True
    print("agent selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python agent.py selfcheck")
