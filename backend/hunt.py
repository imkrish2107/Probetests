"""Shopping hunt agents: photo in, ranked listings out.

Pipeline: Spotter (SAM crop + Spark structured) -> Finder (web_search x3)
-> Checker (polite fetch, JSON-LD/meta/quote verify) -> Matcher (image
similarity, drop <60) -> Ranker (plain code). Each agent writes hunt_steps.
Runs in a BackgroundTasks threadpool so the event loop never blocks.

Safety: only search-tool URLs are fetched; page text never acts, it is only
parsed into fields and shown labelled. Sellers are never messaged here.
"""
import datetime as dt
import html
import ipaddress
import json
import logging
import os
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import db

log = logging.getLogger("uvicorn.error")

API = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
DATA = Path(__file__).with_name("data") / "hunts"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ShoppingHunt/1.0)"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hunts (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
  user_id INTEGER REFERENCES users(id), status TEXT DEFAULT 'running',
  flow TEXT DEFAULT 'shopping',
  approved_at TEXT DEFAULT '', approved_by INTEGER DEFAULT 0, approved_hash TEXT DEFAULT '',
  photo_path TEXT DEFAULT '', size_pref TEXT DEFAULT '', budget REAL,
  spot TEXT DEFAULT '{}', top_reason TEXT DEFAULT '',
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0,
  searches_used INTEGER DEFAULT 0, error TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS hunt_items (
  id INTEGER PRIMARY KEY, hunt_id INTEGER NOT NULL REFERENCES hunts(id),
  name TEXT NOT NULL, spec TEXT DEFAULT '{}', quantity REAL DEFAULT 1,
  unit TEXT DEFAULT '', status TEXT DEFAULT 'sourcing'
);
CREATE TABLE IF NOT EXISTS hunt_steps (
  id INTEGER PRIMARY KEY, hunt_id INTEGER NOT NULL REFERENCES hunts(id),
  agent TEXT NOT NULL, state TEXT DEFAULT 'running', detail TEXT DEFAULT '',
  at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY, hunt_id INTEGER NOT NULL REFERENCES hunts(id),
  hunt_item_id INTEGER REFERENCES hunt_items(id),
  business_id INTEGER NOT NULL, url TEXT NOT NULL, title TEXT DEFAULT '',
  seller TEXT DEFAULT '', price REAL, currency TEXT DEFAULT '',
  unit TEXT DEFAULT '', city TEXT DEFAULT '',
  in_stock TEXT DEFAULT 'unknown', delivery TEXT DEFAULT '',
  image_url TEXT DEFAULT '', whatsapp TEXT DEFAULT '',
  similarity INTEGER DEFAULT 0, match_reason TEXT DEFAULT '',
  verified INTEGER DEFAULT 0, verify_note TEXT DEFAULT ''
);
"""

SPOT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_garment": {"type": "boolean"},
        "garment": {"type": "string"}, "colour": {"type": "string"},
        "pattern": {"type": "string"}, "fabric": {"type": "string"},
        "collar": {"type": "string"}, "sleeve": {"type": "string"},
        "fit": {"type": "string"}, "brand": {"type": "string"},
        "phrases": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_garment", "garment", "colour", "phrases"],
}
MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "similarity": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["similarity", "reason"],
}

# Product pages only: drop search engines, video and social results.
NON_PRODUCT = ("google.", "bing.", "youtube.", "youtu.be", "facebook.",
                "instagram.", "pinterest.", "wikipedia.", "tiktok.")

_reasoning_ok = True  # set False on first 400 naming reasoning (logged)


def init_db() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        # migrate dev DBs made before the engine columns existed
        hcols = [r[1] for r in conn.execute("PRAGMA table_info(hunts)")]
        for col in ("flow TEXT DEFAULT 'shopping'", "approved_at TEXT DEFAULT ''",
                    "approved_by INTEGER DEFAULT 0", "approved_hash TEXT DEFAULT ''"):
            if col.split()[0] not in hcols:
                conn.execute(f"ALTER TABLE hunts ADD COLUMN {col}")
        lcols = [r[1] for r in conn.execute("PRAGMA table_info(listings)")]
        for col in ("hunt_item_id INTEGER REFERENCES hunt_items(id)",
                    "unit TEXT DEFAULT ''", "city TEXT DEFAULT ''"):
            if col.split()[0] not in lcols:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col}")
        conn.commit()


def fail_stale() -> None:
    """Mark hunts left running (restart) as failed; photos GC'd below."""
    with db.connect() as conn:
        conn.execute("UPDATE hunts SET status = 'failed', error = 'server restarted'"
                     " WHERE status = 'running'")
        conn.commit()
    gc_photos()


def gc_photos() -> None:
    """Delete hunt photos older than 7 days."""
    if not DATA.exists():
        return
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    for f in DATA.rglob("*"):
        if f.is_file() and dt.datetime.fromtimestamp(
                f.stat().st_mtime, dt.timezone.utc) < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


def step(hunt_id: int, agent: str, state: str, detail: str = "") -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO hunt_steps (hunt_id, agent, state, detail)"
                     " VALUES (?, ?, ?, ?)", (hunt_id, agent, state, detail[:2000]))
        conn.commit()


def add_usage(hunt_id: int, tin: int, tout: int) -> None:
    import models
    cost = tin / 1000 * models.PRICE_IN_PER_1K + tout / 1000 * models.PRICE_OUT_PER_1K
    with db.connect() as conn:
        conn.execute("UPDATE hunts SET tokens_in = tokens_in + ?,"
                     " tokens_out = tokens_out + ?, cost_usd = cost_usd + ?"
                     " WHERE id = ?", (tin, tout, cost, hunt_id))
        conn.commit()


def _key() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("MODEL_API_KEY", "")
    if not key:
        raise RuntimeError("MODEL_API_KEY missing in backend/.env")
    return key


def responses_request(payload: dict, timeout: int = 90) -> tuple[dict, dict]:
    """POST /responses; usage back. Retries once without reasoning effort."""
    import httpx
    global _reasoning_ok
    headers = {"Authorization": f"Bearer {_key()}"}
    p = dict(payload)
    if _reasoning_ok:
        p.setdefault("reasoning", {"effort": "minimal"})
    r = httpx.post(f"{API}/responses", headers=headers, json=p, timeout=timeout)
    if r.status_code == 400 and _reasoning_ok \
            and "reasoning" in r.text.lower():
        _reasoning_ok = False  # server doesn't take it; plain from here on
        log.info("responses drops reasoning effort; retrying plain")
        p.pop("reasoning", None)
        r = httpx.post(f"{API}/responses", headers=headers, json=p, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    u = data.get("usage", {}) or {}
    tin = u.get("input_tokens", u.get("prompt_tokens", 0)) or 0
    tout = u.get("output_tokens", u.get("completion_tokens", 0)) or 0
    return data, {"in": tin, "out": tout}


def chat_structured(prompt: str, schema: dict, image_b64: str | None = None,
                    max_tokens: int = 600, pdf_b64: str | None = None,
                    filename: str = "plan.pdf") -> tuple[dict, dict]:
    """Chat completions + json_schema response_format. No tools: page/model
    text is untrusted data, so the call can only return fields."""
    import httpx
    import models
    content: list = [{"type": "text", "text": prompt}]
    if image_b64:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + image_b64}})
    if pdf_b64:
        content.append({"type": "file", "filename": filename,
                        "file_data": "data:application/pdf;base64," + pdf_b64})
    r = httpx.post(
        f"{API}/chat/completions", headers={"Authorization": f"Bearer {_key()}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": content}],
              "max_tokens": max_tokens, "reasoning_effort": "minimal",
              "response_format": {"type": "json_schema",
                                  "json_schema": {"name": "r", "schema": schema}}},
        timeout=60)
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    u = data.get("usage", {}) or {}
    tin, tout = u.get("prompt_tokens", 0) or 0, u.get("completion_tokens", 0) or 0
    cost = tin / 1000 * models.PRICE_IN_PER_1K + tout / 1000 * models.PRICE_OUT_PER_1K
    return json.loads(text), {"in": tin, "out": tout, "cost": cost}


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def search_results(data: dict) -> list[dict]:
    out, seen = [], set()
    for node in _walk(data):
        if isinstance(node, dict) and isinstance(node.get("results"), list):
            for r in node["results"]:
                if isinstance(r, dict) and r.get("url") and r["url"] not in seen:
                    seen.add(r["url"])
                    out.append(r)
    return out


BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+)")


def find_box(data: dict) -> tuple[int, int, int, int] | None:
    for node in _walk(data):
        if isinstance(node, str):
            m = BOX_RE.search(node)
            if m:
                return tuple(int(g) for g in m.groups())  # type: ignore[return-value]
    return None


# ---- photos ----

def save_intake(business_id: int, hunt_id: int, raw: bytes) -> tuple[str, str]:
    """Validate + save a hunt file. Returns (rel path, kind).
    Images are re-encoded (metadata stripped); PDFs are saved as-is."""
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("file over 8 MB")
    if raw[:4] == b"%PDF":
        d = DATA / str(business_id)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{hunt_id}.pdf"
        p.write_bytes(raw)
        return f"{business_id}/{hunt_id}.pdf", "pdf"
    return save_photo(business_id, hunt_id, raw), "image"


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "has_dimensions": {"type": "boolean"},
        "rooms": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "length": {"type": ["number", "null"]},
            "width": {"type": ["number", "null"]}, "unit": {"type": "string"},
            "seen_text": {"type": "string"}, "confidence": {"type": "string"}},
            "required": ["name"]}},
        "door_count": {"type": ["integer", "null"]},
        "window_count": {"type": ["integer", "null"]},
        "bathroom_count": {"type": ["integer", "null"]},
    },
    "required": ["readable", "rooms"],
}


def read_plan(raw: bytes) -> tuple[dict, dict]:
    """Plan Reader: reports only what the drawing prints. No arithmetic,
    no guessing: missing dimensions stay empty."""
    import base64
    prompt = (
        "Read this floor plan. For each room report name, length, width, unit"
        " (ft or m) and the exact dimension text printed on the drawing, plus"
        " confidence (high/low). Copy numbers only as printed; never convert,"
        " compute or fill in missing ones: use null. Also count doors,"
        " windows and bathrooms if shown. readable false if this is not a"
        " readable plan, has_dimensions false if no dimensions are printed.")
    if raw[:4] == b"%PDF":
        return chat_structured(prompt, PLAN_SCHEMA, None, max_tokens=1200,
                               pdf_b64=base64.b64encode(raw).decode())
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1536, 1536))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return chat_structured(prompt, PLAN_SCHEMA,
                           base64.b64encode(buf.getvalue()).decode(),
                           max_tokens=1200)


def _run_plan(hunt_id: int) -> None:
    with db.connect() as conn:
        h = conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
    if not h:
        return
    try:
        raw = photo_bytes(h["photo_path"] or "")
        if not raw:
            raise RuntimeError("plan file missing")
        step(hunt_id, "Plan Reader", "running")
        plan, u = read_plan(raw)
        add_usage(hunt_id, u["in"], u["out"])
        if not plan.get("readable"):
            step(hunt_id, "Plan Reader", "failed", "plan unreadable")
            raise RuntimeError("Plan unreadable: upload a clearer plan.")
        with db.connect() as conn:
            conn.execute("DELETE FROM hunt_items WHERE hunt_id = ?", (hunt_id,))
            for r in plan.get("rooms") or []:
                conn.execute(
                    "INSERT INTO hunt_items (hunt_id, name, spec, quantity,"
                    " unit, status) VALUES (?, ?, ?, 0, '', 'room')",
                    (hunt_id, str(r.get("name") or "Room")[:80],
                     json.dumps({k: r.get(k) for k in
                                 ("length", "width", "unit", "seen_text",
                                  "confidence")})))
            conn.execute("UPDATE hunts SET status = 'awaiting_rooms',"
                         " spot = ? WHERE id = ?",
                         (json.dumps({k: plan.get(k) for k in
                                      ("door_count", "window_count",
                                       "bathroom_count", "has_dimensions")}),
                          hunt_id))
            conn.commit()
        step(hunt_id, "Plan Reader", "done",
             f"{len(plan.get('rooms') or [])} rooms; check them below")
    except Exception as e:
        log.warning("plan %s failed: %s", hunt_id, e)
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET status = 'failed', error = ? WHERE id = ?",
                         (str(e)[:500], hunt_id))
            conn.commit()
        step(hunt_id, "Plan Reader", "failed", str(e)[:500])


def confirm_rooms(hunt_id: int, bid: int, rooms: list[dict]) -> dict:
    """Room check: user-edited rooms replace the Reader's; gates the BOQ."""
    with db.connect() as conn:
        h = conn.execute("SELECT status FROM hunts WHERE id = ? AND business_id = ?",
                         (hunt_id, bid)).fetchone()
        if not h:
            raise ValueError("unknown hunt")
        if h["status"] not in ("awaiting_rooms", "rooms_confirmed", "failed"):
            raise ValueError("rooms are not ready to check yet")
        # "failed" is the unreadable-plan dead end: hand-entered rooms replace
        # nothing and reopen the hunt at rooms_confirmed.
        cleaned = []
        for r in rooms:
            name = str(r.get("name") or "").strip()[:80]
            if not name:
                continue
            try:
                ln = float(r.get("length") or 0)
                wd = float(r.get("width") or 0)
            except (ValueError, TypeError):
                raise ValueError(f"bad size for {name}")
            if ln < 0 or wd < 0:
                raise ValueError(f"bad size for {name}")
            cleaned.append((name, ln, wd, str(r.get("unit") or "ft")[:10]))
        if not cleaned:
            raise ValueError("at least one room is required")
        conn.execute("DELETE FROM hunt_items WHERE hunt_id = ? AND status = 'room'",
                     (hunt_id,))
        for name, ln, wd, unit in cleaned:
            conn.execute("INSERT INTO hunt_items (hunt_id, name, spec, quantity,"
                         " unit, status) VALUES (?, ?, ?, 0, ?, 'room')",
                         (hunt_id, name,
                          json.dumps({"length": ln, "width": wd, "unit": unit}),
                          unit))
        conn.execute("UPDATE hunts SET status = 'rooms_confirmed' WHERE id = ?",
                     (hunt_id,))
        conn.commit()
    return {"rooms": len(cleaned)}


def save_photo(business_id: int, hunt_id: int, raw: bytes) -> str:
    """Validate, strip metadata by re-encode, save. Returns relative path."""
    from PIL import Image
    import io
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("photo over 8 MB")
    img = Image.open(io.BytesIO(raw))
    if img.format not in ("JPEG", "PNG", "WEBP"):
        raise ValueError("need JPEG, PNG or WebP")
    img = img.convert("RGB")
    d = DATA / str(business_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{hunt_id}.jpg"
    img.save(p, "JPEG", quality=88)  # fresh encode: no EXIF, no metadata
    return f"{business_id}/{hunt_id}.jpg"


def photo_bytes(rel: str) -> bytes | None:
    p = DATA / rel
    return p.read_bytes() if p.is_file() else None


# ---- Spotter ----

def spotter(image_b64: str) -> tuple[dict, dict]:
    """SAM crop first (full photo on failure), then structured describe."""
    crop_b64 = image_b64
    try:
        data, _ = responses_request({
            "model": "sam-3.1",
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "shirt"},
                {"type": "input_image",
                 "image_url": "data:image/jpeg;base64," + image_b64}]}]})
        box = find_box(data)
        if box:
            from PIL import Image
            import base64
            import io
            img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
            x1, y1, x2, y2 = box
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.width, x2), min(img.height, y2)
            if x2 > x1 + 20 and y2 > y1 + 20:
                buf = io.BytesIO()
                img.crop((x1, y1, x2, y2)).save(buf, "JPEG", quality=88)
                crop_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        log.warning("sam crop failed, full photo: %s", e)
    spot, usage = chat_structured(
        "Describe this clothing item for shopping search. phrases: 3 short"
        " search phrases (colour + garment + detail). brand only if clearly"
        " visible as a logo, else empty. is_garment false if no clothing.",
        SPOT_SCHEMA, crop_b64)
    return spot, usage


# ---- Finder ----

def normalize_url(u: str) -> str:
    p = urlparse(u)
    return (p.hostname or "").lower() + p.path.rstrip("/").lower()


def is_product_url(u: str) -> bool:
    try:
        p = urlparse(u)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    if any(d in p.hostname.lower() for d in NON_PRODUCT):
        return False
    return len(p.path.strip("/")) > 0  # homepage isn't a product page


# The only place the flows differ. Agents below take (item, profile).
PROFILES = {
    "shopping": {"intake": "photo", "match": "photo", "contact": "whatsapp",
                 "location": "delivers to user"},
    "construction": {"intake": "plan", "match": "spec", "contact": "call",
                     "location": "same city preferred"},
}


def finder(spot: dict, country: str = "IN") -> tuple[list[dict], int]:
    """Shopping Finder: phrases from what Spotter saw. Shared engine below."""
    phrases = (spot.get("phrases") or [])[:3]
    if not phrases:
        g = f"{spot.get('colour', '')} {spot.get('garment', '')}".strip()
        phrases = [g or "shirt"]
    queries = [f"{ph} buy online price India" for ph in phrases]
    found, usages, searches = find_listings(queries, country)
    finder.usages.extend(usages)  # type: ignore[attr-defined]
    return found, searches


def find_listings(queries: list[str], country: str = "IN", max_n: int = 12,
                  max_searches: int = 3, city: str = "") -> tuple[list[dict], list[dict], int]:
    """Shared Finder: web_search per query, product pages only, deduped."""
    found: list[dict] = []
    seen: set[str] = set()
    usages: list[dict] = []
    searches = 0
    loc: dict = {"type": "approximate", "country": country}
    if city.strip():
        loc["city"] = city.strip()
    for q in queries[:max_searches]:
        data, usage = responses_request({
            "model": MODEL,
            "input": q,
            "tools": [{"type": "web_search", "user_location": loc}],
            "include": ["web_search_call.results"]})
        searches += 1
        usages.append(usage)
        for r in search_results(data):
            norm = normalize_url(r["url"])
            if norm not in seen and is_product_url(r["url"]):
                seen.add(norm)
                found.append(r)
            if len(found) >= max_n:
                break
        if len(found) >= max_n:
            break
    return found, usages, searches


# usage collector: shopping Finder stash for the hunt loop.
finder.usages = []  # type: ignore[attr-defined]


# ---- Checker ----

class FetchError(Exception):
    pass


def ip_blocked(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (a.is_private or a.is_loopback or a.is_link_local
            or a.is_multicast or a.is_reserved or a.is_unspecified)


_robots_cache: dict[str, str] = {}


def robots_allows(host: str, path: str, robots_txt: str | None) -> bool:
    """Pure check against a robots.txt body (fetch lives in polite_get)."""
    if robots_txt is None:
        return True
    agent, star = True, False
    for line in robots_txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            star = v in ("*", "ShoppingHunt")
            agent = star
        elif k == "disallow" and (agent or star):
            if v and path.startswith(v):
                return False
    return True


def polite_get(url: str, max_bytes: int = 2_000_000,
               timeout: int = 10) -> tuple[bytes, str]:
    """Fetch allowing only public http(s); redirects re-checked (<=3)."""
    import httpx
    redirs = 0
    while True:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise FetchError("bad scheme")
        try:
            ip = socket.gethostbyname(p.hostname)
        except Exception:
            raise FetchError("dns failed")
        if ip_blocked(ip):
            raise FetchError("blocked address")
        host = p.hostname.lower()
        if host not in _robots_cache:
            try:
                r = httpx.get(f"{p.scheme}://{host}/robots.txt", headers=UA,
                              timeout=5, follow_redirects=False)
                _robots_cache[host] = r.text if r.status_code == 200 else ""
            except Exception:
                _robots_cache[host] = ""
        if not robots_allows(host, p.path or "/",
                              _robots_cache[host] or None):
            raise FetchError("robots denied")
        with httpx.stream("GET", url, headers=UA, timeout=timeout,
                          follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                redirs += 1
                if redirs > 3:
                    raise FetchError("too many redirects")
                url = urljoin(url, r.headers.get("location", ""))
                continue
            if r.status_code != 200:
                raise FetchError(f"http {r.status_code}")
            body = b""
            for chunk in r.iter_bytes(65536):
                body += chunk
                if len(body) > max_bytes:
                    raise FetchError("too large")
            return body, url


def _ld_offers(obj) -> list[dict]:
    out = []
    if isinstance(obj, dict):
        t = obj.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any("product" in str(x).lower() for x in types):
            offers = obj.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]
            out.extend([o for o in offers if isinstance(o, dict)])
        for v in obj.values():
            if isinstance(v, (dict, list)):
                out.extend(_ld_offers(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_ld_offers(v))
    return out


def extract_listing(page: bytes) -> dict:
    """Price/stock/seller/image from JSON-LD, then meta tags, then quote."""
    text = page.decode("utf-8", "replace")
    low = text.lower()
    out: dict = {"price": None, "currency": "", "in_stock": "unknown",
                 "seller": "", "title": "", "image": "", "delivery": "",
                 "whatsapp": "", "verify": None}
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if m:
        out["title"] = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()[:200]
    for mt in re.finditer(r'<meta[^>]+>', text, re.I):
        tag = mt.group(0)
        prop = re.search(r'(?:property|name)="([^"]+)"', tag, re.I)
        cont = re.search(r'content="([^"]*)"', tag, re.I)
        if not prop or not cont:
            continue
        k, v = prop.group(1).lower(), html.unescape(cont.group(1)).strip()
        if k in ("product:price:amount", "og:price:amount", "twitter:price:amount"):
            try:
                out["price"], out["verify"] = float(v), "meta price tag"
            except ValueError:
                pass
        elif k in ("product:price:currency", "og:price:currency"):
            out["currency"] = v.upper()[:3]
        elif k == "og:site_name":
            out["seller"] = v[:120]
        elif k in ("og:title",) and not out["title"]:
            out["title"] = v[:200]
        elif k in ("og:image", "twitter:image") and not out["image"]:
            out["image"] = v
        elif k == "product:availability":
            out["in_stock"] = ("yes" if "instock" in v.lower()
                               else "no" if "outofstock" in v.lower()
                               else "unknown")
    for ld in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            text, re.I | re.S):
        try:
            doc = json.loads(ld.group(1))
        except ValueError:
            continue
        for o in _ld_offers(doc):
            pr = o.get("price", o.get("lowPrice"))
            if pr is not None and out["price"] is None:
                try:
                    out["price"] = float(pr)
                    out["currency"] = str(o.get("priceCurrency", ""))[:3]
                    out["verify"] = "JSON-LD Offer"
                except (ValueError, TypeError):
                    pass
            av = str(o.get("availability", ""))
            if "InStock" in av:
                out["in_stock"] = "yes"
            elif "OutOfStock" in av:
                out["in_stock"] = "no"
            sel = o.get("seller", o.get("offeredBy", ""))
            if isinstance(sel, dict) and sel.get("name") and not out["seller"]:
                out["seller"] = str(sel["name"])[:120]
    if out["price"] is not None and out["verify"] in (None,):
        sym = "₹" if out["currency"] in ("", "INR") else out["currency"]
        quote = f"{sym}{out['price']:,.0f}"
        blob = re.sub(r"\s+", " ", html.unescape(
            re.sub(r"<[^>]+>", " ", text)))
        if quote in blob or f"{out['price']:,.0f}" in blob:
            out["verify"] = "exact quote on page"
    for pat in (r"wa\.me/(\d{6,15})",
                r"(?:whatsapp\.com|whatsapp)[^\"']*?(\d{10,13})"):
        m = re.search(pat, text, re.I)
        if m:
            out["whatsapp"] = m.group(1)
            break
    m = re.search(r"deliver[^.]{0,120}", low)
    if m:
        out["delivery"] = m.group(0).strip()[:200]
    return out


def check_listing(url: str, profile: dict | None = None) -> dict:
    """Shared Checker: fetch one candidate; never raises (note on failure).
    profile is the flow profile; parsing rules are identical for both flows."""
    try:
        body, final = polite_get(url)
    except FetchError as e:
        return {"url": url, "note": f"Couldn't check: {e}"}
    try:
        info = extract_listing(body)
    except Exception as e:
        log.warning("extract failed for %s: %s", url, e)
        return {"url": url, "note": "Couldn't check: parse failed"}
    info["url"] = final
    info["note"] = "" if info["price"] is not None else "Price not verified"
    return info


# ---- Matcher ----

def match_one(crop_b64: str, image_url: str) -> tuple[int, str, dict]:
    """Similarity 0-100 + reason + usage. Image fetch failure scores 0."""
    try:
        body, _ = polite_get(image_url)
        from PIL import Image
        import base64
        import io
        img = Image.open(io.BytesIO(body)).convert("RGB")
        img.thumbnail((512, 512))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        cand_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return 0, f"image not fetchable: {e}", {"in": 0, "out": 0}
    # Two images, no tools: the call can only return score + reason.
    import httpx
    content = [
        {"type": "text", "text": (
            "First image: the customer's garment. Second image: a shopping"
            " listing photo. Rate visual similarity 0-100 (same garment type,"
            " colour and pattern score high) plus one-line reason.")},
        {"type": "image_url",
         "image_url": {"url": "data:image/jpeg;base64," + crop_b64}},
        {"type": "image_url",
         "image_url": {"url": "data:image/jpeg;base64," + cand_b64}},
    ]
    r = httpx.post(
        f"{API}/chat/completions", headers={"Authorization": f"Bearer {_key()}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": content}],
              "max_tokens": 200, "reasoning_effort": "minimal",
              "response_format": {"type": "json_schema",
                                  "json_schema": {"name": "m", "schema": MATCH_SCHEMA}}},
        timeout=60)
    r.raise_for_status()
    data = r.json()
    m = json.loads(data["choices"][0]["message"]["content"])
    u = data.get("usage", {}) or {}
    mu = {"in": u.get("prompt_tokens", 0) or 0,
          "out": u.get("completion_tokens", 0) or 0}
    return int(m.get("similarity", 0)), str(m.get("reason", "")), mu


# ---- Ranker (plain code, no model) ----

# Base units: mass -> kg, volume -> cft. Unconvertible stays unranked.
_TO_BASE = {"kg": ("kg", 1), "kgs": ("kg", 1), "quintal": ("kg", 100),
            "q": ("kg", 100), "quintals": ("kg", 100),
            "tonne": ("kg", 1000), "tonnes": ("kg", 1000), "ton": ("kg", 1000),
            "tons": ("kg", 1000), "mt": ("kg", 1000),
            "cft": ("cft", 1), "cuft": ("cft", 1), "brass": ("cft", 100),
            "bag": ("bag", 1), "bags": ("bag", 1),
            "piece": ("piece", 1), "pieces": ("piece", 1), "nos": ("piece", 1)}


def to_base(price: float, unit: str) -> tuple[float, str] | None:
    """Price per base unit, or None when the unit can't be converted."""
    u = (unit or "").strip().lower()
    if u in ("", "nos"):
        u = "piece"
    conv = _TO_BASE.get(u)
    if conv is None or price is None:
        return None
    base, mult = conv
    return price / mult, base

def _delivery_fee(delivery: str) -> float:
    fees = [float(n.replace(",", "")) for n in
            re.findall(r"₹\s*([\d,]+)", delivery or "")]
    if re.search(r"free\s+deliver", (delivery or "").lower()):
        return 0.0
    return min(fees) if fees else 0.0


def rank(item: dict, rows: list[dict]) -> dict:
    """Shared Ranker. item: quantity, unit, city. Returns ordered rows plus
    cheapest/best ids and one-line reasons. Rows without a real price or
    with an unconvertible unit keep their data but stay unranked at the end.
    Never estimates a price: no price means "Quote needed"."""
    qty = item.get("quantity") or 1
    unit = item.get("unit") or ""
    city = (item.get("city") or "").strip().lower()
    scored = []
    for r in rows:
        conv = to_base(r.get("price"), r.get("unit") or unit or "piece")
        if r.get("price") is None or conv is None:
            scored.append((None, r))
            continue
        per_base, _ = conv
        total = per_base * qty + _delivery_fee(r.get("delivery", ""))
        scored.append((total, r))
    priced = [(t, r) for t, r in scored if t is not None]
    unranked = [r for t, r in scored if t is None]

    def sort_key(pair: tuple) -> tuple:
        t, r = pair
        return (not r.get("verified"), r.get("in_stock") != "yes",
                t, -(r.get("similarity") or 0))

    ordered = [r for _, r in sorted(priced, key=sort_key)] + unranked
    cheapest = min(priced, key=lambda p: p[0])[1] if priced else None
    best = None
    for _, r in sorted(priced, key=sort_key):
        if not r.get("verified") or r.get("in_stock") != "yes":
            continue
        if city and (r.get("city") or "") and city not in r["city"].lower():
            continue
        best = r
        break
    n = len(priced)
    reasons = {}
    if cheapest is not None:
        reasons["cheapest"] = (
            f"Cheapest of {n} compared: "
            f"{(cheapest.get('seller') or cheapest.get('title', ''))[:60]}")
    if best is not None:
        label = "Best and cheapest" if best is cheapest else "Best"
        reasons["best"] = (
            f"{label} of {n} compared: "
            f"{(best.get('seller') or best.get('title', ''))[:60]}")
    return {"ordered": ordered, "cheapest": cheapest, "best": best,
            "reasons": reasons, "compared": n,
            "unranked": len(unranked)}


def rank_listings(rows: list[dict]) -> list[dict]:
    """Shopping order view: same engine, quantity 1."""
    return rank({"quantity": 1, "unit": ""}, rows)["ordered"]


# ---- hunt loop ----

def _run_hunt(hunt_id: int) -> None:
    with db.connect() as conn:
        h = conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
    if not h:
        return
    bid = h["business_id"]
    try:
        raw = photo_bytes(h["photo_path"] or "")
        if not raw:
            raise RuntimeError("photo missing")
        import base64
        image_b64 = base64.b64encode(raw).decode()

        step(hunt_id, "Spotter", "running")
        spot, u = spotter(image_b64)
        add_usage(hunt_id, u["in"], u["out"])
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET spot = ? WHERE id = ?",
                         (json.dumps(spot), hunt_id))
            conn.commit()
        if not spot.get("is_garment"):
            step(hunt_id, "Spotter", "failed", "no garment in photo")
            raise RuntimeError("Photo shows no garment; try a clear shirt photo.")
        step(hunt_id, "Spotter", "done",
             f"{spot.get('colour', '')} {spot.get('garment', '')}".strip())
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO hunt_items (hunt_id, name, spec, quantity, unit)"
                " VALUES (?, ?, ?, 1, '')",
                (hunt_id, spot.get("garment", "item")[:120], json.dumps(spot)))
            item_id = cur.lastrowid
            conn.commit()

        step(hunt_id, "Finder", "running")
        finder.usages = []  # type: ignore[attr-defined]
        cands, searches = finder(spot)
        for fu in finder.usages:  # type: ignore[attr-defined]
            add_usage(hunt_id, fu["in"], fu["out"])
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET searches_used = ? WHERE id = ?",
                         (searches, hunt_id))
            conn.commit()
        if not cands:
            step(hunt_id, "Finder", "failed", "no product pages found")
            raise RuntimeError("Search found no product pages; try another photo.")
        step(hunt_id, "Finder", "done", f"{len(cands)} candidates")

        step(hunt_id, "Checker", "running")
        checked = [check_listing(c["url"], PROFILES["shopping"]) for c in cands]
        step(hunt_id, "Checker", "done",
             f"{sum(1 for c in checked if c.get('price') is not None)} priced")

        step(hunt_id, "Matcher", "running")
        scored = 0
        for c in checked:
            if c.get("image"):
                sim, reason, mu = match_one(image_b64, c["image"])
                add_usage(hunt_id, mu["in"], mu["out"])
                c["similarity"], c["match_reason"] = sim, reason
                if sim >= 60:
                    scored += 1
        step(hunt_id, "Matcher", "done", f"{scored} matched ≥60")
        kept = [c for c in checked if (c.get("similarity") or 0) >= 60]

        for c in kept:
            verified = 1 if c.get("verify") else 0
            with db.connect() as conn:
                conn.execute(
                    """INSERT INTO listings (hunt_id, hunt_item_id,
                       business_id, url, title,
                       seller, price, currency, unit, city, in_stock, delivery,
                       image_url,
                       whatsapp, similarity, match_reason, verified, verify_note)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (hunt_id, item_id, bid, c.get("url", ""),
                     c.get("title", "")[:200],
                     c.get("seller", "")[:120], c.get("price"),
                     c.get("currency", ""), "", "",
                     c.get("in_stock", "unknown"),
                     c.get("delivery", "")[:200], c.get("image", ""),
                     c.get("whatsapp", ""), c.get("similarity", 0),
                     c.get("match_reason", "")[:500], verified,
                     (c.get("verify") or c.get("note", ""))[:200]))
                conn.commit()
        ordered = rank_listings([{**c, "verified": 1 if c.get("verify") else 0}
                                 for c in kept])
        n = len(ordered)
        reason = ("Best verified price of the %d listings checked" % n) if n else ""
        if ordered and ordered[0].get("price") is not None:
            reason += f": {ordered[0].get('title', '')[:80]}"
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET status = 'done', top_reason = ?"
                         " WHERE id = ?", (reason, hunt_id))
            conn.commit()
        step(hunt_id, "Ranker", "done", reason)
    except Exception as e:
        log.warning("hunt %s failed: %s", hunt_id, e)
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET status = 'failed', error = ? WHERE id = ?",
                         (str(e)[:500], hunt_id))
            # Blame the agent that was actually running, not always Ranker.
            row = conn.execute("SELECT agent FROM hunt_steps WHERE hunt_id = ?"
                               " AND state = 'running' ORDER BY id DESC LIMIT 1",
                               (hunt_id,)).fetchone()
            conn.commit()
        step(hunt_id, row["agent"] if row else "Ranker", "failed", str(e)[:500])


# ---- routes ----

def routes(app, *, require_api_key, need_login, api_error) -> None:
    from fastapi import BackgroundTasks, Request, Response
    from fastapi.responses import FileResponse, JSONResponse

    @app.post("/api/hunts", status_code=201)
    async def create_hunt(request: Request, background_tasks: BackgroundTasks):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            form = await request.form()
        except Exception:
            return api_error("invalid", "need multipart photo upload", 422)
        up = form.get("photo") or form.get("plan")
        data = await up.read() if up and hasattr(up, "read") else b""
        if not data:
            return api_error("invalid", "photo or plan file required", 422)
        if len(data) > 8 * 1024 * 1024:
            return api_error("invalid", "file over 8 MB", 422)
        flow = str(form.get("flow") or "shopping")
        if flow not in ("shopping", "construction"):
            return api_error("invalid", "flow is shopping or construction", 422)
        size_pref = str(form.get("size") or "")[:10]
        try:
            budget = float(form.get("budget") or 0) or None
        except ValueError:
            budget = None
        intake = {}
        if flow == "construction":
            try:
                floors = int(form.get("floors") or 1)
            except ValueError:
                floors = 1
            try:
                fh = float(form.get("floor_height_ft") or 10)
            except ValueError:
                fh = 10.0
            intake = {"city": str(form.get("city") or "")[:80],
                      "floors": max(1, floors), "floor_height_ft": fh,
                      "finish": str(form.get("finish") or "standard")[:20],
                      "builtup_sqft": str(form.get("builtup_sqft") or "")[:20]}
            if intake["finish"] not in ("basic", "standard", "premium"):
                return api_error("invalid", "finish is basic/standard/premium", 422)
        with db.connect() as conn:
            running = conn.execute(
                "SELECT id FROM hunts WHERE business_id = ? AND status = 'running'",
                (u["business_id"],)).fetchone()
            if running:
                return api_error("busy", "one hunt at a time", 409)
            today = conn.execute(
                "SELECT COUNT(*) c FROM hunts WHERE business_id = ?"
                " AND created_at > datetime('now', '-1 day')",
                (u["business_id"],)).fetchone()["c"]
            if today >= 20:
                return api_error("limited", "20 hunts per day", 429)
            cur = conn.execute(
                "INSERT INTO hunts (business_id, user_id, flow, size_pref, budget, spot)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (u["business_id"], u["id"], flow, size_pref, budget,
                 json.dumps(intake)))
            hid = cur.lastrowid
            conn.commit()
        try:
            rel, kind = save_intake(u["business_id"], hid, data)
        except ValueError as e:
            with db.connect() as conn:
                conn.execute("DELETE FROM hunts WHERE id = ?", (hid,))
                conn.commit()
            return api_error("invalid", str(e), 422)
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET photo_path = ? WHERE id = ?", (rel, hid))
            conn.commit()
        gc_photos()
        if flow == "construction":
            step(hid, "Plan Reader", "queued")
            background_tasks.add_task(_run_plan, hid)
        else:
            step(hid, "Spotter", "queued")
            background_tasks.add_task(_run_hunt, hid)  # starlette threads sync tasks
        return JSONResponse({"id": hid, "status": "running", "flow": flow},
                            status_code=201)

    @app.get("/api/hunts")
    async def list_hunts(request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, flow, status, size_pref, budget, top_reason, tokens_in,"
                " tokens_out, cost_usd, searches_used, error, created_at"
                " FROM hunts WHERE business_id = ? ORDER BY id DESC LIMIT 50",
                (u["business_id"],)).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/hunts/{hunt_id}")
    async def hunt_detail(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        with db.connect() as conn:
            h = conn.execute("SELECT * FROM hunts WHERE id = ? AND business_id = ?",
                             (hunt_id, u["business_id"])).fetchone()
            if not h:
                return api_error("not_found", "no hunt", 404)
            steps = conn.execute("SELECT agent, state, detail, at FROM hunt_steps"
                                 " WHERE hunt_id = ? ORDER BY id", (hunt_id,)).fetchall()
            items = conn.execute("SELECT * FROM listings WHERE hunt_id = ?",
                                 (hunt_id,)).fetchall()
            rooms = conn.execute("SELECT * FROM hunt_items WHERE hunt_id = ?"
                                 " ORDER BY id", (hunt_id,)).fetchall()
        d = dict(h)
        d.pop("photo_path", None)
        return {"hunt": d, "steps": [dict(s) for s in steps],
                "listings": [dict(x) for x in items],
                "rooms": [dict(x) for x in rooms]}

    @app.get("/api/hunts/{hunt_id}/photo")
    async def hunt_photo(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        with db.connect() as conn:
            h = conn.execute("SELECT photo_path FROM hunts"
                             " WHERE id = ? AND business_id = ?",
                             (hunt_id, u["business_id"])).fetchone()
        if not h or not h["photo_path"]:
            return api_error("not_found", "no photo", 404)
        p = DATA / h["photo_path"]
        if not p.is_file():
            return api_error("not_found", "no photo", 404)
        media = "application/pdf" if p.suffix == ".pdf" else "image/jpeg"
        return FileResponse(p, media_type=media)

    @app.patch("/api/hunts/{hunt_id}/rooms")
    async def patch_rooms(hunt_id: int, request: Request):
        """Room check: user confirms/edits the Reader's rooms. Gates the BOQ."""
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
            return confirm_rooms(hunt_id, u["business_id"],
                                 body.get("rooms") or [])
        except ValueError as e:
            return api_error("invalid", str(e), 422)

    @app.delete("/api/hunts/{hunt_id}", status_code=204)
    async def delete_hunt(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        with db.connect() as conn:
            h = conn.execute("SELECT photo_path FROM hunts"
                             " WHERE id = ? AND business_id = ?",
                             (hunt_id, u["business_id"])).fetchone()
            if not h:
                return api_error("not_found", "no hunt", 404)
            if h["photo_path"]:
                try:
                    (DATA / h["photo_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
            for t in ("listings", "hunt_items", "hunt_steps"):
                conn.execute(f"DELETE FROM {t} WHERE hunt_id = ?", (hunt_id,))
            conn.execute("DELETE FROM seller_messages WHERE hunt_id = ?", (hunt_id,))
            conn.execute("DELETE FROM hunts WHERE id = ?", (hunt_id,))
            conn.commit()
        return Response(status_code=204)


# ---- selfcheck: offline, stubbed network + models ----

SAMPLE_JSONLD = """<html><head><title>White Tee - ShopX</title>
<meta property="og:site_name" content="ShopX">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
"name":"White Tee","image":"https://x/img.jpg",
"offers":{"@type":"Offer","price":"1299","priceCurrency":"INR",
"availability":"https://schema.org/InStock"}}</script></head>
<body><p> MRP Rs. 1,999, our price Rs. 1,299. Free delivery in 3 days.</p></body></html>"""

SAMPLE_META = """<html><head><title>Blue Shirt - ShopY</title>
<meta property="product:price:amount" content="899">
<meta property="product:price:currency" content="INR">
<meta property="product:availability" content="outofstock"></head>
<body><p>Blue shirt for Rs. 899, ships in a week.</p></body></html>"""

SAMPLE_NONE = """<html><head><title>Lookbook 2024</title></head>
<body><p>Our new collection is coming soon.</p></body></html>"""


def selfcheck() -> None:
    """Offline: extraction, blocks, invented-URL filter, ranking, isolation."""
    import tempfile
    # JSON-LD + quote
    e = extract_listing(SAMPLE_JSONLD.encode())
    assert e["price"] == 1299 and e["currency"] == "INR", e
    assert e["in_stock"] == "yes" and e["verify"] == "JSON-LD Offer", e
    assert e["seller"] == "ShopX" and "delivery" in e["delivery"], e
    # meta fallback
    e2 = extract_listing(SAMPLE_META.encode())
    assert e2["price"] == 899 and e2["verify"] == "meta price tag", e2
    assert e2["in_stock"] == "no", e2
    # no price, no verify
    e3 = extract_listing(SAMPLE_NONE.encode())
    assert e3["price"] is None and e3["verify"] is None, e3
    # address blocks (literal IPs need no DNS, so no network here)
    for bad in ("http://127.0.0.1/x", "http://10.0.0.5/", "http://192.168.1.1/",
                "http://169.254.169.254/", "ftp://x.com/y", "file:///etc/passwd"):
        try:
            polite_get(bad)
        except FetchError:
            pass
        else:
            raise AssertionError(f"not blocked: {bad}")
    assert ip_blocked("8.8.8.8") is False
    # robots pure check
    assert robots_allows("h", "/p", "User-agent: *\nDisallow: /p") is False
    assert robots_allows("h", "/q", "User-agent: *\nDisallow: /p") is True
    assert robots_allows("h", "/p", None) is True
    # invented URLs: only search-tool results pass; junk filtered
    assert is_product_url("https://shop.example/white-tee-123") is True
    for junk in ("https://www.google.com/search?q=x", "https://shop.example/",
                 "https://youtu.be/abc", "javascript:alert(1)"):
        assert is_product_url(junk) is False, junk
    assert normalize_url("https://S.example/P/?utm=x") == "s.example/p"
    # ranking still passes through the shared engine
    rows = [
        {"price": 900, "delivery": "", "in_stock": "yes",
         "verified": 0, "similarity": 99},
        {"price": 1000, "delivery": "₹100 delivery", "in_stock": "no",
         "verified": 1, "similarity": 70},
        {"price": 1200, "delivery": "Free delivery", "in_stock": "yes",
         "verified": 1, "similarity": 80},
        {"price": 1100, "delivery": "", "in_stock": "yes",
         "verified": 1, "similarity": 75},
    ]
    assert [r["price"] for r in rank_listings(rows)] == [1100, 1200, 1000, 900]
    # unit conversion: tonne/quintal to kg, brass to cft
    assert to_base(52000, "tonne") == (52.0, "kg")
    assert to_base(6200, "quintal") == (62.0, "kg")
    assert to_base(5000, "brass") == (50.0, "cft")
    assert to_base(100, "bag") == (100.0, "bag")
    assert to_base(100, "lot") is None  # unconvertible
    assert to_base(None, "kg") is None
    # Best vs Cheapest on a construction item
    crows = [
        {"seller": "Far Vendor", "price": 50, "unit": "kg", "city": "Delhi",
         "in_stock": "yes", "verified": 1, "delivery": "", "similarity": 0},
        {"seller": "Local Vendor", "price": 55, "unit": "kg", "city": "Jaipur",
         "in_stock": "yes", "verified": 1, "delivery": "",
         "similarity": 0},
        {"seller": "NoStock", "price": 40, "unit": "kg", "city": "Jaipur",
         "in_stock": "no", "verified": 1, "delivery": "", "similarity": 0},
        {"seller": "QuoteMe", "price": None, "unit": "kg", "city": "Jaipur",
         "in_stock": "unknown", "verified": 0, "delivery": "",
         "similarity": 0},
        {"seller": "WeirdLot", "price": 30, "unit": "lot", "city": "Jaipur",
         "in_stock": "yes", "verified": 1, "delivery": "", "similarity": 0},
    ]
    res = rank({"quantity": 100, "unit": "kg", "city": "Jaipur"}, crows)
    assert res["cheapest"]["seller"] == "NoStock", res["reasons"]  # lowest total
    assert res["best"]["seller"] == "Local Vendor", res["reasons"]  # in area+stock
    assert res["compared"] == 3 and res["unranked"] == 2, res  # quote+lot aside
    assert res["ordered"][-2]["seller"] == "QuoteMe"
    assert res["ordered"][-1]["seller"] == "WeirdLot"
    # same vendor is both: one row, both labels
    same = rank({"quantity": 1, "unit": "kg", "city": ""},
                [dict(crows[1], in_stock="yes")])
    assert same["best"] is same["cheapest"]
    assert same["reasons"]["best"].startswith("Best and cheapest")
    # business isolation on a temp DB
    tmp = tempfile.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmp) / "t.db"
    try:
        db.init_db()
        init_db()
        with db.connect() as conn:
            conn.execute("INSERT INTO businesses (slug, name) VALUES ('a','A'),('b','B')")
            conn.execute("INSERT INTO hunts (business_id, status) VALUES (1,'done')")
            conn.execute("INSERT INTO listings (hunt_id, business_id, url) VALUES (1,1,'u')")
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) c FROM hunts WHERE business_id = 2").fetchone()["c"] == 0
            assert conn.execute(
                "SELECT COUNT(*) c FROM listings WHERE business_id = 2").fetchone()["c"] == 0
    finally:
        db.DB_PATH = old
    assert _reasoning_ok in (True, False)  # flag exists; real hunt says which
    # Plan flow on a second temp DB, model stubbed. No network here.
    db.DB_PATH = Path(tmp) / "p.db"
    real_chat = chat_structured
    plan_file = DATA / "1" / "1.pdf"
    try:
        db.init_db()
        init_db()
        fake = {"readable": True, "has_dimensions": True,
                "rooms": [{"name": "Living", "length": 14, "width": 12,
                           "unit": "ft", "seen_text": "14' x 12'",
                           "confidence": "high"},
                          {"name": "Bath", "length": None, "width": None,
                           "unit": "", "seen_text": "", "confidence": "low"}],
                "door_count": 2, "window_count": 3, "bathroom_count": 1}
        globals()["chat_structured"] = lambda *a, **k: (fake, {"in": 1, "out": 1})
        with db.connect() as conn:
            conn.execute("INSERT INTO businesses (slug, name) VALUES ('p','P')")
            conn.execute("INSERT INTO hunts (business_id, flow, status, photo_path)"
                         " VALUES (1, 'construction', 'running', '1/1.pdf')")
            conn.commit()
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_bytes(b"%PDF-1.4 fake")
        _run_plan(1)
        with db.connect() as conn:
            st = conn.execute("SELECT status FROM hunts WHERE id = 1"
                              ).fetchone()["status"]
            assert st == "awaiting_rooms", st
            rooms = conn.execute("SELECT name, spec FROM hunt_items WHERE hunt_id = 1"
                                 ).fetchall()
            assert len(rooms) == 2, len(rooms)
        # Room check: user fills the missing Bath size; gates later BOQ.
        r = confirm_rooms(1, 1, [{"name": "Living", "length": 14, "width": 12,
                                  "unit": "ft"},
                                 {"name": "Bath", "length": 7, "width": 5,
                                  "unit": "ft"}])
        assert r == {"rooms": 2}, r
        with db.connect() as conn:
            assert conn.execute("SELECT status FROM hunts WHERE id = 1"
                                ).fetchone()["status"] == "rooms_confirmed"
            bath = conn.execute("SELECT spec FROM hunt_items WHERE name = 'Bath'"
                                ).fetchone()
            assert json.loads(bath["spec"]) == {"length": 7.0, "width": 5.0,
                                                "unit": "ft"}
        try:
            confirm_rooms(1, 1, [{"name": "", "length": 1, "width": 1}])
        except ValueError:
            pass
        else:
            raise AssertionError("empty rooms accepted")
        # Unreadable plan fails the hunt with a clear message.
        globals()["chat_structured"] = lambda *a, **k: ({"readable": False,
                                                          "rooms": []},
                                                         {"in": 1, "out": 1})
        with db.connect() as conn:
            conn.execute("INSERT INTO hunts (business_id, flow, status, photo_path)"
                         " VALUES (1, 'construction', 'running', '1/1.pdf')")
            conn.commit()
        _run_plan(2)
        with db.connect() as conn:
            h2 = conn.execute("SELECT status, error FROM hunts WHERE id = 2").fetchone()
            assert h2["status"] == "failed" and "unreadable" in h2["error"], dict(h2)
        # Dead end reopened: hand-entered rooms on the failed hunt work.
        r2 = confirm_rooms(2, 1, [{"name": "Living", "length": 14, "width": 12,
                                   "unit": "ft"}])
        assert r2 == {"rooms": 1}, r2
        with db.connect() as conn:
            assert conn.execute("SELECT status FROM hunts WHERE id = 2"
                                ).fetchone()["status"] == "rooms_confirmed"
    finally:
        globals()["chat_structured"] = real_chat
        db.DB_PATH = old
        try:
            plan_file.unlink(missing_ok=True)
        except OSError:
            pass
    print("hunt selfcheck: PASS")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    elif len(sys.argv) > 1 and sys.argv[1] == "hunt":
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("MODEL_API_KEY"):
            print("hunt aborted: MODEL_API_KEY missing in backend/.env")
            sys.exit(2)
        src = Path(__file__).with_name("hunt_test") / "shirt.jpg"
        raw = src.read_bytes()
        import base64
        b64 = base64.b64encode(raw).decode()
        print("spotter...")
        spot, u = spotter(b64)
        print(json.dumps(spot, indent=1)[:1500])
        print("finder...")
        finder.usages = []  # type: ignore[attr-defined]
        cands, n = finder(spot)
        for fu in finder.usages:  # type: ignore[attr-defined]
            u["in"] += fu["in"]
            u["out"] += fu["out"]
        print(f"{len(cands)} candidates from {n} searches")
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((512, 512))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        crop = base64.b64encode(buf.getvalue()).decode()
        print("checker+matcher...")
        out = []
        for c in cands:
            info = check_listing(c["url"])
            info["title"] = info.get("title") or c.get("title", "")
            if info.get("image"):
                sim, why, mu = match_one(crop, info["image"])
                u["in"] += mu["in"]
                u["out"] += mu["out"]
                info["similarity"], info["match_reason"] = sim, why
            else:
                info["similarity"] = 0
            out.append(info)
        kept = [c for c in out if (c.get("similarity") or 0) >= 60]
        for c in rank_listings([{**c, "verified": 1 if c.get("verify") else 0}
                                for c in kept]):
            print(f"{c.get('similarity')} {c.get('price')} {c.get('currency')}"
                  f" {c.get('in_stock')} verified={c.get('verified')}"
                  f" {c.get('title', '')[:60]} {c.get('url', '')[:80]}")
        print(f"tokens {u['in']}/{u['out']} searches {n}"
              f" verified {sum(1 for c in kept if c.get('verify'))}/{len(kept)}")
    elif len(sys.argv) > 1 and sys.argv[1] == "read-plan" and len(sys.argv) > 2:
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("MODEL_API_KEY"):
            print("read-plan aborted: MODEL_API_KEY missing in backend/.env")
            sys.exit(2)
        raw = Path(sys.argv[2]).read_bytes()
        plan, u = read_plan(raw)
        print(json.dumps(plan, indent=1)[:2000])
        print(f"tokens {u['in']}/{u['out']}")
    else:
        print("usage: python hunt.py [selfcheck|hunt|read-plan <file>]")
