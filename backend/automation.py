"""After-call automation: summary JSON -> CRM -> follow-up -> owner alert + scheduler.

LLM call and WhatsApp sends are injected (fakes offline, real ones with keys).
"""
import json
import logging
from datetime import datetime, timedelta, timezone

import db

log = logging.getLogger("automation")

OUTCOMES = {"booked", "task", "answered", "busy", "missed"}
STAGES = {"new", "lead", "booked", "customer"}
FOLLOWUP_TEMPLATES = {"booking_confirmed", "booking_reminder", "booking_changed",
                      "message_received", "task_done", "call_thanks"}


def queue_message(business_id: int, kind: str, body: str = "", contact_id=None,
                  call_id=None, booking_id=None, task_id=None, template="",
                  language="") -> int:
    # NOTE: dup of main.stub_send; merge when the webhook calls post_call.
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO messages (business_id, contact_id, call_id, booking_id, task_id,
                                     kind, template, language, body, status)
               VALUES (?,?,?,?,?,?,?,?,?,'queued')""",
            (business_id, contact_id, call_id, booking_id, task_id, kind,
             template, language, body))
        conn.commit()
        return cur.lastrowid


def _stub_llm(transcript: str, business: dict) -> dict:
    """Fallback until MODEL_API_KEY lands: generic thanks, no CRM change."""
    return {"summary": "", "outcome": "answered", "language": "",
            "customer_name": "", "stage": "", "tags": [],
            "followup": {"template": "call_thanks",
                         "params": ["friend", business.get("name", "")]},
            "owner_alert": ""}


def upsert_contact(business_id: int, wa_user_id: str, phone: str,
                   fields: dict, call_at: str) -> tuple[int, dict]:
    """Upsert by (business, wa_user_id); returns (id, changes dict)."""
    changes: dict = {}
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM contacts WHERE business_id = ? AND wa_user_id = ?",
            (business_id, wa_user_id)).fetchone()
        if not row:
            tags = fields.get("tags") or []
            cur = conn.execute(
                """INSERT INTO contacts (business_id, wa_user_id, phone, name, language,
                                         stage, tags, first_call_at, last_call_at, calls_count)
                   VALUES (?,?,?,?,?,?,?,?,?,1)""",
                (business_id, wa_user_id, phone, fields.get("customer_name", ""),
                 fields.get("language", ""), fields.get("stage") or "new",
                 json.dumps(tags), call_at, call_at))
            conn.commit()
            for k in ("customer_name", "language", "stage", "tags"):
                if fields.get(k):
                    changes[k] = {"from": "", "to": fields[k]}
            return cur.lastrowid, changes
        d = dict(row)
        upd: dict = {"last_call_at": call_at, "calls_count": d["calls_count"] + 1}
        if phone and not d["phone"]:
            upd["phone"] = phone
        if fields.get("customer_name") and fields["customer_name"] != d["name"]:
            upd["name"] = fields["customer_name"]
        if fields.get("language") and fields["language"] != d["language"]:
            upd["language"] = fields["language"]
        if fields.get("stage") in STAGES and fields["stage"] != d["stage"]:
            upd["stage"] = fields["stage"]
        if fields.get("tags"):
            try:
                old_tags = json.loads(d["tags"]) if d["tags"] else []
            except ValueError:
                old_tags = []
            merged = sorted(set(old_tags) | set(fields["tags"]))
            if merged != old_tags:
                upd["tags"] = json.dumps(merged)
        for k, v in upd.items():
            if k in ("last_call_at", "calls_count"):
                continue
            old = d.get(k if k != "name" else "name")
            if old != v:
                changes[k] = {"from": old, "to": v}
        conn.execute(f"UPDATE contacts SET {', '.join(f'{k} = ?' for k in upd)} WHERE id = ?",
                     (*upd.values(), d["id"]))
        conn.commit()
        return d["id"], changes


def crm_post(url: str, payload: dict) -> bool:
    """POST contact+call JSON; False on any failure (scheduler retries once)."""
    import httpx
    try:
        return httpx.post(url, json=payload, timeout=10).is_success
    except Exception as e:
        log.warning("crm webhook failed: %s", e)
        return False


def post_call(call_id: int, llm_json=None) -> dict:
    """Run the full after-call chain for one finished call."""
    with db.connect() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if not call:
            raise ValueError("no call")
        call = dict(call)
        biz = dict(conn.execute("SELECT * FROM businesses WHERE id = ?",
                                (call["business_id"],)).fetchone())
        contact = conn.execute("SELECT * FROM contacts WHERE id = ?",
                               (call["contact_id"],)).fetchone()
        lines = conn.execute("SELECT role, text FROM transcripts WHERE call_id = ? ORDER BY id",
                             (call_id,)).fetchall()
    transcript = "\n".join(f"{r['role']}: {r['text']}" for r in lines)
    data = (llm_json or _stub_llm)(transcript, biz)
    outcome = data.get("outcome") if data.get("outcome") in OUTCOMES else "answered"
    wa_user_id = dict(contact)["wa_user_id"] if contact else f"call-{call_id}"
    phone = dict(contact)["phone"] if contact else ""
    cid, changes = upsert_contact(call["business_id"], wa_user_id, phone, data,
                                  call["started_at"] or utcnow())
    with db.connect() as conn:
        conn.execute("UPDATE calls SET outcome = ?, language = ?, summary = ?,"
                     " contact_id = ?, crm_changes = ? WHERE id = ?",
                     (outcome, data.get("language", ""), data.get("summary", ""),
                      cid, json.dumps(changes), call_id))
        conn.commit()
    # External CRM
    if biz.get("crm_webhook_url"):
        payload = {"event": "call.completed", "business": biz["name"],
                   "contact": {"name": data.get("customer_name", ""), "phone": phone,
                               "language": data.get("language", ""),
                               "stage": data.get("stage", ""), "tags": data.get("tags", [])},
                   "call": {"id": call_id, "started_at": call["started_at"],
                            "duration_s": call["duration_s"], "outcome": outcome,
                            "summary": data.get("summary", "")},
                   "bookings": [], "tasks": []}
        if not crm_post(biz["crm_webhook_url"], payload):
            changes["_crm_webhook"] = "pending"
            with db.connect() as conn:
                conn.execute("UPDATE calls SET crm_changes = ? WHERE id = ?",
                             (json.dumps(changes), call_id))
                conn.commit()
    # Follow-up in the caller's language
    f = data.get("followup") or {}
    tmpl = f.get("template") if f.get("template") in FOLLOWUP_TEMPLATES else "call_thanks"
    queue_message(call["business_id"], "followup",
                  body=" | ".join(f.get("params", [])), contact_id=cid, call_id=call_id,
                  template=tmpl, language=data.get("language", ""))
    # Owner alert
    if data.get("owner_alert") and biz.get("owner_whatsapp"):
        queue_message(call["business_id"], "owner_alert", body=data["owner_alert"],
                      call_id=call_id, template="owner_new_lead")
    return {"call_id": call_id, "outcome": outcome, "contact_id": cid, "changes": changes}


def scheduler_tick(now=None) -> dict:
    """Reminders 3h before bookings; re-alert urgent tasks open >30min. Returns counts."""
    now = now or datetime.now(timezone.utc)
    done = {"reminders": 0, "realerts": 0, "crm_retries": 0}
    with db.connect() as conn:  # drop expired logins each tick
        conn.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
        conn.commit()
    with db.connect() as conn:
        bookings = conn.execute(
            "SELECT b.*, c.language FROM bookings b LEFT JOIN contacts c ON c.id = b.contact_id"
            " WHERE b.reminder_sent_at IS NULL AND b.status IN ('booked','changed')").fetchall()
        urgents = conn.execute(
            "SELECT * FROM tasks WHERE status = 'open' AND urgency = 'urgent'").fetchall()
        pending_crm = conn.execute(
            "SELECT id, business_id, crm_changes FROM calls WHERE crm_changes LIKE '%pending%'"
        ).fetchall()
    for b in bookings:
        b = dict(b)
        try:
            slot = datetime.fromisoformat(b["slot"])
        except ValueError:
            continue
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)
        if now < slot <= now + timedelta(hours=3):
            queue_message(b["business_id"], "reminder",
                          body=f"{b['name']} | {b['slot']}", contact_id=b["contact_id"],
                          booking_id=b["id"], template="booking_reminder",
                          language=b.get("language") or "")
            with db.connect() as conn:
                conn.execute("UPDATE bookings SET reminder_sent_at = datetime('now') WHERE id = ?",
                             (b["id"],))
                conn.commit()
            done["reminders"] += 1
    for t in urgents:
        t = dict(t)
        try:
            created = datetime.fromisoformat(t["created_at"])
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if now - created < timedelta(minutes=30):
            continue
        with db.connect() as conn:
            recent = conn.execute(
                "SELECT id FROM messages WHERE task_id = ? AND kind = 'owner_alert'"
                " AND sent_at > datetime('now','-30 minutes')", (t["id"],)).fetchone()
            biz = conn.execute("SELECT owner_whatsapp, crm_webhook_url FROM businesses WHERE id = ?",
                               (t["business_id"],)).fetchone()
        if not recent and biz and biz["owner_whatsapp"]:
            queue_message(t["business_id"], "owner_alert",
                          body=f"still open: {t['type']} — {t['details']}",
                          contact_id=t["contact_id"], task_id=t["id"], template="owner_new_lead")
            done["realerts"] += 1
    for c in pending_crm:  # one retry, then marked failed on the call
        c = dict(c)
        with db.connect() as conn:
            biz = conn.execute("SELECT crm_webhook_url FROM businesses WHERE id = ?",
                               (c["business_id"],)).fetchone()
        changes = json.loads(c["crm_changes"])
        ok = biz and biz["crm_webhook_url"] and crm_post(biz["crm_webhook_url"], {"retry": c["id"]})
        changes["_crm_webhook"] = "sent" if ok else "failed"
        with db.connect() as conn:
            conn.execute("UPDATE calls SET crm_changes = ? WHERE id = ?", (json.dumps(changes), c["id"]))
            conn.commit()
        done["crm_retries"] += 1
    return done


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def selfcheck() -> None:
    """Offline: fake LLM JSON drives CRM, follow-up, scheduler on a temp DB."""
    import tempfile
    tmp = tempfile.mkdtemp()
    db.DB_PATH = db.Path(tmp) / "t.db"
    db.init_db()
    with db.connect() as c:
        c.execute("INSERT INTO businesses (slug, name, owner_whatsapp) VALUES (?,?,?)",
                  ("cafe", "Your Cafe", "+91111"))
        c.execute("INSERT INTO contacts (business_id, wa_user_id, phone) VALUES (?,?,?)",
                  (1, "u9", "+919812345678"))
        c.execute("INSERT INTO calls (business_id, contact_id, wa_call_id, started_at)"
                  " VALUES (?,?,?,?)", (1, 1, "w1", utcnow()))
        c.execute("INSERT INTO transcripts (call_id, role, text) VALUES (?,?,?)",
                  (1, "caller", "table for 4 saturday"))
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        c.execute("INSERT INTO bookings (business_id, contact_id, name, party_size, slot)"
                  " VALUES (?,?,?,?,?)", (1, 1, "Priya", 4, future))
        c.execute("INSERT INTO tasks (business_id, contact_id, type, details, urgency,"
                  " created_at) VALUES (?,?,?,?,?,?)",
                  (1, 1, "complaint", "cold food", "urgent",
                   (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()))
        c.commit()

    def fake_llm(transcript, biz):
        assert "table for 4" in transcript
        return {"summary": "Table for 4 Saturday", "outcome": "booked", "language": "hi",
                "customer_name": "Priya", "stage": "booked", "tags": ["party"],
                "followup": {"template": "booking_confirmed", "params": ["Priya"]},
                "owner_alert": "New booking Priya"}

    r = post_call(1, fake_llm)
    assert r["outcome"] == "booked" and r["contact_id"] == 1, r
    with db.connect() as c:
        assert c.execute("SELECT stage FROM contacts WHERE id = 1").fetchone()[0] == "booked"
        kinds = [x[0] for x in c.execute("SELECT kind FROM messages ORDER BY id")]
        assert kinds == ["followup", "owner_alert"], kinds
    tick = scheduler_tick()
    assert tick == {"reminders": 1, "realerts": 1, "crm_retries": 0}, tick
    print("automation selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python automation.py selfcheck")
