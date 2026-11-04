"""Purchases: Picker (plain rule), Buyer (price/seller-change rejection), Tracker.

Safety: an order is sent only after a logged-in click on the confirmation
screen, and only to an opted-in seller. Seller text is untrusted: it can only
fill parsed fields or flip a purchase through the fixed transitions below.
"""
import re

import db

STATUSES = ("draft", "order_sent", "seller_confirmed", "seller_declined",
            "shipped", "delivered", "cancelled", "needs_attention")

TRANSITIONS = {
    "draft": ("order_sent", "cancelled"),
    "order_sent": ("seller_confirmed", "seller_declined", "cancelled"),
    "seller_confirmed": ("shipped", "delivered", "cancelled", "needs_attention"),
    "shipped": ("delivered", "needs_attention"),
    "needs_attention": ("seller_confirmed", "shipped", "delivered", "cancelled"),
    "seller_declined": (),
    "delivered": (),
    "cancelled": (),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  hunt_id INTEGER DEFAULT 0, listing_id INTEGER DEFAULT 0, seller_id INTEGER DEFAULT 0,
  item TEXT DEFAULT '', price REAL, unit TEXT DEFAULT '', seller_name TEXT DEFAULT '',
  delivery_option TEXT DEFAULT '', delivery_reason TEXT DEFAULT '',
  status TEXT DEFAULT 'draft',
  courier TEXT DEFAULT '', tracking_number TEXT DEFAULT '', tracking_link TEXT DEFAULT '',
  reminders INTEGER DEFAULT 0, track_checked_at TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS purchase_events (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  purchase_id INTEGER NOT NULL REFERENCES purchases(id),
  at TEXT DEFAULT (datetime('now')), status TEXT DEFAULT '', note TEXT DEFAULT ''
);
"""


def init_db() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def set_status(bid: int, pid: int, new: str, note: str = "") -> dict:
    """Move a purchase through TRANSITIONS only, logging a timeline event."""
    if new not in STATUSES:
        raise ValueError(f"unknown status {new}")
    with db.connect() as conn:
        p = conn.execute("SELECT * FROM purchases WHERE id = ? AND business_id = ?",
                         (pid, bid)).fetchone()
        if not p:
            raise ValueError("no purchase")
        if new != p["status"] and new not in TRANSITIONS[p["status"]]:
            raise ValueError(f"cannot go from {p['status']} to {new}")
        conn.execute("UPDATE purchases SET status = ?, updated_at = datetime('now')"
                     " WHERE id = ?", (new, pid))
        conn.execute("INSERT INTO purchase_events (business_id, purchase_id, status, note)"
                     " VALUES (?, ?, ?, ?)", (bid, pid, new, note[:500]))
        conn.commit()
        return dict(conn.execute("SELECT * FROM purchases WHERE id = ?", (pid,)).fetchone())


def _days(text: str) -> int | None:
    """First integer in a delivery-days string; None when there is none."""
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else None


def delivery_options(bid: int, listing_id: int) -> list:
    """Options from the verified page text plus any quoted delivery days."""
    with db.connect() as conn:
        li = conn.execute("SELECT * FROM listings WHERE id = ? AND business_id = ?",
                          (listing_id, bid)).fetchone()
        if not li:
            raise ValueError("no listing")
        li = dict(li)
        quotes = conn.execute(
            "SELECT delivery_days FROM quotes WHERE business_id = ?"
            " AND hunt_item_id = ? AND seller_id = ? AND delivery_days != ''",
            (bid, li["hunt_item_id"] or 0, li["seller_id"] or 0)).fetchall()
    opts = [{"label": li["delivery"] or "as listed",
             "price": li["price"], "days": None}]
    for q in quotes:
        d = _days(q["delivery_days"])
        if d is not None:
            opts.append({"label": f"seller quoted: {q['delivery_days']}",
                         "price": li["price"], "days": d})
    return opts


def pick_delivery(options: list, pref: str, by_date: str = "") -> tuple:
    """Plain rule, no model. Returns (option|None, reason)."""
    if not options:
        # shortcut: nothing to pick from; ask the seller, never guess
        return None, "no delivery options: ask the seller, not guessing"
    if pref == "fastest":
        known = [o for o in options if o["days"] is not None]
        pool = known or options
        best = min(pool, key=lambda o: o["days"] if o["days"] is not None else 10**9)
        return best, "fastest quoted delivery"
    if pref == "by_date" and by_date:
        from datetime import date
        try:
            limit = date.fromisoformat(by_date)
            days_left = (limit - date.today()).days
        except ValueError:
            return None, f"bad arrive-by date {by_date}"
        ok = [o for o in options
              if o["days"] is not None and o["days"] <= days_left]
        if not ok:
            return None, f"nothing arrives by {by_date}: ask the seller"
        priced = [o for o in ok if o["price"] is not None]
        best = min(priced or ok, key=lambda o: o["price"] if o["price"] is not None else 10**18)
        return best, f"cheapest arriving by {by_date}"
    # cheapest (default)
    priced = [o for o in options if o["price"] is not None]
    if not priced:
        return options[0], "only option"
    return min(priced, key=lambda o: o["price"]), "cheapest"


def delivery_pick(bid: int, listing_id: int) -> dict:
    """Preference comes from Setup; returns options + pick + reason."""
    with db.connect() as conn:
        biz = conn.execute("SELECT delivery_pref, delivery_date FROM businesses"
                           " WHERE id = ?", (bid,)).fetchone()
    pref = (biz["delivery_pref"] if biz and biz["delivery_pref"] else "cheapest")
    by_date = (biz["delivery_date"] if biz and biz["delivery_date"] else "")
    options = delivery_options(bid, listing_id)
    pick, reason = pick_delivery(options, pref, by_date)
    return {"options": options, "pick": pick, "reason": reason, "pref": pref}


def _send_logged(bid: int, seller, hid: int, listing_id: int,
                 template: str, params: list, text: str) -> dict:
    """Same fallback shape as stock checks: template, 24h free-form, waiting."""
    import outbound
    import sellers
    try:
        outbound.send_template(sellers.digits(seller["phone"]), template, "en", params)
        sellers._log(bid, seller["id"], hid, listing_id, "out", template,
                     text, status="sent")
        return {"sent": "template"}
    except Exception as e:
        if "template" not in str(e).lower() and "approv" not in str(e).lower():
            sellers._log(bid, seller["id"], hid, listing_id, "out", template,
                         text, status="failed", error=str(e))
            raise ValueError(f"send failed: {e}")
    with db.connect() as conn:
        recent = conn.execute(
            "SELECT id FROM seller_messages WHERE business_id = ? AND seller_id = ?"
            " AND direction = 'in' AND created_at > datetime('now', '-1 day')",
            (bid, seller["id"])).fetchone()
    if recent:
        outbound.send_text(sellers.digits(seller["phone"]), text)
        sellers._log(bid, seller["id"], hid, listing_id, "out", "", text, status="sent")
        return {"sent": "free-form (24h window)"}
    sellers._log(bid, seller["id"], hid, listing_id, "out", template, text,
                 status="waiting", error="template waiting for approval")
    return {"sent": "none",
            "note": "Template waiting for approval",
            "ask_from_whatsapp": sellers.wa_me_link(seller["phone"], text)}


def create_purchase(bid: int, uid: int, listing_id: int, price_seen,
                    seller_seen: int, delivery_option: str, payment: str = "") -> dict:
    """Buyer: rejects when the price or seller changed since the screen shown."""
    import sellers
    with db.connect() as conn:
        li = conn.execute("SELECT * FROM listings WHERE id = ? AND business_id = ?",
                          (listing_id, bid)).fetchone()
        if not li:
            raise ValueError("no listing")
        li = dict(li)
    try:
        seen = float(price_seen) if price_seen not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("price changed since you saw it")
    if (li["price"] is None) != (seen is None) or (
            li["price"] is not None and float(li["price"]) != seen):
        raise ValueError("price changed since you saw it")
    sid = li["seller_id"] or seller_seen or 0
    if li["seller_id"] and seller_seen and int(li["seller_id"]) != int(seller_seen):
        raise ValueError("seller changed since you saw it")
    with db.connect() as conn:
        s = conn.execute("SELECT * FROM sellers WHERE id = ? AND business_id = ?",
                         (sid, bid)).fetchone() if sid else None
        s = dict(s) if s else None
        biz = conn.execute("SELECT delivery_name, delivery_address, delivery_phone"
                           " FROM businesses WHERE id = ?", (bid,)).fetchone()
        cur = conn.execute(
            "INSERT INTO purchases (business_id, hunt_id, listing_id, seller_id,"
            " item, price, unit, seller_name, delivery_option, delivery_reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')",
            (bid, li["hunt_id"], listing_id, sid, li["title"][:200], li["price"],
             li["unit"] or "", (s["name"] if s else li["seller"])[:120],
             str(delivery_option or "")[:200]))
        pid = cur.lastrowid
        conn.execute("INSERT INTO purchase_events (business_id, purchase_id, status, note)"
                     " VALUES (?, ?, 'draft', ?)",
                     (bid, pid, f"created from confirmation screen (pay: {payment or 'cod'}"))
        conn.commit()
    if not s or not s["opted_in"]:
        import sellers as _s
        text = (f"Hello {s['name'] if s else li['seller']}, we would like to order"
                f" {li['title'][:80]}.")
        return {"purchase_id": pid, "sent": "none",
                "note": "Seller has not opted in: order from your own WhatsApp.",
                "ask_from_whatsapp": _s.wa_me_link(
                    s["phone"] if s else "", text) if s else ""}
    buyer = f"{biz['delivery_name']}, {biz['delivery_address']}, {biz['delivery_phone']}" \
        if biz else ""
    params = [sellers.clean_param(x) for x in
              (s["name"], li["title"][:200], str(li["price"] or "quote"),
               str(delivery_option or "-")[:200], buyer[:200])]
    text = (f"Hello {s['name']}, order request for {li['title'][:80]}"
            f" at {li['price']} ({delivery_option}). Deliver to: {buyer}."
            f" Payment: {'cash on delivery' if (payment or 'cod') == 'cod' else 'paying you directly'}")
    try:
        r = _send_logged(bid, s, li["hunt_item_id"] or li["hunt_id"],
                         listing_id, "order_request", params, text)
    except ValueError as e:
        return {"purchase_id": pid, "sent": "none", "note": str(e)}
    if r["sent"] != "none":
        set_status(bid, pid, "order_sent", f"order_request via {r['sent']}")
    else:
        with db.connect() as conn:
            conn.execute("INSERT INTO purchase_events (business_id, purchase_id,"
                         " status, note) VALUES (?, ?, 'draft', ?)",
                         (bid, pid, r.get("note", "waiting")[:500]))
            conn.commit()
    r["purchase_id"] = pid
    return r


def ask_update(bid: int, pid: int) -> dict:
    """Ask-for-update: confirmed orders with no tracking, at most 1/day/seller."""
    with db.connect() as conn:
        p = conn.execute("SELECT * FROM purchases WHERE id = ? AND business_id = ?",
                         (pid, bid)).fetchone()
        if not p:
            raise ValueError("no purchase")
        p = dict(p)
        if p["status"] not in ("seller_confirmed", "shipped"):
            raise ValueError("only confirmed orders can be chased")
        if p["tracking_number"]:
            raise ValueError("already has a tracking number")
        s = conn.execute("SELECT * FROM sellers WHERE id = ?", (p["seller_id"],)).fetchone()
        if not s:
            raise ValueError("no seller")
        s = dict(s)
        today = conn.execute(
            "SELECT id FROM seller_messages WHERE business_id = ? AND seller_id = ?"
            " AND listing_id = ? AND direction = 'out' AND template = 'tracking_request'"
            " AND created_at > datetime('now', '-1 day')",
            (bid, s["id"], p["listing_id"])).fetchone()
        if today:
            raise ValueError("already asked today")
    params = [s["name"][:200], p["item"][:200], str(p["id"])]
    text = (f"Hello {s['name']}, any update on order #{p['id']} ({p['item'][:60]})?"
            " Please share the courier and tracking number.")
    r = _send_logged(bid, s, p["hunt_id"], p["listing_id"],
                     "tracking_request", params, text)
    if r["sent"] != "none":
        with db.connect() as conn:
            conn.execute("UPDATE purchases SET reminders = reminders + 1 WHERE id = ?",
                         (pid,))
            conn.execute("INSERT INTO purchase_events (business_id, purchase_id,"
                         " status, note) VALUES (?, ?, ?, ?)",
                         (bid, pid, p["status"], f"tracking asked ({r['sent']})"))
            conn.commit()
    r["purchase_id"] = pid
    return r


def tracker_tick() -> dict:
    """6-hour check: chase confirmed orders with no tracking; 3 misses need eyes."""
    done = {"asked": 0, "needs_attention": 0}
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM purchases WHERE status IN ('seller_confirmed', 'shipped')"
            " AND (tracking_number IS NULL OR tracking_number = '')"
            " AND (track_checked_at IS NULL OR track_checked_at = ''"
            " OR track_checked_at < datetime('now', '-6 hours'))").fetchall()
        rows = [dict(r) for r in rows]
    for p in rows:
        with db.connect() as conn:
            conn.execute("UPDATE purchases SET track_checked_at = datetime('now')"
                         " WHERE id = ?", (p["id"],))
            conn.commit()
        if p["reminders"] >= 3:
            try:
                set_status(p["business_id"], p["id"], "needs_attention",
                           "3 unanswered tracking reminders")
                done["needs_attention"] += 1
            except ValueError:
                pass
            continue
        try:
            r = ask_update(p["business_id"], p["id"])
            if r["sent"] != "none":
                done["asked"] += 1
        except ValueError:
            pass  # already asked today, or send fell back: retry next tick
    return done


TRACK_NO = re.compile(r"(?:tracking|track|awb|lr|docket|consign)[^\dA-Za-z]{0,10}"
                      r"([A-Za-z0-9][A-Za-z0-9-]{5,29})", re.IGNORECASE)
COURIER = re.compile(r"(?:courier|shipped via|shipped through|via)\s+([A-Za-z][A-Za-z .]{1,29})",
                     re.IGNORECASE)
LINK = re.compile(r"(https://\S+)", re.IGNORECASE)
CONFIRM = re.compile(r"confirm(?:ed|ing|s)?\s+(?:the\s+)?order|order\s+confirm|"
                     r"^confirmed$|i\s+confirm", re.IGNORECASE)
DECLINE = re.compile(r"decline[sd]?|cancel(?:led|ling|s)?\s+(?:the\s+)?order|"
                     r"cannot?\s+suppl|cannot (?:do|fulfil)|no\s+stock", re.IGNORECASE)


def open_for_seller(bid: int, seller_id: int):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM purchases WHERE business_id = ? AND seller_id = ?"
            " AND status IN ('order_sent','seller_confirmed','shipped','needs_attention')"
            " ORDER BY id DESC", (bid, seller_id)).fetchall()]


def record_seller_decision(bid: int, seller_id: int, decision: str) -> dict | None:
    """Confirm/decline from a button or text. Only ever touches open purchases."""
    if decision not in ("seller_confirmed", "seller_declined"):
        raise ValueError("bad decision")
    for p in open_for_seller(bid, seller_id):
        if p["status"] != "order_sent":
            continue
        return set_status(bid, p["id"], decision, f"seller said {decision}")
    return None


def apply_seller_text(bid: int, seller_id: int, body: str) -> str | None:
    """Tracking/confirm/delivered notes from free text. Returns what it did."""
    t = (body or "").strip()
    if not t:
        return None
    if CONFIRM.search(t):
        if record_seller_decision(bid, seller_id, "seller_confirmed"):
            return "confirmed"
        return None
    if DECLINE.search(t):
        if record_seller_decision(bid, seller_id, "seller_declined"):
            return "declined"
        return None
    found = []
    m = TRACK_NO.search(t)
    link = next((u for u in LINK.findall(t)
                 if u.lower().startswith("https://")), "")
    c = COURIER.search(t)
    handled = None
    for p in open_for_seller(bid, seller_id):
        with db.connect() as conn:
            if m and not p["tracking_number"]:
                conn.execute("UPDATE purchases SET tracking_number = ? WHERE id = ?",
                             (m.group(1)[:40], p["id"]))
                found.append(f"tracking {m.group(1)[:40]}")
            if link and not p["tracking_link"]:
                conn.execute("UPDATE purchases SET tracking_link = ? WHERE id = ?",
                             (link[:300], p["id"]))
                found.append("tracking link")
            if c and not p["courier"]:
                conn.execute("UPDATE purchases SET courier = ? WHERE id = ?",
                             (c.group(1).strip()[:60], p["id"]))
                found.append(f"courier {c.group(1).strip()[:60]}")
            if found:
                conn.execute("INSERT INTO purchase_events (business_id, purchase_id,"
                             " status, note) VALUES (?, ?, ?, ?)",
                             (bid, p["id"], p["status"], f"seller said: {t[:200]}"))
                conn.commit()
        if found:
            handled = "tracking"
            break
    if handled:
        return handled
    if re.search(r"\bdeliver(?:ed|y done)\b", t, re.IGNORECASE):
        for p in open_for_seller(bid, seller_id):
            with db.connect() as conn:
                conn.execute("INSERT INTO purchase_events (business_id, purchase_id,"
                             " status, note) VALUES (?, ?, ?, ?)",
                             (bid, p["id"], p["status"],
                              f"seller says delivered — confirm below: {t[:200]}"))
                conn.commit()
            return "delivered-noted"
    return None


def routes(app, *, require_api_key, need_login, api_error) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    def one(bid, pid):
        with db.connect() as conn:
            p = conn.execute("SELECT * FROM purchases WHERE id = ? AND business_id = ?",
                             (pid, bid)).fetchone()
            if not p:
                return None
            p = dict(p)
            p["events"] = [dict(r) for r in conn.execute(
                "SELECT * FROM purchase_events WHERE purchase_id = ? ORDER BY id",
                (pid,)).fetchall()]
            return p

    @app.get("/api/purchases")
    async def list_purchases(request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM purchases WHERE business_id = ?"
                                " ORDER BY id DESC", (u["business_id"],)).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/purchases/{pid}")
    async def get_purchase(pid: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        p = one(u["business_id"], pid)
        if not p:
            return api_error("not_found", "no purchase", 404)
        return p

    @app.post("/api/purchases", status_code=201)
    async def buyer(request: Request):
        """Logged-in click on the confirmation screen. Rejects stale values."""
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return api_error("invalid", "bad json", 422)
        try:
            return JSONResponse(create_purchase(
                u["business_id"], u["id"], body.get("listing_id"),
                body.get("price"), body.get("seller_id"),
                body.get("delivery_option") or "",
                str(body.get("payment") or "")[:20]), status_code=201)
        except ValueError as e:
            return api_error("rejected", str(e), 409)

    @app.get("/api/listings/{listing_id}/delivery-pick")
    async def pick(listing_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            return delivery_pick(u["business_id"], listing_id)
        except ValueError as e:
            return api_error("not_found", str(e), 404)

    @app.patch("/api/purchases/{pid}")
    async def edit_purchase(pid: int, request: Request):
        """User moves: cancel, mark delivered, or change the delivery option."""
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return api_error("invalid", "bad json", 422)
        try:
            if "status" in body:
                if body["status"] not in ("cancelled", "delivered"):
                    return api_error("invalid", "users can only cancel or mark delivered", 422)
                return set_status(u["business_id"], pid, body["status"],
                                  str(body.get("note") or "")[:500])
            if "delivery_option" in body:
                with db.connect() as conn:
                    p = conn.execute("SELECT status FROM purchases WHERE id = ?"
                                     " AND business_id = ?", (pid, u["business_id"])).fetchone()
                    if not p:
                        return api_error("not_found", "no purchase", 404)
                    if p["status"] != "draft":
                        return api_error("rejected", "order already sent", 409)
                    conn.execute("UPDATE purchases SET delivery_option = ? WHERE id = ?",
                                 (str(body["delivery_option"])[:200], pid))
                    conn.execute("INSERT INTO purchase_events (business_id, purchase_id,"
                                 " status, note) VALUES (?, ?, 'draft', ?)",
                                 (u["business_id"], pid, "delivery changed by user"))
                    conn.commit()
                return one(u["business_id"], pid)
            return api_error("invalid", "nothing to change", 422)
        except ValueError as e:
            return api_error("rejected", str(e), 409)

    @app.post("/api/purchases/{pid}/ask-update")
    async def ask(pid: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            return ask_update(u["business_id"], pid)
        except ValueError as e:
            return api_error("rejected", str(e), 409)


# ---- selfcheck: offline, WhatsApp stubbed ----

def selfcheck() -> None:
    """Stubbed sends. A skipped check counts as failed: no skips here."""
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmp) / "t.db"
    calls = []
    try:
        import hunt
        import sellers
        db.init_db()
        hunt.init_db()
        sellers.init_db()
        init_db()
        # business delivery columns land via db migration below
        for c in ("delivery_name", "delivery_address", "delivery_phone",
                  "delivery_pref", "delivery_date", "country"):
            with db.connect() as conn:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(businesses)")]
                if c not in cols:
                    conn.execute(f"ALTER TABLE businesses ADD COLUMN {c} TEXT DEFAULT ''")
                conn.commit()
        with db.connect() as conn:
            conn.execute("INSERT INTO businesses (slug, name, delivery_name,"
                         " delivery_address, delivery_phone, delivery_pref)"
                         " VALUES ('a','A','Buyer','Addr','91111','cheapest')")
            conn.execute("INSERT INTO hunts (business_id, status) VALUES (1,'done')")
            conn.execute("INSERT INTO hunt_items (hunt_id, name) VALUES (1,'Tee')")
            conn.execute("INSERT INTO listings (hunt_id, hunt_item_id, business_id,"
                         " url, title, price, delivery) VALUES (1,1,1,'https://s/x',"
                         " 'Tee', 100.0, '3 days')")
            conn.execute("INSERT INTO sellers (business_id, name, phone, opted_in)"
                         " VALUES (1,'Yes','91222',1)")
            conn.execute("UPDATE listings SET seller_id = 1 WHERE id = 1")
            conn.commit()

        import outbound
        outbound.send_template = lambda to, n, l, p: calls.append(("t", to, n)) or {}
        outbound.send_text = lambda to, t: calls.append(("x", to)) or {}

        # 1. status rules: bad name and bad jump both refuse
        p = create_purchase(1, 1, 1, 100.0, 1, "as listed")
        pid = p["purchase_id"]
        assert p["sent"] == "template", p
        for bad in ("bogus", "delivered"):
            try:
                set_status(1, pid, bad, "")
            except ValueError:
                pass
            else:
                raise AssertionError(f"allowed {bad}")
        set_status(1, pid, "seller_confirmed", "seller confirmed")
        # timeline kept the trail
        with db.connect() as conn:
            evs = conn.execute("SELECT status FROM purchase_events WHERE purchase_id = ?"
                               " ORDER BY id", (pid,)).fetchall()
        assert [e["status"] for e in evs] == ["draft", "order_sent", "seller_confirmed"], evs

        # 2. price changed since the screen: rejected, no send
        n0 = len(calls)
        try:
            create_purchase(1, 1, 1, 120.0, 1, "as listed")
        except ValueError as e:
            assert "price changed" in str(e), e
        else:
            raise AssertionError("stale price accepted")
        assert len(calls) == n0, calls

        # 3. seller changed: rejected
        with db.connect() as conn:
            conn.execute("INSERT INTO sellers (business_id, name, phone, opted_in)"
                         " VALUES (1,'Other','91333',1)")
            conn.commit()
        try:
            create_purchase(1, 1, 1, 100.0, 2, "as listed")
        except ValueError as e:
            assert "seller changed" in str(e), e
        else:
            raise AssertionError("stale seller accepted")

        # 4. Picker: cheapest / fastest / by-date / none
        opts = [{"label": "a", "price": 90.0, "days": 5},
                {"label": "b", "price": 100.0, "days": 2}]
        assert pick_delivery(opts, "cheapest")[0]["label"] == "a"
        assert pick_delivery(opts, "fastest")[0]["label"] == "b"
        from datetime import date, timedelta
        soon = (date.today() + timedelta(days=3)).isoformat()
        got, why = pick_delivery(opts, "by_date", soon)
        assert got["label"] == "b", (got, why)
        assert pick_delivery([], "cheapest")[0] is None
        dp = delivery_pick(1, 1)
        assert dp["pick"] and dp["reason"] == "cheapest", dp

        # 5. reminders: 1/day cap, 3 misses need eyes
        r = ask_update(1, pid)
        assert r["sent"] == "template", r
        try:
            ask_update(1, pid)
        except ValueError as e:
            assert "today" in str(e), e
        else:
            raise AssertionError("double ask allowed")
        with db.connect() as conn:  # two more days pass, still nothing
            conn.execute("UPDATE seller_messages SET created_at = datetime('now','-2 days')"
                         " WHERE template = 'tracking_request'")
            conn.execute("UPDATE purchases SET reminders = 3,"
                         " track_checked_at = datetime('now','-7 hours') WHERE id = ?", (pid,))
            conn.commit()
        tick = tracker_tick()
        assert tick["needs_attention"] == 1, tick
        with db.connect() as conn:
            st = conn.execute("SELECT status FROM purchases WHERE id = ?", (pid,)).fetchone()
        assert st["status"] == "needs_attention", dict(st)

        # 6. seller text: tracking + link saved, delivered only noted
        with db.connect() as conn:
            cur = conn.execute("INSERT INTO purchases (business_id, listing_id, seller_id,"
                               " item, price, status) VALUES (1,1,1,'Tee',100,'seller_confirmed')")
            conn.commit()
            pid2 = cur.lastrowid
        assert apply_seller_text(1, 1, "Shipped via Delhivery, tracking 123456789, "
                                 "https://track.example/123456789") == "tracking"
        with db.connect() as conn:
            row = conn.execute("SELECT courier, tracking_number, tracking_link FROM purchases"
                               " WHERE id = ?", (pid2,)).fetchone()
        assert row["tracking_number"] == "123456789", dict(row)
        assert row["tracking_link"].startswith("https://"), dict(row)
        assert apply_seller_text(1, 1, "delivered") == "delivered-noted"
        with db.connect() as conn:
            st = conn.execute("SELECT status FROM purchases WHERE id = ?", (pid2,)).fetchone()
        assert st["status"] == "seller_confirmed", dict(st)  # user confirms, not the seller
        with db.connect() as conn:
            conn.execute("INSERT INTO purchases (business_id, listing_id, seller_id,"
                         " item, price, status) VALUES (1,1,1,'Tee',100,'order_sent')")
            conn.commit()
        assert apply_seller_text(1, 1, "please confirm the order") == "confirmed"
        print("purchases selfcheck: OK")
    finally:
        db.DB_PATH = old
