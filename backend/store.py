"""ESCAPE store: products, orders, OTP support gate, try-on (STORE_BUILD 2-4).

Prices in paise, computed on the server. COD only. Phones matched on the
last 10 digits. No order data leaves without a phone match or OTP verify.
"""
import os
import re
import secrets
import time

import db
import outbound

STATUSES = ("pending_call", "confirmed", "change_requested", "cancelled",
            "shipped", "delivered", "needs_followup")
OPEN = ("pending_call", "change_requested", "needs_followup")  # customer can still act
PRE_SHIP = ("pending_call", "confirmed", "change_requested", "needs_followup")

STORE_TABLES = """
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  slug TEXT NOT NULL, name TEXT NOT NULL, price_paise INTEGER NOT NULL,
  image TEXT DEFAULT '', fabric TEXT DEFAULT '', fit TEXT DEFAULT '',
  sizes TEXT DEFAULT '["XS","S","M","L","XL"]', active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE (business_id, slug));
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  contact_id INTEGER REFERENCES contacts(id),
  name TEXT DEFAULT '', phone TEXT DEFAULT '', address TEXT DEFAULT '',
  items_total_paise INTEGER DEFAULT 0, status TEXT DEFAULT 'pending_call',
  note TEXT DEFAULT '', channel TEXT DEFAULT 'store',
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER REFERENCES products(id), name TEXT DEFAULT '',
  price_paise INTEGER DEFAULT 0, qty INTEGER DEFAULT 1, size TEXT DEFAULT 'M');
CREATE TABLE IF NOT EXISTS otps (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  phone TEXT NOT NULL, code_hash TEXT NOT NULL, attempts INTEGER DEFAULT 0,
  used_at TEXT DEFAULT '', expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')));
"""


def ensure_tables() -> None:
    with db.connect() as conn:
        conn.executescript(STORE_TABLES)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "order_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN order_id INTEGER DEFAULT 0")
        conn.commit()


def digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def same_phone(a: str, b: str) -> bool:
    da, dbb = digits(a), digits(b)
    return len(da) >= 7 and len(dbb) >= 7 and da[-10:] == dbb[-10:]


def inr(paise: int) -> str:
    return f"₹{paise // 100:,}"


def _biz_by_slug(slug: str) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM businesses WHERE slug = ?", (slug,)).fetchone()
    if not row:
        raise ValueError("no_business")
    return dict(row)


def list_products(slug: str) -> list[dict]:
    biz = _biz_by_slug(slug)
    with db.connect() as conn:
        rows = conn.execute("SELECT id, slug, name, price_paise, image, fabric, fit, sizes"
                            " FROM products WHERE business_id = ? AND active = 1 ORDER BY id",
                            (biz["id"],)).fetchall()
    return [dict(r) for r in rows]


def _ensure_contact_phone(business_id: int, phone: str, name: str = "") -> int:
    d = digits(phone)
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM contacts WHERE business_id = ? AND wa_user_id = ?",
                           (business_id, d)).fetchone()
        if row:
            if name:
                conn.execute("UPDATE contacts SET name = ? WHERE id = ?", (name, row["id"]))
                conn.commit()
            return row["id"]
        cur = conn.execute("INSERT INTO contacts (business_id, wa_user_id, phone, name)"
                           " VALUES (?,?,?,?)", (business_id, d, "+" + d, name))
        conn.commit()
        return cur.lastrowid


def create_order(slug: str, items: list[dict], name: str, phone: str,
                 address: str, call_consent: bool) -> dict:
    if not call_consent:
        raise ValueError("need_call_consent")
    name, address = (name or "").strip(), (address or "").strip()
    if len(digits(phone)) < 7:
        raise ValueError("bad_phone")
    if len(name) < 2 or len(address) < 8:
        raise ValueError("bad_details")
    if not items:
        raise ValueError("empty_cart")
    biz = _biz_by_slug(slug)
    with db.connect() as conn:
        prods = {r["id"]: dict(r) for r in conn.execute(
            "SELECT * FROM products WHERE business_id = ? AND active = 1", (biz["id"],)).fetchall()}
    lines = []
    total = 0
    for it in items:
        p = prods.get(int(it.get("product_id", 0)))
        qty = int(it.get("qty", 1))
        size = str(it.get("size", "M")).upper()
        if not p or not 1 <= qty <= 9:
            raise ValueError("bad_item")
        total += p["price_paise"] * qty
        lines.append((p, qty, size))
    cid = _ensure_contact_phone(biz["id"], phone, name)
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO orders (business_id, contact_id, name, phone, address,"
            " items_total_paise) VALUES (?,?,?,?,?,?)",
            (biz["id"], cid, name, "+" + digits(phone), address, total))
        oid = cur.lastrowid
        for p, qty, size in lines:
            conn.execute("INSERT INTO order_items (order_id, product_id, name, price_paise, qty, size)"
                         " VALUES (?,?,?,?,?,?)",
                         (oid, p["id"], p["name"], p["price_paise"], qty, size))
        conn.execute("INSERT INTO messages (business_id, contact_id, order_id, kind, status)"
                     " VALUES (?,?,?, 'order_placed', 'queued')", (biz["id"], cid, oid))
        conn.commit()
    return {"id": oid, "total": inr(total), "status": "pending_call",
            "whatsapp": wa_link(biz, oid)}


def wa_link(biz: dict, order_id: int) -> str:
    disp = digits(biz.get("wa_display_number") or "")
    if not disp:
        return ""
    return f"https://wa.me/{disp}?text=ORDER%20{order_id}"


def get_order(business_id: int, order_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ? AND business_id = ?",
                           (order_id, business_id)).fetchone()
        if not row:
            return None
        o = dict(row)
        o["items"] = [dict(r) for r in conn.execute(
            "SELECT name, price_paise, qty, size FROM order_items WHERE order_id = ?",
            (order_id,)).fetchall()]
    return o


def get_order_public(slug: str, order_id: int, phone: str) -> dict | None:
    biz = _biz_by_slug(slug)
    o = get_order(biz["id"], order_id)
    if not o or not same_phone(o["phone"], phone):
        return None
    return o


def order_action(business_id: int, order_id: int, phone: str,
                 action: str, note: str = "") -> dict:
    o = get_order(business_id, order_id)
    if not o or not same_phone(o["phone"], phone):
        return {"error": "not_found"}
    if action == "confirmed" and o["status"] in OPEN:
        st = "confirmed"
    elif action == "change_requested" and o["status"] in OPEN + ("confirmed",):
        st = "change_requested"
    elif action == "cancelled" and o["status"] in PRE_SHIP:
        st = "cancelled"
    else:
        return {"error": "bad_transition", "status": o["status"]}
    with db.connect() as conn:
        conn.execute("UPDATE orders SET status = ?, note = note || ?,"
                     " updated_at = datetime('now') WHERE id = ?",
                     (st, f" [{action}: {note}]" if note else "", order_id))
        conn.execute("INSERT INTO messages (business_id, contact_id, order_id, kind, status)"
                     " VALUES (?,?,?, 'order_update', 'queued')",
                     (business_id, o["contact_id"], order_id))
        conn.commit()
    return {"id": order_id, "status": st}


def orders_for_phone(business_id: int, phone: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM orders WHERE business_id = ? ORDER BY id DESC",
                            (business_id,)).fetchall()
    return [dict(r) for r in rows if same_phone(r["phone"], phone)]


def confirm_text(o: dict, biz_name: str) -> str:
    items = ", ".join(f"{i['qty']}x {i['name']} ({i['size']})" for i in o.get("items", []))
    return (f"Hi {o['name']}, this is {biz_name}. Your order #{o['id']}: {items},"
            f" total {inr(o['items_total_paise'])}. Cash on delivery. Please confirm.")


def send_confirm(business_id: int, order_id: int) -> bool:
    """Confirm / Change / Cancel buttons. Returns False outside the 24h window."""
    with db.connect() as conn:
        o = get_order(business_id, order_id)
    if not o:
        return False
    with db.connect() as conn:
        biz = dict(conn.execute("SELECT * FROM businesses WHERE id = ?",
                                (business_id,)).fetchone())
    try:
        outbound.send_buttons(o["phone"], confirm_text(o, biz["name"]), [
            (f"confirm_{order_id}", "Confirm"),
            (f"change_{order_id}", "Change"),
            (f"cancel_{order_id}", "Cancel")])
        sent = True
    except Exception:
        sent = False
    with db.connect() as conn:
        conn.execute("INSERT INTO messages (business_id, contact_id, order_id, kind, status)"
                     " VALUES (?,?,?, 'order_confirm', ?)",
                     (business_id, o["contact_id"], order_id, "sent" if sent else "failed"))
        conn.commit()
    return sent


def handle_order_link(business_id: int, sender_wa: str, text: str) -> str | None:
    """ORDER <id> from the order phone: permission request + confirm buttons."""
    m = re.match(r"(?i)^order\s+(\d+)\s*$", (text or "").strip())
    if not m:
        return None
    o = get_order(business_id, int(m.group(1)))
    if not o or not same_phone(o["phone"], sender_wa) or o["status"] not in OPEN:
        return None  # wrong phone or unknown order: stay silent, no oracle
    _ensure_contact_phone(business_id, o["phone"], o["name"])
    try:
        perm = outbound.permission_status("+" + digits(o["phone"]))
        if (perm.get("permission") or {}).get("status") not in ("temporary", "permanent"):
            ok, _ = outbound.limits_ok("+" + digits(o["phone"]))
            if ok:
                outbound.request_permission(
                    "+" + digits(o["phone"]),
                    f"Hi, this is ESCAPE. May we call you about order #{o['id']}?")
    except Exception:
        pass  # buttons below still work without call permission
    send_confirm(business_id, o["id"])
    return "sent"


def remind_pending() -> int:
    """Scheduler: pending_call orders older than 30min get one reminder, then
    needs_followup. Cut the unanswered-call retry; the message stays."""
    ensure_tables()
    cutoff = outbound.utc_sqlite(0.5)
    n = 0
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM orders WHERE status = 'pending_call'"
                            " AND created_at < ?", (cutoff,)).fetchall()
    for r in rows:
        o = dict(r)
        with db.connect() as conn:
            seen = conn.execute("SELECT id FROM messages WHERE order_id = ?"
                                " AND kind = 'order_remind'", (o["id"],)).fetchone()
        if seen:
            continue
        send_confirm(o["business_id"], o["id"])
        with db.connect() as conn:
            conn.execute("UPDATE orders SET status = 'needs_followup',"
                         " updated_at = datetime('now') WHERE id = ?", (o["id"],))
            conn.execute("INSERT INTO messages (business_id, contact_id, order_id, kind, status)"
                         " VALUES (?,?,?, 'order_remind', 'sent')",
                         (o["business_id"], o["contact_id"], o["id"]))
            conn.commit()
        n += 1
    return n


# ---- OTP support line ----

OTP_MSG = "If that number has an order, I've sent a code."


def request_otp(business_id: int, phone: str) -> dict:
    """Always the same message whether or not the number has orders. 6-digit
    code, hashed, 5min expiry, single use, 3 attempts, 3 sends/hour. The code
    goes only to the phone on the order. Never logged."""
    ensure_tables()
    if not orders_for_phone(business_id, phone):
        return {"sent": False, "message": OTP_MSG}
    import auth
    hour = outbound.utc_sqlite(1)
    with db.connect() as conn:
        sends = conn.execute("SELECT COUNT(*) FROM otps WHERE business_id = ? AND phone = ?"
                             " AND created_at > ?", (business_id, digits(phone), hour)).fetchone()[0]
    if sends >= 3:
        return {"sent": False, "message": OTP_MSG}
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    exp = outbound.utc_sqlite(-5 / 60)  # 5 min ahead, SQLite-shaped
    with db.connect() as conn:
        conn.execute("INSERT INTO otps (business_id, phone, code_hash, expires_at)"
                     " VALUES (?,?,?,?)",
                     (business_id, digits(phone), auth.hash_password(code), exp))
        conn.commit()
    try:
        outbound.send_text("+" + digits(phone),
                           f"Your ESCAPE code is {code}. It expires in 5 minutes. Never share it.")
    except Exception:
        with db.connect() as conn:
            crow = conn.execute("SELECT id FROM contacts WHERE business_id = ? AND wa_user_id = ?",
                                (business_id, digits(phone))).fetchone()
        with db.connect() as conn:
            conn.execute("INSERT INTO tasks (business_id, contact_id, type, details, urgency)"
                         " VALUES (?,?, 'callback', ?, 'urgent')",
                         (business_id, crow["id"] if crow else None,
                          f"OTP send failed for order phone ending {digits(phone)[-4:]}"))
            conn.commit()
        return {"sent": False,
                "message": "I couldn't send the code right now. I've asked the team to call you back."}
    return {"sent": True, "message": OTP_MSG}


def verify_otp(business_id: int, phone: str, code: str) -> tuple[bool, str]:
    ensure_tables()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM otps WHERE business_id = ? AND phone = ?"
                           " AND used_at = '' ORDER BY id DESC LIMIT 1",
                           (business_id, digits(phone))).fetchone()
    if not row:
        return False, "no_code"
    import auth
    if row["expires_at"] < outbound.utc_sqlite():
        return False, "expired"
    if row["attempts"] >= 3:
        return False, "locked"
    if not auth.verify_password(row["code_hash"], (code or "").strip()):
        with db.connect() as conn:
            conn.execute("UPDATE otps SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
            conn.commit()
        return False, "bad_code"
    with db.connect() as conn:
        conn.execute("UPDATE otps SET used_at = datetime('now') WHERE id = ?", (row["id"],))
        conn.commit()
    return True, "ok"


# ---- Virtual try-on (live browser frame, consent required) ----

TRYON_ENABLED = os.getenv("TRYON_ENABLED", "true").lower() not in ("0", "false", "no")
_tryon_hold: dict[str, tuple[bytes, float]] = {}  # id -> (jpeg, expiry); memory only
_tryon_ips: dict[str, list[float]] = {}


class TryonError(Exception):
    pass


def tryon_preview(image: bytes, mime: str, product: str = "") -> tuple[str, bytes]:
    """One browser frame in, one preview out. Holds the result in memory for
    an hour; never writes customer photos to disk, SQLite or git. Meta's own
    safety filter is the backstop: shortcut, add a vision check before public.
    """
    if not TRYON_ENABLED:
        raise TryonError("try-on is off")
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise TryonError("photo must be JPEG, PNG or WebP")
    if len(image) > 8 * 1024 * 1024:
        raise TryonError("photo over 8 MB")
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(image))
        im.verify()
        im = Image.open(io.BytesIO(image)).convert("RGB")
        if min(im.size) < 200:
            raise TryonError("photo too small")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)  # re-encode strips metadata
        clean = buf.getvalue()
    except TryonError:
        raise
    except Exception:
        raise TryonError("could not read that photo")
    garment = f", dressing them in {product}" if product else ""
    prompt = ("Keep the person's face, body shape, skin tone, pose and background"
              f" exactly unchanged{garment}; change only the clothing to match the"
              " garment's colour, pattern and cut. Photorealistic.")
    key = os.getenv("MODEL_API_KEY", "")
    if not key:
        raise TryonError("MODEL_API_KEY missing")
    import httpx
    try:
        r = httpx.post("https://api.meta.ai/v1/images/edits",
                       headers={"Authorization": f"Bearer {key}"}, timeout=120,
                       files={"image": ("photo.jpg", clean, "image/jpeg")},
                       data={"model": "muse-image-1.0", "prompt": prompt})
    except Exception as e:
        raise TryonError(f"image service unreachable: {e}") from e
    out = _parse_image_response(r)
    tid = secrets.token_hex(8)
    _tryon_hold[tid] = (out, time.time() + 3600)
    for k in [k for k, (_, exp) in _tryon_hold.items() if exp < time.time()]:
        del _tryon_hold[k]
    with db.connect() as conn:  # cost line only; no photo, no customer data
        try:
            conn.execute("INSERT INTO messages (business_id, kind, body, status)"
                         " VALUES (0, 'tryon', 'tryon preview generated', 'sent')")
            conn.commit()
        except Exception:
            pass
    return tid, out


def _parse_image_response(r) -> bytes:
    ctype = r.headers.get("content-type", "")
    if ctype.startswith("image/"):
        return r.content
    try:
        data = r.json()
    except ValueError:
        raise TryonError(f"image service error {r.status_code}")
    imgs = (data.get("data") or []) if isinstance(data, dict) else []
    if not imgs:
        raise TryonError(str(data)[:200] if isinstance(data, dict) and data.get("error")
                         else "image service returned no image")
    first = imgs[0]
    if first.get("b64_json"):
        import base64
        return base64.b64decode(first["b64_json"])
    if first.get("url"):
        import httpx
        d = httpx.get(first["url"], timeout=60)
        d.raise_for_status()
        return d.content
    raise TryonError("unrecognised image response")


def tryon_get(tid: str) -> bytes | None:
    item = _tryon_hold.get(tid)
    if not item:
        return None
    out, exp = item
    if exp < time.time():
        del _tryon_hold[tid]
        return None
    return out


def tryon_ratelimited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _tryon_ips.get(ip, []) if t > now - 3600]
    if len(hits) >= 10:
        return True
    hits.append(now)
    _tryon_ips[ip] = hits
    return False


def selfcheck() -> None:
    """Offline: orders, transitions, wrong-phone rejection, OTP gates. No network."""
    import tempfile
    tmp = tempfile.mkdtemp()
    db.DB_PATH = db.Path(tmp) / "t.db"
    db.init_db()
    ensure_tables()
    with db.connect() as conn:
        conn.execute("INSERT INTO businesses (slug, name, wa_display_number) VALUES (?,?,?)",
                     ("escape", "ESCAPE", "15550001111"))
        conn.execute("INSERT INTO products (business_id, slug, name, price_paise, image)"
                     " VALUES (1,'tee','Tee',99900,'tee.jpg')")
        conn.execute("INSERT INTO products (business_id, slug, name, price_paise)"
                     " VALUES (1,'hood','Hoodie',199900)")
        conn.commit()
    assert len(list_products("escape")) == 2
    for kw in ({"phone": "123"}, {"name": "A", "address": "short"}, {"items": []}):
        args = {"items": [{"product_id": 1, "qty": 1}], "name": "Ab",
                "phone": "+911234567890", "address": "12 Main St, Kochi",
                "call_consent": True}
        args.update(kw)
        try:
            create_order("escape", **args)
            raise AssertionError(f"accepted {kw}")
        except ValueError:
            pass
    try:
        create_order("escape", [{"product_id": 1, "qty": 1}], "Ab", "+911234567890",
                     "12 Main St, Kochi", False)
        raise AssertionError("no-consent accepted")
    except ValueError:
        pass
    o = create_order("escape", [{"product_id": 1, "qty": 2, "size": "L"},
                                {"product_id": 2, "qty": 1}],
                     "Asha", "+911234567890", "12 Main St, Kochi", True)
    assert o["total"] == inr(99900 * 2 + 199900), o
    assert o["whatsapp"].endswith("text=ORDER%201"), o
    assert get_order_public("escape", o["id"], "+911234567890")["status"] == "pending_call"
    assert get_order_public("escape", o["id"], "+911234567891") is None  # wrong phone: nothing
    assert order_action(1, o["id"], "+911234567890", "confirmed")["status"] == "confirmed"
    assert order_action(1, o["id"], "+911234567890", "confirmed")["error"] == "bad_transition"
    assert order_action(1, o["id"], "+911234567890", "cancelled")["status"] == "cancelled"
    o2 = create_order("escape", [{"product_id": 1, "qty": 1}], "Dev", "+919876543210",
                      "9 Cross St, Kochi", True)
    assert remind_pending() == 0, "fresh order must not be reminded"
    assert get_order(1, o2["id"])["status"] == "pending_call"
    with db.connect() as conn:
        conn.execute("UPDATE orders SET created_at = datetime('now', '-31 minutes')"
                     " WHERE id = ?", (o2["id"],))
        conn.commit()
    assert remind_pending() == 1
    assert get_order(1, o2["id"])["status"] == "needs_followup"
    assert remind_pending() == 0, "reminded once only"
    try:
        import auth as _auth  # noqa: F401 (argon2 missing on bare machines)
        _otp_live = True
    except ImportError:
        _otp_live = False
    if _otp_live:
        import auth
        # correct code, then single use
        create_order("escape", [{"product_id": 1, "qty": 1}], "Oa", "+915555555551",
                     "1 A St, Kochi", True)
        with db.connect() as conn:
            conn.execute("INSERT INTO otps (business_id, phone, code_hash, expires_at)"
                         " VALUES (1,?,?,?)",
                         (digits("+915555555551"), auth.hash_password("123456"),
                          outbound.utc_sqlite(-5 / 60)))
            conn.commit()
        assert verify_otp(1, "+915555555551", "123456") == (True, "ok")
        assert verify_otp(1, "+915555555551", "123456") == (False, "no_code")
        # 3 wrong attempts lock the code, even the right one
        create_order("escape", [{"product_id": 1, "qty": 1}], "Ob", "+915555555552",
                     "2 B St, Kochi", True)
        with db.connect() as conn:
            conn.execute("INSERT INTO otps (business_id, phone, code_hash, expires_at)"
                         " VALUES (1,?,?,?)",
                         (digits("+915555555552"), auth.hash_password("999999"),
                          outbound.utc_sqlite(-5 / 60)))
            conn.commit()
        for _ in range(3):
            assert verify_otp(1, "+915555555552", "000000") == (False, "bad_code")
        assert verify_otp(1, "+915555555552", "999999") == (False, "locked")
        # expired code
        create_order("escape", [{"product_id": 1, "qty": 1}], "Oc", "+915555555553",
                     "3 C St, Kochi", True)
        with db.connect() as conn:
            conn.execute("INSERT INTO otps (business_id, phone, code_hash, expires_at)"
                         " VALUES (1,?,?,?)",
                         (digits("+915555555553"), auth.hash_password("111111"),
                          outbound.utc_sqlite(1)))
            conn.commit()
        assert verify_otp(1, "+915555555553", "111111") == (False, "expired")
        # 4th send in an hour blocked
        create_order("escape", [{"product_id": 1, "qty": 1}], "Od", "+915555555554",
                     "4 D St, Kochi", True)
        for _ in range(3):
            request_otp(1, "+915555555554")
        assert request_otp(1, "+915555555554") == {"sent": False, "message": OTP_MSG}
    else:
        print("store selfcheck: OTP positive tests skipped here (no argon2); VPS runs them")
    # OTP: unknown number gets the same message, no row
    m1 = request_otp(1, "+910000000000")
    assert m1["message"] == OTP_MSG and m1["sent"] is False
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM otps").fetchone()[0] == 0
    ok, _ = verify_otp(1, "+910000000000", "123456")
    assert (ok, _) == (False, "no_code")
    print("store selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python store.py selfcheck")
