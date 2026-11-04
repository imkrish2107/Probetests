"""One-time seed: ESCAPE business + 6 products. Run once on the VPS:

  cd /home/kautilya/Probetests/backend && .venv/bin/python seed_escape.py

Idempotent: re-running only fills gaps. Photos must already be in
store/public/products/ (see filenames below).
"""
import os

from dotenv import load_dotenv

import db
import store

load_dotenv()

PRODUCTS = [
    ("oversized-tee", "Escape Oversized Tee", 99900, "tee-white.jpg",
     "240 GSM combed cotton", "Dropped shoulders, boxy fit. Model is 6'1\" and wears M."),
    ("smoke-tee", "Smoke Graphic Tee", 119900, "tee-smoke.jpg",
     "220 GSM cotton", "Regular fit, chest print. Model is 5'11\" and wears M."),
    ("essential-hoodie", "Essential Hoodie", 199900, "hoodie.jpg",
     "400 GSM brushed fleece", "Relaxed fit, double-lined hood. Model is 6'0\" and wears L."),
    ("leather-biker", "Leather Biker", 599900, "leather.jpg",
     "Genuine leather", "Slim biker cut, quilted shoulders. Model is 6'1\" and wears M."),
    ("raw-denim", "Raw Denim", 249900, "denim.jpg",
     "14oz raw denim", "Straight leg, chainstitched hems. Model is 5'10\" and wears 32."),
    ("denim-trucker", "Denim Trucker", 279900, "jacket-denim.jpg",
     "12oz washed denim", "Classic trucker, boxy fit. Model is 6'0\" and wears M."),
]

GREETING = "Hi! This is ESCAPE's AI assistant. Are you calling about an order?"


def main() -> None:
    db.init_db()
    store.ensure_tables()
    pnid = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    disp = os.getenv("WHATSAPP_DISPLAY_NUMBER", "")
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM businesses WHERE slug = 'escape'").fetchone()
        if row:
            bid = row["id"]
            conn.execute("UPDATE businesses SET name = 'ESCAPE', languages = ?, greeting = ?"
                         " WHERE id = ?", ('["English"]', GREETING, bid))
        else:
            cur = conn.execute(
                "INSERT INTO businesses (slug, name, timezone, languages, greeting,"
                " wa_phone_number_id, wa_display_number)"
                " VALUES ('escape','ESCAPE','Asia/Kolkata','[\"English\"]',?,?,?)",
                (GREETING, pnid, disp))
            bid = cur.lastrowid
        if pnid:
            conn.execute("UPDATE businesses SET wa_phone_number_id = ? WHERE id = ?", (pnid, bid))
        if disp:
            conn.execute("UPDATE businesses SET wa_display_number = ? WHERE id = ?", (disp, bid))
        have = {r["slug"] for r in conn.execute(
            "SELECT slug FROM products WHERE business_id = ?", (bid,)).fetchall()}
        added = 0
        for slug, name, paise, img, fabric, fit in PRODUCTS:
            if slug in have:
                continue
            conn.execute("INSERT INTO products (business_id, slug, name, price_paise, image,"
                         " fabric, fit) VALUES (?,?,?,?,?,?,?)",
                         (bid, slug, name, paise, img, fabric, fit))
            added += 1
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM products WHERE business_id = ?",
                         (bid,)).fetchone()[0]
        num = conn.execute("SELECT wa_phone_number_id, wa_display_number FROM businesses"
                           " WHERE id = ?", (bid,)).fetchone()
    print(f"ESCAPE business id={bid}, products={n} (+{added} new)")
    print(f"wa_phone_number_id={'set' if num['wa_phone_number_id'] else 'MISSING'}, "
          f"wa_display_number={'set' if num['wa_display_number'] else 'MISSING (wa.me links empty)'}")
    if not num["wa_display_number"]:
        print("Set wa_display_number on the dashboard setup page (your WhatsApp number, digits only).")


if __name__ == "__main__":
    main()
