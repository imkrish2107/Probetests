"""Business-initiated WhatsApp calls: permission, limits, connect/terminate.

Transport (creds, _call, GraphError) lives in outbound.py; this file owns
call state: the outbound_log table, per-vendor limits, and the webhook hook
that stashes SDP answers and scores terminate events.

Limits are enforced in code: 1 permission request per 24h, 2 per 7 days
per business+vendor pair, and never the 4th call after 3 unanswered in a
row (the 4th auto-revokes permission). Real network only happens in
outbound_test.py on the VPS and in the live webhook.
"""
import datetime as dt
import json
import os
import re
import tempfile

import db
import outbound

OUTBOUND_TABLE = """CREATE TABLE IF NOT EXISTS outbound_log (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, call_id TEXT DEFAULT '',
  phone TEXT DEFAULT '', at TEXT DEFAULT (datetime('now')))"""


ended: set = set()  # calls Meta reports as finished; a live quote call watches this


def digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def ensure_table() -> None:
    with db.connect() as conn:
        conn.execute(OUTBOUND_TABLE)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(outbound_log)").fetchall()]
        if "phone" not in cols:  # databases created before per-phone limits
            conn.execute("ALTER TABLE outbound_log ADD COLUMN phone TEXT DEFAULT ''")
        conn.commit()


def utc_sqlite(hours_ago: float = 0) -> str:
    """UTC as 'YYYY-MM-DD HH:MM:SS': string-comparable with SQLite datetime('now').

    Never compare Python isoformat() text against SQLite timestamps: the space
    sorts before isoformat's 'T', so every window check silently breaks.
    """
    return (dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def log(kind: str, call_id: str = "", phone: str = "") -> None:
    """kinds: request | connect_placed | connected | unanswered."""
    ensure_table()
    with db.connect() as conn:
        conn.execute("INSERT INTO outbound_log (kind, call_id, phone) VALUES (?, ?, ?)",
                     (kind, call_id or "", digits(phone)))
        conn.commit()


def limits_ok(phone: str = "") -> tuple[bool, str]:
    """Per-vendor gates. Creates its own table: safe on a fresh database."""
    ensure_table()
    phone = digits(phone)
    day = utc_sqlite(24)
    week = utc_sqlite(7 * 24)
    with db.connect() as conn:
        rows = conn.execute("SELECT kind, at FROM outbound_log WHERE phone = ? ORDER BY id",
                            (phone,)).fetchall()
    if sum(1 for k, at in rows if k == "request" and at > day) >= 1:
        return False, "permission already requested in the last 24h"
    if sum(1 for k, at in rows if k == "request" and at > week) >= 2:
        return False, "2 permission requests already sent in the last 7 days"
    streak = 0
    for k, _at in reversed(rows):
        if k == "connected":
            break
        if k == "unanswered":
            streak += 1
    if streak >= 3:
        return False, f"{streak} unanswered calls in a row, stopping before a 4th"
    return True, ""


def is_outbound(item: dict) -> bool:
    return item.get("direction") == "BUSINESS_INITIATED"


def permission_status(to: str) -> dict:
    token, pnid = outbound.creds()
    return outbound._call("GET", f"{pnid}/call_permissions", token,
                          params={"user_wa_id": digits(to)})


def request_permission(to: str, text: str) -> dict:
    """Free-form request; needs the vendor to have messaged the number in the
    last 24h (open service window). Outside it, Meta rejects and the owner
    must message the business number first, then rerun."""
    token, pnid = outbound.creds()
    data = outbound._call("POST", f"{pnid}/messages", token, json={
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": digits(to), "type": "interactive",
        "interactive": {"type": "call_permission_request",
                        "action": {"name": "call_permission_request"},
                        "body": {"text": text}}})
    log("request", phone=to)
    return data


def place_call(to: str, sdp_offer: str) -> str:
    token, pnid = outbound.creds()
    try:
        data = outbound._call("POST", f"{pnid}/calls", token, json={
            "messaging_product": "whatsapp", "to": digits(to), "action": "connect",
            "session": {"sdp_type": "offer", "sdp": sdp_offer},
            "biz_opaque_callback_data": "escape-outbound-test"})
    except outbound.GraphError as e:
        if "138006" in e.body:
            raise outbound.GraphError(e.status, e.body + " (no call permission: request it first, "
                                      "approve on the phone, then rerun)") from e
        raise
    call_id = ((data.get("calls") or [{}])[0].get("id", ""))
    log("connect_placed", call_id, to)
    return call_id


def terminate_call(call_id: str) -> dict:
    token, pnid = outbound.creds()
    return outbound._call("POST", f"{pnid}/calls", token, json={
        "messaging_product": "whatsapp", "call_id": call_id, "action": "terminate"})


def answer_path(call_id: str) -> str:
    safe = "".join(c for c in call_id if c.isalnum() or c in ".-_")[:80]
    return os.path.join(tempfile.gettempdir(), f"outbound_answer_{safe}.json")


def handle_outbound_item(item: dict, logger=None) -> None:
    """Webhook side: stash the SDP answer for outbound_test.py; score the
    terminate event into the unanswered streak. Never raises."""
    try:
        event = item.get("event")
        if event == "connect":
            sess = item.get("session") or {}
            if sess.get("sdp"):
                with open(answer_path(item.get("id", "")), "w") as f:
                    json.dump({"sdp_type": sess.get("sdp_type", "answer"),
                               "sdp": sess["sdp"]}, f)
        elif event == "terminate":
            ended.add(item.get("id", ""))
            log("connected" if item.get("duration") else "unanswered",
                item.get("id", ""), item.get("to", "") or "")
        elif logger:
            logger.info("outbound call event: %s", json.dumps(item)[:200])
    except Exception as e:
        if logger:
            logger.warning("outbound hook failed: %s", e)


def selfcheck() -> None:
    """Offline: limit gates against a temp DB, digits normalization, webhook
    scoring. No network, no keys."""
    import tempfile as _tf
    from pathlib import Path
    tmp = _tf.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmp) / "t.db"
    try:
        # fresh database, no table yet: limits_ok builds it (old crash)
        ok, _ = limits_ok("919111111111")
        assert ok, "empty log must pass"
        log("request", phone="+919111111111")
        ok, reason = limits_ok("919111111111")
        assert not ok and "24h" in reason, reason  # 1 request per 24h
        # same number without the + hits the same bucket (webhook numbers vary)
        ok, _ = limits_ok("919111111111")
        assert not ok, "+ and no-+ must share one bucket"
        with db.connect() as conn:  # age it out, keep the 7-day window
            conn.execute("UPDATE outbound_log SET at = datetime('now', '-2 days')")
            conn.commit()
        ok, reason = limits_ok("919111111111")
        assert ok, f"one request 2 days ago must pass: {reason}"
        log("request", phone="919111111111")
        with db.connect() as conn:  # two requests inside 7 days, none inside 24h
            conn.execute("UPDATE outbound_log SET at = datetime('now', '-2 days')")
            conn.commit()
        ok, reason = limits_ok("919111111111")
        assert not ok and "7 days" in reason, reason  # 2 requests per 7 days
        with db.connect() as conn:
            conn.execute("DELETE FROM outbound_log")
            conn.commit()
        log("request", phone="919111111111")
        with db.connect() as conn:
            conn.execute("UPDATE outbound_log SET at = datetime('now', '-20 hours')")
            conn.commit()
        ok, reason = limits_ok("919111111111")
        assert not ok and "24h" in reason, reason  # a request 20h old still blocks
        with db.connect() as conn:
            conn.execute("DELETE FROM outbound_log")
            conn.commit()
        log("unanswered", phone="919111111111")
        log("unanswered", phone="919111111111")
        ok, _ = limits_ok("919111111111")
        assert ok, "2 in a row still allowed"
        log("unanswered", phone="919111111111")
        ok, reason = limits_ok("919111111111")
        assert not ok and "in a row" in reason, reason  # stop before the 4th
        log("connected", phone="919111111111")
        ok, _ = limits_ok("919111111111")
        assert ok, "an answered call resets the streak"
        with db.connect() as conn:
            conn.execute("DELETE FROM outbound_log")
            conn.commit()
        log("unanswered", phone="+911111111111")
        log("unanswered", phone="+911111111111")
        log("unanswered", phone="+911111111111")
        ok, _ = limits_ok("911111111111")
        assert not ok, "3 unanswered to one number blocks that number"
        ok, _ = limits_ok("912222222222")
        assert ok, "limits apply per phone, not globally"
        # webhook scoring: connect stashes SDP, terminate scores the streak
        handle_outbound_item({"direction": "BUSINESS_INITIATED", "event": "connect",
                              "id": "wacid.selfcheck",
                              "session": {"sdp_type": "answer", "sdp": "v=0"}})
        p = answer_path("wacid.selfcheck")
        assert json.load(open(p))["sdp"] == "v=0", p
        os.remove(p)
        handle_outbound_item({"direction": "BUSINESS_INITIATED", "event": "terminate",
                              "id": "wacid.1", "to": "913333333333"})
        handle_outbound_item({"direction": "BUSINESS_INITIATED", "event": "terminate",
                              "id": "wacid.2", "to": "+913333333333"})
        handle_outbound_item({"direction": "BUSINESS_INITIATED", "event": "terminate",
                              "id": "wacid.3", "to": "913333333333"})
        ok, reason = limits_ok("913333333333")
        assert not ok and "in a row" in reason, reason  # webhook phones score too
        handle_outbound_item({"direction": "BUSINESS_INITIATED", "event": "terminate",
                              "id": "wacid.4", "to": "913333333333", "duration": 12})
        ok, _ = limits_ok("913333333333")
        assert ok, "an answered call resets the streak"
    finally:
        db.DB_PATH = old
    print("call_out selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python call_out.py selfcheck")
