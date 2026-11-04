"""House Artist + approval gate. Concept images only, never design drawings.

Approval is enforced in code: vendor search and calls refuse to run unless
the live BOQ rows + chosen image still hash to the approved hash. Editing
the BOQ clears the approval (see boq.set_boq_qty).
"""
import hashlib
import json
import os

import httpx

import db

LABEL = "Concept image. Not to scale, and the real building will differ."
MAX_IMAGES = 5


def _concept_paths(bid: int, hid: int) -> list:
    import hunt
    return sorted((hunt.DATA / str(bid)).glob(f"{hid}_concept_*"))


def _call_images(prompt: str, plan_b64: str, mime: str) -> bytes:
    """One image edit call. Returns raw image bytes. Raises on failure."""
    import httpx
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("MODEL_API_KEY", "")
    if not key:
        raise RuntimeError("MODEL_API_KEY missing in backend/.env")
    data_url = f"data:{mime};base64,{plan_b64}"
    r = httpx.post("https://api.meta.ai/v1/images/edits",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": "muse-image-1.0",
                         "images": [{"image_url": data_url}],
                         "prompt": prompt, "n": 1}, timeout=180)
    r.raise_for_status()
    payload = r.json()
    # Accept a URL or inline base64, whichever ImagesResponse carries.
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("url",) and isinstance(v, str) and v.startswith("http"):
                    found.append(("url", v))
                elif k in ("b64_json", "base64", "image_base64") and isinstance(v, str):
                    found.append(("b64", v))
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(payload)
    if not found:
        raise RuntimeError("image call returned no image")
    kind, val = found[0]
    if kind == "url":
        d = httpx.get(val, timeout=60)
        d.raise_for_status()
        if len(d.content) > 8 * 1024 * 1024:
            raise RuntimeError("image too large")
        return d.content
    import base64
    return base64.b64decode(val)


def generate_image(bid: int, hid: int, style: str = "") -> dict:
    """House Artist: plan + floors/finish prompt -> concept image file."""
    import base64
    import hunt
    existing = _concept_paths(bid, hid)
    if len(existing) >= MAX_IMAGES:
        raise ValueError(f"limit of {MAX_IMAGES} images per hunt reached")
    with db.connect() as conn:
        h = conn.execute("SELECT spot, photo_path FROM hunts WHERE id = ?"
                         " AND business_id = ?", (hid, bid)).fetchone()
        if not h:
            raise ValueError("unknown hunt")
        try:
            intake = json.loads(h["spot"] or "{}")
        except ValueError:
            intake = {}
    raw = hunt.photo_bytes(h["photo_path"] or "")
    if not raw:
        raise RuntimeError("plan file missing")
    mime = "application/pdf" if raw[:4] == b"%PDF" else "image/jpeg"
    prompt = (f"Exterior concept view of a {intake.get('floors') or 1}-storey"
              f" {intake.get('finish') or 'standard'}-finish family house."
              f" {style.strip()[:200]}"
              " Daytime, street view, no people close up, no text or watermark.")
    img = _call_images(prompt, base64.b64encode(raw).decode(), mime)
    if img[:4] == b"%PDF" or len(img) < 1000:
        raise RuntimeError("image call returned no usable image")
    d = hunt.DATA / str(bid)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{hid}_concept_{len(existing) + 1}.jpg"
    (d / name).write_bytes(img)
    hunt.step(hid, "House Artist", "done", f"{name}: {LABEL}")
    return {"image": name, "label": LABEL}


def boq_snapshot(bid: int, hunt_id: int) -> list:
    import boq
    return boq.boq_lines(hunt_id, bid)


def approval_hash(bid: int, hunt_id: int, image_name: str) -> str:
    import hunt
    snap = boq_snapshot(bid, hunt_id)
    canon = json.dumps(
        [{"n": ln["name"], "u": ln["unit"], "q": ln["quantity"]} for ln in snap],
        sort_keys=True)
    with db.connect() as conn:
        h = conn.execute("SELECT id FROM hunts WHERE id = ? AND business_id = ?",
                         (hunt_id, bid)).fetchone()
    if not h:
        raise ValueError("unknown hunt")
    img = hunt.DATA / str(bid) / image_name
    if not img.is_file():
        raise ValueError("unknown image")
    return hashlib.sha256((canon + "|").encode() + img.read_bytes()).hexdigest()


def approve(bid: int, hid: int, user_id: int, image_name: str) -> dict:
    """User clicks Approve on the BOQ + chosen image. Saves hash + time."""
    import hunt
    if "/" in image_name or not image_name.startswith(f"{hid}_concept_"):
        raise ValueError("unknown image")
    with db.connect() as conn:
        h = conn.execute("SELECT status FROM hunts WHERE id = ? AND business_id = ?",
                         (hid, bid)).fetchone()
        if not h or h["status"] != "boq_ready":
            raise ValueError("BOQ is not ready to approve")
        if not boq_snapshot(bid, hid):
            raise ValueError("BOQ is empty")
    digest = approval_hash(bid, hid, image_name)
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE hunts SET status = 'approved', approved_at = ?,"
                     " approved_by = ?, approved_hash = ? WHERE id = ?",
                     (now, user_id, digest, hid))
        conn.commit()
    hunt.step(hid, "Ranker", "done", f"approved {image_name}")
    return {"approved_at": now, "image": image_name}


def approval_ok(bid: int, hid: int) -> tuple[bool, str]:
    with db.connect() as conn:
        h = conn.execute("SELECT status, approved_hash FROM hunts WHERE id = ?"
                         " AND business_id = ?", (hid, bid)).fetchone()
        if not h:
            return False, "unknown hunt"
        if h["status"] != "approved" or not h["approved_hash"]:
            return False, "not approved yet"
        saved = h["approved_hash"]
    # The hash covers BOQ rows + approved image bytes, but we don't store
    # which image. Re-hash every concept file; any BOQ edit breaks all matches.
    import hunt
    for p in _concept_paths(bid, hid):
        try:
            if approval_hash(bid, hid, p.name) == saved:
                return True, "approved"
        except ValueError:
            continue
    return False, "BOQ or image changed since approval; approve again"


def require_approval(bid: int, hid: int) -> None:
    ok, reason = approval_ok(bid, hid)
    if not ok:
        raise ValueError(f"vendor search needs approval: {reason}")


def routes(app, *, require_api_key, need_login, api_error) -> None:
    import asyncio
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse

    @app.post("/api/hunts/{hunt_id}/image")
    async def make_image(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            out = await asyncio.to_thread(
                generate_image, u["business_id"], hunt_id,
                (body.get("style") if isinstance(body, dict) else "") or "")
        except (ValueError, RuntimeError) as e:
            # Plain failure, retry allowed; never a stock image instead.
            return api_error("failed", f"image failed: {e}; try again", 502)
        except httpx.HTTPError:
            # Network or timeout reaching the image model, not our bug.
            return api_error("failed", "image failed, try again", 502)
        return JSONResponse(out)

    @app.get("/api/hunts/{hunt_id}/image")
    async def get_image(hunt_id: int, request: Request, n: int = 1):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        import hunt
        p = hunt.DATA / str(u["business_id"]) / f"{hunt_id}_concept_{n}.jpg"
        if not p.is_file():
            return api_error("not_found", "no image", 404)
        return FileResponse(p, media_type="image/jpeg")

    @app.post("/api/hunts/{hunt_id}/approve")
    async def approve_hunt(hunt_id: int, request: Request):
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
            return approve(u["business_id"], hunt_id, u["id"],
                           (body.get("image") if isinstance(body, dict) else "") or "")
        except ValueError as e:
            return api_error("invalid", str(e), 422)

    @app.get("/api/hunts/{hunt_id}/approval")
    async def approval(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        ok, reason = approval_ok(u["business_id"], hunt_id)
        return {"approved": ok, "reason": reason,
                "label": LABEL}


# ---- selfcheck: offline, image call stubbed ----

def selfcheck() -> None:
    """Refused before approval and after an edit; passes once approved."""
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmp) / "t.db"
    real_call = _call_images
    files = []
    try:
        db.init_db()
        import boq
        import hunt
        hunt.init_db()
        with db.connect() as conn:
            conn.execute("INSERT INTO businesses (slug, name) VALUES ('a','A')")
            conn.execute("INSERT INTO hunts (business_id, flow, status, spot)"
                         " VALUES (1, 'construction', 'rooms_confirmed', '{}')")
            conn.execute("INSERT INTO hunt_items (hunt_id, name, spec, quantity,"
                         " unit, status) VALUES (1, 'Cement', '{}', 100, 'bag', 'room')")
            conn.commit()
        # gate 1: no BOQ yet -> approve refuses
        try:
            approve(1, 1, 1, "1_concept_1.jpg")
        except ValueError:
            pass
        else:
            raise AssertionError("approved with no BOQ")
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET status = 'boq_ready' WHERE id = 1")
            conn.execute("INSERT INTO hunt_items (hunt_id, name, spec, quantity,"
                         " unit, status) VALUES (1, 'Cement', '{}', 241.88,"
                         " 'bag', 'boq')")
            conn.commit()
        try:
            require_approval(1, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("search allowed before approval")
        # stub the image call: 2 KiB of fake jpeg
        globals()["_call_images"] = lambda *a, **k: b"\xff\xd8" + b"0" * 2048
        (hunt.DATA / "1").mkdir(parents=True, exist_ok=True)
        plan = hunt.DATA / "1" / "1.jpg"
        plan.write_bytes(b"\xff\xd8" + b"1" * 2048)
        files.append(plan)
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET photo_path = '1/1.jpg' WHERE id = 1")
            conn.commit()
        out = generate_image(1, 1)
        files.append(hunt.DATA / "1" / out["image"])
        assert out["label"].startswith("Concept image"), out
        try:
            generate_image(1, 1, "x" * 1)  # still counts to the limit path
        except ValueError:
            raise AssertionError("limit hit at 2 images")
        r = approve(1, 1, 7, out["image"])
        assert r["approved_at"], r
        ok, _ = approval_ok(1, 1)
        assert ok is True
        require_approval(1, 1)  # no raise
        # gate 2: editing the BOQ clears the approval
        boq.set_boq_qty(1, 1, "Cement", 200)
        ok, _ = approval_ok(1, 1)
        assert ok is False
        try:
            require_approval(1, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("search allowed after BOQ edit")
        # gate 2b: rows changed behind an intact approval -> hash mismatch
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET status = 'approved', approved_at = 'x',"
                         " approved_by = 1, approved_hash = ? WHERE id = 1",
                         (approval_hash(1, 1, out["image"]),))
            conn.commit()
        require_approval(1, 1)  # no raise
        with db.connect() as conn:
            conn.execute("UPDATE hunt_items SET quantity = 999 WHERE hunt_id = 1"
                         " AND name = 'Cement'")
            conn.commit()
        ok, reason = approval_ok(1, 1)
        assert ok is False and "changed" in reason, reason
        try:
            require_approval(1, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("search allowed after silent BOQ change")
    finally:
        globals()["_call_images"] = real_call
        db.DB_PATH = old
        for f in files:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    print("house selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python house.py selfcheck")
