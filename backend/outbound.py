"""Outbound call plumbing (STORE_BUILD Phase 1): limits, Graph helpers, webhook hook.

Limits are enforced in code, not just docs: 1 permission request per
24h, 2 per 7 days, and never place the 4th call after 3 unanswered in a
row. Real network only happens in outbound_test.py and the live webhook.
"""
import datetime as dt
import json
import os
import tempfile

import db

GRAPH = "https://graph.facebook.com/v21.0"

OUTBOUND_TABLE = """CREATE TABLE IF NOT EXISTS outbound_log (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, call_id TEXT DEFAULT '',
  at TEXT DEFAULT (datetime('now')))"""


def ensure_table() -> None:
    with db.connect() as conn:
        conn.execute(OUTBOUND_TABLE)
        conn.commit()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def log(kind: str, call_id: str = "") -> None:
    """kinds: request | connect_placed | connected | unanswered."""
    ensure_table()
    with db.connect() as conn:
        conn.execute("INSERT INTO outbound_log (kind, call_id) VALUES (?, ?)",
                     (kind, call_id or ""))
        conn.commit()


def limits_ok() -> tuple[bool, str]:
    now = _now()
    day = (now - dt.timedelta(hours=24)).isoformat()
    week = (now - dt.timedelta(days=7)).isoformat()
    with db.connect() as conn:
        rows = conn.execute("SELECT kind, at FROM outbound_log ORDER BY id").fetchall()
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


def creds() -> tuple[str, str]:
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("WHATSAPP_TOKEN", "")
    pnid = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not token or not pnid:
        raise RuntimeError("WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID missing in backend/.env")
    return token, pnid


class GraphError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"graph {status}: {body[:200]}")
        self.status = status
        self.body = body


def _call(method: str, path: str, token: str, **kw) -> dict:
    import httpx
    r = httpx.request(method, f"{GRAPH}/{path}", headers={"Authorization": f"Bearer {token}"},
                      timeout=20, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        raise GraphError(r.status_code, json.dumps(data.get("error", r.text)))
    return data if isinstance(data, dict) else {}


def permission_status(to: str) -> dict:
    token, pnid = creds()
    return _call("GET", f"{pnid}/call_permissions", token, params={"user_wa_id": to})


def request_permission(to: str, text: str) -> dict:
    """Free-form request; needs the owner to have messaged the number in the
    last 24h (open service window). Outside it, Meta rejects and the owner
    must message the business number first, then rerun."""
    token, pnid = creds()
    data = _call("POST", f"{pnid}/messages", token, json={
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
        "type": "interactive",
        "interactive": {"type": "call_permission_request",
                        "action": {"name": "call_permission_request"},
                        "body": {"text": text}}})
    log("request")
    return data


def place_call(to: str, sdp_offer: str) -> str:
    token, pnid = creds()
    try:
        data = _call("POST", f"{pnid}/calls", token, json={
            "messaging_product": "whatsapp", "to": to, "action": "connect",
            "session": {"sdp_type": "offer", "sdp": sdp_offer},
            "biz_opaque_callback_data": "escape-outbound-test"})
    except GraphError as e:
        if "138006" in e.body:
            raise GraphError(e.status, e.body + " (no call permission: request it first, "
                             "approve on the phone, then rerun)") from e
        raise
    call_id = ((data.get("calls") or [{}])[0].get("id", ""))
    log("connect_placed", call_id)
    return call_id


def terminate_call(call_id: str) -> dict:
    token, pnid = creds()
    return _call("POST", f"{pnid}/calls", token, json={
        "messaging_product": "whatsapp", "call_id": call_id, "action": "terminate"})


def send_text(to: str, text: str) -> dict:
    """Free-form text; needs the 24h service window open."""
    token, pnid = creds()
    return _call("POST", f"{pnid}/messages", token, json={
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to, "type": "text", "text": {"body": text}})


def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> dict:
    """Up to 3 quick-reply buttons. Free-form; needs the open window."""
    token, pnid = creds()
    return _call("POST", f"{pnid}/messages", token, json={
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to, "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body},
                        "action": {"buttons": [
                            {"type": "reply", "reply": {"id": i, "title": t}}
                            for i, t in buttons[:3]]}}})
    return item.get("direction") == "BUSINESS_INITIATED"


def is_outbound(item: dict) -> bool:
    return item.get("direction") == "BUSINESS_INITIATED"


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
            log("connected" if item.get("duration") else "unanswered", item.get("id", ""))
        elif logger:
            logger.info("outbound call event: %s", json.dumps(item)[:200])
    except Exception as e:
        if logger:
            logger.warning("outbound hook failed: %s", e)


def selfcheck() -> None:
    """Offline: limit gates against a temp DB. No network, no keys."""
    import tempfile as _tf
    tmp = _tf.mkdtemp()
    db.DB_PATH = db.Path(tmp) / "t.db"
    ensure_table()
    ok, _ = limits_ok()
    assert ok, "empty log must pass"
    log("request")
    ok, reason = limits_ok()
    assert not ok and "24h" in reason, reason  # 1 request per 24h
    with db.connect() as conn:  # age it out, keep the 7-day window
        conn.execute("UPDATE outbound_log SET at = datetime('now', '-2 days')")
        conn.commit()
    ok, reason = limits_ok()
    assert ok, f"one request 2 days ago must pass: {reason}"
    log("request")
    with db.connect() as conn:  # two requests inside 7 days, none inside 24h
        conn.execute("UPDATE outbound_log SET at = datetime('now', '-2 days')")
        conn.commit()
    ok, reason = limits_ok()
    assert not ok and "7 days" in reason, reason  # 2 requests per 7 days
    with db.connect() as conn:
        conn.execute("DELETE FROM outbound_log")
        conn.commit()
    log("unanswered")
    log("unanswered")
    ok, _ = limits_ok()
    assert ok, "2 in a row still allowed"
    log("unanswered")
    ok, reason = limits_ok()
    assert not ok and "in a row" in reason, reason  # stop before the 4th
    log("connected")
    ok, _ = limits_ok()
    assert ok, "an answered call resets the streak"
    print("outbound selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python outbound.py selfcheck")
