"""Vendor search for approved construction BOQs. Shared Finder/Checker.

Runs only after the approval gate (house.require_approval): the user picks
which BOQ items to source (max 10), each gets Finder + Checker with the
construction profile. Limits per hunt: 20 searches, 8 vendors per item.
City goes in the query and in user_location. Blocked pages are marked
"Couldn't check" and counted, never bypassed.
"""
import json

import db
import house

MAX_ITEMS = 10
MAX_SEARCHES = 20
VENDORS_PER_ITEM = 8


def _intake(hunt_id: int) -> dict:
    with db.connect() as conn:
        h = conn.execute("SELECT spot FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
    try:
        return json.loads(h["spot"] or "{}") if h else {}
    except ValueError:
        return {}


def search_vendors(bid: int, hid: int, item_ids: list[int] | None = None) -> dict:
    """Finder + Checker per BOQ item. Returns per-item vendor/blocked counts."""
    import hunt
    house.require_approval(bid, hid)  # raises unless BOQ+image still approved
    with db.connect() as conn:
        h = conn.execute("SELECT searches_used FROM hunts WHERE id = ?"
                         " AND business_id = ?", (hid, bid)).fetchone()
        if not h:
            raise ValueError("unknown hunt")
        used = h["searches_used"] or 0
        q = ("SELECT id, name, spec, quantity, unit FROM hunt_items"
             " WHERE hunt_id = ? AND status = 'boq' ORDER BY id")
        items = [dict(r) for r in conn.execute(q, (hid,)).fetchall()]
    if item_ids:
        wanted = set(item_ids)
        items = [i for i in items if i["id"] in wanted]
        if len(items) != len(wanted):
            raise ValueError("unknown BOQ item picked")
    if not items:
        raise ValueError("no BOQ items to source")
    items = items[:MAX_ITEMS]
    remaining = MAX_SEARCHES - used
    if remaining <= 0:
        raise ValueError("search limit reached for this hunt (20)")
    intake = _intake(hid)
    city = str(intake.get("city") or "").strip()
    summary = []
    for it in items:
        per = min(3, max(1, remaining // len(items)))
        try:
            spec = json.loads(it["spec"] or "{}").get("spec", "")
        except ValueError:
            spec = ""
        base = f"{it['name']} {spec}".strip()
        queries = [f"{base} price {city} India buy".strip(),
                   f"{base} dealer {city} rate".strip()][:per]
        hunt.step(hid, "Finder", "running", f"{it['name']}: searching")
        found, usages, searches = hunt.find_listings(
            queries, country="IN", city=city,
            max_n=VENDORS_PER_ITEM, max_searches=per)
        for u in usages:
            hunt.add_usage(hid, u["in"], u["out"])
        remaining -= searches
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET searches_used = searches_used + ?"
                         " WHERE id = ?", (searches, hid))
            seen_urls = {r[0] for r in conn.execute(
                "SELECT url FROM listings WHERE hunt_id = ?", (hid,))}
            conn.commit()
        hunt.step(hid, "Finder", "done",
                  f"{it['name']}: {len(found)} candidates")
        hunt.step(hid, "Checker", "running", it["name"])
        priced, blocked = 0, 0
        rows = []
        for c in found:
            if c["url"] in seen_urls:
                continue
            seen_urls.add(c["url"])
            info = hunt.check_listing(c["url"], hunt.PROFILES["construction"])
            if (info.get("note") or "").startswith("Couldn't check"):
                blocked += 1
            elif info.get("price") is not None:
                priced += 1
            info["item_id"] = it["id"]
            rows.append(info)
        stored = _store(bid, hid, it, rows, city)
        hunt.step(hid, "Checker", "done",
                  f"{it['name']}: {priced} priced, {blocked} blocked")
        r = hunt.rank({"quantity": it["quantity"], "unit": it["unit"],
                       "city": city}, stored)
        best = r.get("best") or {}
        hunt.step(hid, "Ranker", "done",
                  f"{it['name']}: {r['reasons'].get('best', 'no verified price')}")
        summary.append({"item": it["name"], "vendors": len(stored),
                        "priced": priced, "blocked": blocked,
                        "best_price": best.get("price"),
                        "best_seller": best.get("seller", "")})
        if remaining <= 0:
            break
    with db.connect() as conn:
        left = conn.execute("SELECT searches_used FROM hunts WHERE id = ?",
                            (hid,)).fetchone()[0]
    return {"items": summary, "searches_left": max(0, MAX_SEARCHES - left)}


def _store(bid: int, hid: int, item: dict, rows: list[dict],
           city: str) -> list[dict]:
    """Save listings; link (never message) vendors whose phone is on the page."""
    import sellers
    out = []
    with db.connect() as conn:
        for c in rows:
            sid = None
            phone = sellers.digits(c.get("whatsapp") or "")
            if phone:
                s = conn.execute("SELECT id, opted_in FROM sellers WHERE"
                                 " business_id = ? AND phone = ?",
                                 (bid, phone)).fetchone()
                if s:
                    sid = s["id"]
                else:
                    cur = conn.execute(
                        "INSERT INTO sellers (business_id, name, phone, kind)"
                        " VALUES (?, ?, ?, 'vendor')",
                        (bid, (c.get("seller") or "")[:120], phone))
                    sid = cur.lastrowid
            verified = 1 if c.get("price") is not None and not (
                c.get("note") or "").startswith("Couldn't check") else 0
            cur = conn.execute(
                """INSERT INTO listings (hunt_id, hunt_item_id, business_id,
                   seller_id, url, title, seller, price, currency, unit, city,
                   in_stock, delivery, image_url, whatsapp, verified, verify_note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (hid, item["id"], bid, sid, c.get("url", ""),
                 (c.get("title") or "")[:200], (c.get("seller") or "")[:120],
                 c.get("price"), c.get("currency", ""), item["unit"],
                 (c.get("city") or city)[:120],
                 c.get("in_stock", "unknown"), (c.get("delivery") or "")[:200],
                 c.get("image", ""), phone,
                 verified, (c.get("note") or "")[:200]))
            conn.commit()
            out.append({"id": cur.lastrowid, "price": c.get("price"),
                        "unit": item["unit"], "verified": verified,
                        "seller": c.get("seller") or "",
                        "delivery": c.get("delivery") or "",
                        "in_stock": c.get("in_stock", "unknown")})
    return out


def vendors_of(bid: int, hid: int) -> dict:
    """Listings grouped by BOQ item with live best/cheapest flags."""
    import hunt
    with db.connect() as conn:
        h = conn.execute("SELECT id FROM hunts WHERE id = ? AND business_id = ?",
                         (hid, bid)).fetchone()
        if not h:
            raise ValueError("unknown hunt")
        items = [dict(r) for r in conn.execute(
            "SELECT id, name, quantity, unit FROM hunt_items"
            " WHERE hunt_id = ? AND status = 'boq' ORDER BY id", (hid,))]
        groups = []
        for it in items:
            rows = [dict(r) for r in conn.execute(
                """SELECT l.id, l.url, l.title, l.seller, l.price, l.currency,
                          l.unit, l.city, l.in_stock, l.delivery, l.verified,
                          l.verify_note, l.seller_id, l.whatsapp,
                          s.opted_in AS seller_opted_in
                   FROM listings l LEFT JOIN sellers s ON s.id = l.seller_id
                   WHERE l.hunt_id = ? AND l.hunt_item_id = ? ORDER BY l.id""",
                (hid, it["id"]))]
            r = hunt.rank({"quantity": it["quantity"], "unit": it["unit"],
                           "city": ""}, rows)
            best_id = (r.get("best") or {}).get("id")
            cheap_id = (r.get("cheapest") or {}).get("id")
            for row in rows:
                row["is_best"] = row["id"] == best_id
                row["is_cheapest"] = row["id"] == cheap_id
            blocked = sum(1 for row in rows if (row["verify_note"] or "")
                          .startswith("Couldn't check"))
            groups.append({"item": it["name"], "quantity": it["quantity"],
                           "unit": it["unit"], "listings": rows,
                           "priced": sum(1 for row in rows
                                         if row["price"] is not None),
                           "blocked": blocked,
                           "best_reason": r["reasons"].get("best", "")})
    return {"items": groups}


def run_vendor_search(bid: int, hid: int,
                      item_ids: list[int] | None = None) -> None:
    """Background entry: gate re-checked here, failure lands in hunt_steps."""
    import hunt
    try:
        search_vendors(bid, hid, item_ids)
    except Exception as e:
        hunt.step(hid, "Finder", "failed", str(e)[:500])


def routes(app, *, require_api_key, need_login, api_error) -> None:
    from fastapi import BackgroundTasks, Request
    from fastapi.responses import JSONResponse

    @app.post("/api/hunts/{hunt_id}/vendors")
    async def start_vendor_search(hunt_id: int, request: Request,
                                  background: BackgroundTasks):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        ids = None
        if isinstance(body, dict) and body.get("item_ids"):
            try:
                ids = [int(x) for x in body["item_ids"]][:MAX_ITEMS]
            except (ValueError, TypeError):
                return api_error("invalid", "bad item_ids", 422)
        try:
            house.require_approval(u["business_id"], hunt_id)
        except ValueError as e:
            return api_error("invalid", str(e), 422)
        background.add_task(run_vendor_search, u["business_id"], hunt_id, ids)
        return JSONResponse({"started": True})

    @app.get("/api/hunts/{hunt_id}/vendors")
    async def get_vendors(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            return vendors_of(u["business_id"], hunt_id)
        except ValueError as e:
            return api_error("not_found", str(e), 404)


SAMPLE_HTML = """<html><head>
<meta property="og:title" content="UltraTech Cement 50kg bag">
<meta property="og:price:amount" content="385">
<meta property="og:price:currency" content="INR">
<script type="application/ld+json">{"@context":"https://schema.org",
"@type":"Product","name":"UltraTech Cement 50kg",
"offers":{"@type":"Offer","price":"385","priceCurrency":"INR",
"availability":"https://schema.org/InStock",
"seller":{"@type":"Organization","name":"Sharma Building Mart"}}}
</script></head><body><h1>UltraTech Cement 50kg bag</h1>
<p>Rs. 385 per bag. Call <a href="https://wa.me/919876543210">WhatsApp</a></p>
</body></html>"""


def selfcheck() -> None:
    """Gate, Finder+Checker on saved sample HTML, limits, seller linking."""
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmp) / "t.db"
    real_find = __import__("hunt").find_listings
    real_get = __import__("hunt").polite_get
    try:
        db.init_db()
        import hunt
        import sellers
        hunt.init_db()
        sellers.init_db()
        with db.connect() as conn:
            conn.execute("INSERT INTO businesses (slug, name) VALUES ('a','A')")
            conn.execute("INSERT INTO hunts (business_id, flow, status, spot)"
                         " VALUES (1, 'construction', 'approved', ?)",
                         (json.dumps({"city": "Pune"}),))
            conn.execute("INSERT INTO hunt_items (hunt_id, name, spec, quantity,"
                         " unit, status) VALUES (1, 'Cement', '{}', 241.88,"
                         " 'bag', 'boq')")
            conn.commit()
        # gate: hash missing -> refused
        try:
            search_vendors(1, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("vendor search ran without approval")
        (hunt.DATA / "1").mkdir(parents=True, exist_ok=True)
        img = hunt.DATA / "1" / "1_concept_1.jpg"
        img.write_bytes(b"\xff\xd8" + b"0" * 2048)
        try:
            with db.connect() as conn:
                conn.execute("UPDATE hunts SET approved_hash = ? WHERE id = 1",
                             (house.approval_hash(1, 1, "1_concept_1.jpg"),))
                conn.commit()

            def fake_find(queries, country="IN", city="", max_n=8,
                          max_searches=3):
                assert city == "Pune", queries  # city reaches user_location
                return ([{"url": "https://dealer.example/cement"},
                         {"url": "https://blocked.example/cement"}],
                        [{"in": 10, "out": 5}], 1)

            def fake_get(url):
                if "blocked" in url:
                    raise hunt.FetchError("blocked by robots.txt")
                return SAMPLE_HTML.encode(), url

            hunt.find_listings = fake_find  # type: ignore
            hunt.polite_get = fake_get  # type: ignore
            r = search_vendors(1, 1)
            assert r["items"][0]["blocked"] == 1, r
            assert r["items"][0]["priced"] == 1, r
            assert r["items"][0]["best_price"] == 385, r
            assert r["items"][0]["best_seller"] == "Sharma Building Mart", r
            with db.connect() as conn:
                l = conn.execute("SELECT price, unit, city, verified, seller_id,"
                                 " whatsapp FROM listings").fetchone()
                assert (l["price"], l["unit"], l["city"]) == (385, "bag", "Pune"), dict(l)
                assert l["verified"] == 1 and l["whatsapp"] == "919876543210", dict(l)
                s = conn.execute("SELECT kind, opted_in, phone FROM sellers").fetchone()
                assert (s["kind"], s["opted_in"]) == ("vendor", 0), dict(s)
                assert conn.execute("SELECT COUNT(*) c FROM seller_messages"
                                    ).fetchone()["c"] == 0  # linked, never messaged
                assert conn.execute("SELECT searches_used FROM hunts WHERE id = 1"
                                    ).fetchone()[0] == 1
            v = vendors_of(1, 1)
            assert v["items"][0]["blocked"] == 1
            assert sum(1 for x in v["items"][0]["listings"]
                       if x["is_best"]) == 1
            # limit: second run reuses stored URLs (no dupes), uses searches
            r2 = search_vendors(1, 1)
            with db.connect() as conn:
                assert conn.execute("SELECT COUNT(*) c FROM listings"
                                    ).fetchone()["c"] == 2
            assert r2["items"][0]["vendors"] == 0, r2
            # unknown item picked -> refused
            try:
                search_vendors(1, 1, [999])
            except ValueError:
                pass
            else:
                raise AssertionError("unknown item accepted")
        finally:
            hunt.find_listings = real_find  # type: ignore
            hunt.polite_get = real_get  # type: ignore
            try:
                img.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        db.DB_PATH = old
    print("vendor_search selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        # Real run on VPS: python vendor_search.py search <bid> <hid> [item_ids]
        bid, hid = int(sys.argv[2]), int(sys.argv[3])
        ids = [int(x) for x in sys.argv[4:]] or None
        import pprint
        db.init_db()
        hunt_mod = __import__("hunt")
        hunt_mod.init_db()
        __import__("sellers").init_db()
        out = search_vendors(bid, hid, ids)
        pprint.pprint(out)
        with db.connect() as conn:
            h = conn.execute("SELECT tokens_in, tokens_out, cost_usd,"
                             " searches_used FROM hunts WHERE id = ?",
                             (hid,)).fetchone()
            print("cost:", dict(h))
    else:
        print("usage: python vendor_search.py selfcheck|search <bid> <hid> [items]")
