"""One-time owner setup: `backend/owner_setup.py <slug> <email>`.

Run as user wa on the VPS; type the password when asked. Idempotent:
creates the business and owner if missing, moves WHATSAPP_PHONE_NUMBER_ID
and WHATSAPP_DISPLAY_NUMBER onto it (any other holder goes to NULL in the
same transaction). An existing email is left untouched.
"""
import getpass
import os
import sys

import db


def setup(slug: str, email: str, password: str) -> dict:
    """Ensure business + owner. Returns what it did; asserts in selfcheck."""
    import auth
    from dotenv import load_dotenv
    load_dotenv()
    if not slug or not email or len(password) < 8:
        raise ValueError("need slug, email and 8+ char password")
    db.init_db()
    pnid = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    disp = os.getenv("WHATSAPP_DISPLAY_NUMBER", "")
    email = email.strip().lower()
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM businesses WHERE slug = ?", (slug,)).fetchone()
        if row:
            bid = row["id"]
            created_biz = False
        else:
            cur = conn.execute("INSERT INTO businesses (slug, name) VALUES (?, ?)",
                               (slug, slug))
            bid = cur.lastrowid
            created_biz = True
        if pnid:
            # UNIQUE holder: clear anyone else first, same transaction.
            conn.execute("UPDATE businesses SET wa_phone_number_id = NULL"
                         " WHERE wa_phone_number_id = ? AND id <> ?", (pnid, bid))
            conn.execute("UPDATE businesses SET wa_phone_number_id = ?,"
                         " wa_display_number = ? WHERE id = ?", (pnid, disp, bid))
        urow = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if urow:
            created_owner = False
        else:
            conn.execute("INSERT INTO users (business_id, name, email, password_hash, role)"
                         " VALUES (?, ?, ?, ?, 'owner')",
                         (bid, email.split("@")[0], email, auth.hash_password(password)))
            created_owner = True
        conn.commit()
    return {"business_id": bid, "created_biz": created_biz, "created_owner": created_owner,
            "pnid_moved": bool(pnid)}


def selfcheck() -> None:
    """Offline: pnid steal, idempotent rerun, existing email untouched (temp DB)."""
    import tempfile
    tmp = tempfile.mkdtemp()
    db.DB_PATH = db.Path(tmp) / "t.db"
    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "15550009999"
    os.environ["WHATSAPP_DISPLAY_NUMBER"] = "15550009999"
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO businesses (slug, name, wa_phone_number_id)"
                     " VALUES ('old','Old','15550009999')")
        conn.execute("INSERT INTO users (business_id, name, email, password_hash, role)"
                     " VALUES (1, 'o', 'owner@x.com', 'kept-hash', 'owner')")
        conn.commit()
    r = setup("shop", "owner@x.com", "longenoughpassword")
    assert r["created_biz"] and not r["created_owner"], r  # email kept, not changed
    with db.connect() as conn:
        rows = {x["slug"]: x["wa_phone_number_id"] for x in conn.execute(
            "SELECT slug, wa_phone_number_id FROM businesses")}
        kept = conn.execute("SELECT password_hash FROM users WHERE email = 'owner@x.com'"
                            ).fetchone()[0]
    assert rows["shop"] == "15550009999" and rows["old"] is None, rows
    assert kept == "kept-hash", "existing owner password must not change"
    r2 = setup("shop", "new@x.com", "anotherlongpassword")
    assert not r2["created_biz"] and r2["created_owner"], r2
    print("owner_setup selfcheck: PASS")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "selfcheck":
        selfcheck()
        return 0
    if len(argv) != 3:
        print("usage: owner_setup.py <business_slug> <owner_email>")
        return 2
    pw = getpass.getpass("Owner password (8+ chars): ")
    r = setup(argv[1], argv[2], pw)
    print(f"business id={r['business_id']}"
          f" ({'created' if r['created_biz'] else 'exists'}),"
          f" owner {'created' if r['created_owner'] else 'exists, unchanged'},"
          f" number {'moved' if r['pnid_moved'] else 'not set (env empty)'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
