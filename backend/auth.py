"""Signup/login/sessions (argon2id, SHA-256 stored tokens)."""
import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

import db

_hasher = PasswordHasher()
_attempts: dict[str, list[float]] = {}  # email -> recent try timestamps


def err(code: str, message: str, status: int) -> dict:
    return {"error": {"code": code, "message": message}, "status": status}


def check_rate_limit(email: str) -> bool:
    """True if allowed; max 5 tries/minute per email."""
    now = time.time()
    recent = [t for t in _attempts.get(email, []) if now - t < 60]
    if len(recent) >= 5:
        _attempts[email] = recent
        return False
    recent.append(now)
    _attempts[email] = recent
    return True


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "business"
    with db.connect() as conn:
        row = conn.execute("SELECT slug FROM businesses WHERE slug LIKE ?", (slug + "%",)).fetchall()
    taken = {r["slug"] for r in row}
    if slug not in taken:
        return slug
    i = 2
    while f"{slug}-{i}" in taken:
        i += 1
    return f"{slug}-{i}"


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _hasher.verify(hash_, pw)
    except VerifyMismatchError:
        return False


def new_session(user_id: int) -> str:
    token = secrets.token_bytes(32).hex()
    digest = hashlib.sha256(token.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, digest, expires),
        )
        conn.commit()
    return token


def user_from_token(token: str) -> dict | None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db.connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.business_id, u.name, u.email, u.role,
                      b.name AS business_name, b.slug AS business_slug
               FROM sessions s JOIN users u ON u.id = s.user_id
               JOIN businesses b ON b.id = u.business_id
               WHERE s.token_hash = ? AND s.expires_at > datetime('now')""",
            (digest,),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
        conn.commit()
