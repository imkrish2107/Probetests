"""BOQ: plain-code quantity estimates from confirmed rooms. The model never
produces a quantity; every number here is arithmetic with a stored basis.

Warning (shown on screen and in CSV): Estimate from thumb rules. Have a
civil engineer check it before buying or building. This is not a
structural design.
"""
import csv
import io
import json

import db

WARNING = ("Estimate from thumb rules. Have a civil engineer check it before"
           " buying or building. This is not a structural design.")

WASTAGE = 1.075  # +7.5%

# item: unit, default per built-up sqft, low, high
WHOLE_BUILDING = {
    "Cement": ("bag", 0.45, 0.35, 0.50),
    "TMT steel": ("kg", 4.0, 3.5, 5.0),
    "Sand": ("cft", 1.4, 1.2, 1.6),
    "Aggregate": ("cft", 1.5, 1.0, 2.0),
    "Bricks": ("piece", 9, 8, 10),
}

FT_PER_M = 3.28084
DOOR_OPENING_SQFT = 21.0  # 7 ft x 3 ft standard door
WINDOW_OPENING_SQFT = 12.0  # 4 ft x 3 ft standard window


def _to_ft(value: float, unit: str) -> float:
    return value * FT_PER_M if (unit or "").lower().startswith("m") else value


def rooms_of(hunt_id: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT name, spec, unit FROM hunt_items"
                            " WHERE hunt_id = ? AND status = 'room' ORDER BY id",
                            (hunt_id,)).fetchall()
    out = []
    for r in rows:
        try:
            spec = json.loads(r["spec"] or "{}")
        except ValueError:
            spec = {}
        out.append({"name": r["name"], "length_ft": _to_ft(spec.get("length") or 0,
                                                           spec.get("unit") or r["unit"]),
                    "width_ft": _to_ft(spec.get("width") or 0,
                                       spec.get("unit") or r["unit"])})
    return out


def build_boq(hunt_id: int, bid: int) -> dict:
    """Compute and store BOQ lines. Refused unless rooms are confirmed."""
    with db.connect() as conn:
        h = conn.execute("SELECT status, spot FROM hunts WHERE id = ?"
                         " AND business_id = ?", (hunt_id, bid)).fetchone()
        if not h:
            raise ValueError("unknown hunt")
        if h["status"] not in ("rooms_confirmed", "boq_ready", "approved"):
            raise ValueError("confirm the rooms before building the BOQ")
        try:
            intake = json.loads(h["spot"] or "{}")
        except ValueError:
            intake = {}
    rooms = rooms_of(hunt_id)
    if not rooms:
        raise ValueError("no rooms to build from")
    height = float(intake.get("floor_height_ft") or 10)
    try:
        builtup = float(intake.get("builtup_sqft") or 0)
    except (ValueError, TypeError):
        builtup = 0
    estimated = False
    if builtup <= 0:
        builtup = sum(r["length_ft"] * r["width_ft"] for r in rooms) * 1.2
        estimated = True
    lines: list[dict] = []
    for name, (unit, rate, lo, hi) in WHOLE_BUILDING.items():
        q = builtup * rate * WASTAGE
        lines.append({"name": name, "spec": "", "unit": unit, "quantity": round(q, 2),
                      "range": f"{builtup * lo * WASTAGE:.1f} to"
                               f" {builtup * hi * WASTAGE:.1f} {unit}",
                      "basis": f"{rate} {unit}/sqft x {builtup:.0f} sqft"
                               f" + 7.5% wastage"})
    floor_area = sum(r["length_ft"] * r["width_ft"] for r in rooms)
    lines.append({"name": "Floor tiles", "spec": "", "unit": "sqft",
                  "quantity": round(floor_area * 1.10, 2),
                  "range": "", "basis": f"floor area {floor_area:.0f} sqft + 10%"})
    perim = sum(2 * (r["length_ft"] + r["width_ft"]) for r in rooms)
    extra = intake.get("counts") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError:
            extra = {}
    n_doors = int(intake.get("door_count") or extra.get("door_count") or 0)
    n_wins = int(intake.get("window_count") or extra.get("window_count") or 0)
    n_baths = int(intake.get("bathroom_count") or extra.get("bathroom_count") or 0)
    paint = perim * height - n_doors * DOOR_OPENING_SQFT - n_wins * WINDOW_OPENING_SQFT
    lines.append({"name": "Wall paint", "spec": "", "unit": "sqft",
                  "quantity": round(max(0, paint), 2), "range": "",
                  "basis": f"perimeter {perim:.0f} ft x {height} ft"
                           f" - {n_doors} doors - {n_wins} windows"})
    for label, n, unit in (("Doors", n_doors, "piece"),
                           ("Windows", n_wins, "piece"),
                           ("Bathroom sets", n_baths, "set")):
        if n > 0:
            lines.append({"name": label, "spec": "", "unit": unit,
                          "quantity": float(n), "range": "",
                          "basis": f"counted from the plan: {n}"})
    with db.connect() as conn:
        conn.execute("DELETE FROM hunt_items WHERE hunt_id = ? AND status = 'boq'",
                     (hunt_id,))
        for ln in lines:
            conn.execute("INSERT INTO hunt_items (hunt_id, name, spec, quantity,"
                         " unit, status) VALUES (?, ?, ?, ?, ?, 'boq')",
                         (hunt_id, ln["name"],
                          json.dumps({"spec": ln["spec"], "range": ln["range"],
                                      "basis": ln["basis"]}),
                          ln["quantity"], ln["unit"]))
        conn.execute("UPDATE hunts SET status = 'boq_ready', approved_at = '',"
                     " approved_by = 0, approved_hash = '' WHERE id = ?",
                     (hunt_id,))
        conn.commit()
    return {"lines": lines, "builtup_sqft": round(builtup, 1),
            "builtup_estimated": estimated, "warning": WARNING}


def set_boq_qty(hunt_id: int, bid: int, name: str, quantity: float) -> None:
    """User edits a row. Editing clears the approval: the screen says why."""
    if quantity < 0:
        raise ValueError("quantity can't be negative")
    with db.connect() as conn:
        h = conn.execute("SELECT status FROM hunts WHERE id = ? AND business_id = ?",
                         (hunt_id, bid)).fetchone()
        if not h or h["status"] not in ("boq_ready", "approved"):
            raise ValueError("no BOQ to edit yet")
        cur = conn.execute("UPDATE hunt_items SET quantity = ? WHERE hunt_id = ?"
                           " AND name = ? AND status = 'boq'",
                           (quantity, hunt_id, name))
        if cur.rowcount == 0:
            raise ValueError("unknown BOQ row")
        conn.execute("UPDATE hunts SET status = 'boq_ready', approved_at = '',"
                     " approved_by = 0, approved_hash = '' WHERE id = ?",
                     (hunt_id,))
        conn.commit()


def boq_csv(lines: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([WARNING])
    w.writerow(["item", "spec", "unit", "quantity", "range", "basis"])
    for ln in lines:
        w.writerow([ln["name"], ln["spec"], ln["unit"],
                    ln["quantity"], ln["range"], ln["basis"]])
    return buf.getvalue()


def boq_lines(hunt_id: int, bid: int) -> list[dict]:
    with db.connect() as conn:
        h = conn.execute("SELECT id FROM hunts WHERE id = ? AND business_id = ?",
                         (hunt_id, bid)).fetchone()
        if not h:
            raise ValueError("unknown hunt")
        rows = conn.execute("SELECT name, spec, quantity, unit FROM hunt_items"
                            " WHERE hunt_id = ? AND status = 'boq' ORDER BY id",
                            (hunt_id,)).fetchall()
    out = []
    for r in rows:
        try:
            spec = json.loads(r["spec"] or "{}")
        except ValueError:
            spec = {}
        out.append({"name": r["name"], "spec": spec.get("spec", ""),
                    "unit": r["unit"], "quantity": r["quantity"],
                    "range": spec.get("range", ""), "basis": spec.get("basis", "")})
    return out


def routes(app, *, require_api_key, need_login, api_error) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse, PlainTextResponse

    @app.post("/api/hunts/{hunt_id}/boq")
    async def make_boq(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            return build_boq(hunt_id, u["business_id"])
        except ValueError as e:
            return api_error("invalid", str(e), 422)

    @app.patch("/api/hunts/{hunt_id}/boq")
    async def edit_boq(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            body = await request.json()
            set_boq_qty(hunt_id, u["business_id"], body.get("name") or "",
                        float(body.get("quantity")))
        except (ValueError, TypeError) as e:
            return api_error("invalid", str(e), 422)
        return {"ok": True}

    @app.get("/api/hunts/{hunt_id}/boq.csv")
    async def download_boq(hunt_id: int, request: Request):
        if denied := require_api_key(request):
            return denied
        u, err = need_login(request)
        if err:
            return err
        try:
            lines = boq_lines(hunt_id, u["business_id"])
        except ValueError as e:
            return api_error("not_found", str(e), 404)
        if not lines:
            return api_error("not_found", "no BOQ yet", 404)
        return PlainTextResponse(boq_csv(lines), media_type="text/csv")


# ---- selfcheck: offline, hand-worked arithmetic ----

def selfcheck() -> None:
    """Worked example checked by hand; gates; wastage; openings; CSV warning."""
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    old = db.DB_PATH
    db.DB_PATH = Path(tmp) / "t.db"
    try:
        db.init_db()
        import hunt
        hunt.init_db()
        with db.connect() as conn:
            conn.execute("INSERT INTO businesses (slug, name) VALUES ('a','A')")
            # hunt 1: rooms confirmed, built-up given
            conn.execute("INSERT INTO hunts (business_id, flow, status, spot)"
                         " VALUES (1, 'construction', 'rooms_confirmed', ?)",
                         (json.dumps({"floor_height_ft": 10,
                                      "builtup_sqft": "500",
                                      "counts": {"door_count": 2,
                                                 "window_count": 3,
                                                 "bathroom_count": 1}}),))
            for name, ln, wd in (("Living", 14, 12), ("Bath", 7, 5)):
                conn.execute("INSERT INTO hunt_items (hunt_id, name, spec, unit, status)"
                             " VALUES (1, ?, ?, 'ft', 'room')",
                             (name, json.dumps({"length": ln, "width": wd,
                                                 "unit": "ft"})))
            # hunt 2: still awaiting rooms -> BOQ refused
            conn.execute("INSERT INTO hunts (business_id, flow, status)"
                         " VALUES (1, 'construction', 'awaiting_rooms')")
            conn.commit()
        try:
            build_boq(2, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("BOQ before room check allowed")
        r = build_boq(1, 1)
        got = {ln["name"]: ln["quantity"] for ln in r["lines"]}
        # by hand: cement 500*0.45*1.075=241.875; steel 500*4*1.075=2150
        assert abs(got["Cement"] - 241.875) < 0.01, got
        assert got["TMT steel"] == 2150.0, got
        assert got["Aggregate"] == 500 * 1.5 * 1.075, got
        assert WHOLE_BUILDING["Aggregate"] == ("cft", 1.5, 1.0, 2.0)
        assert got["Bricks"] == 500 * 9 * 1.075, got
        # tiles (168+35)*1.1=223.3; paint (52+24)*10-2*21-3*12=682
        assert got["Floor tiles"] == 223.3, got
        assert got["Wall paint"] == 682.0, got
        assert got["Doors"] == 2 and got["Bathroom sets"] == 1, got
        assert r["builtup_estimated"] is False
        assert r["warning"].startswith("Estimate from thumb rules")
        # estimated built-up when missing: (168+35)*1.2=243.6
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET spot = ? WHERE id = 1",
                         (json.dumps({"floor_height_ft": 10,
                                      "counts": {"door_count": 0,
                                                 "window_count": 0,
                                                 "bathroom_count": 0}}),))
            conn.commit()
        r2 = build_boq(1, 1)
        assert r2["builtup_sqft"] == 243.6 and r2["builtup_estimated"] is True, r2
        assert "Doors" not in {ln["name"] for ln in r2["lines"]}
        # metres convert: 3m x 4m room = 9.84ft x 13.12ft
        assert abs(_to_ft(3, "m") - 9.84252) < 0.001
        # csv carries the warning, no rates
        out = boq_csv(r["lines"])
        assert out.splitlines()[0].startswith("Estimate from thumb rules"), out[:80]
        assert "Cement" in out and "241" in out
        # edit clears approval
        with db.connect() as conn:
            conn.execute("UPDATE hunts SET status = 'approved', approved_at = 'x',"
                         " approved_hash = 'h' WHERE id = 1")
            conn.commit()
        set_boq_qty(1, 1, "Cement", 200)
        with db.connect() as conn:
            h = conn.execute("SELECT status, approved_hash FROM hunts WHERE id = 1"
                             ).fetchone()
            assert h["status"] == "boq_ready" and h["approved_hash"] == "", dict(h)
            assert conn.execute("SELECT quantity FROM hunt_items WHERE hunt_id = 1"
                                " AND name = 'Cement'").fetchone()["quantity"] == 200
        try:
            set_boq_qty(1, 1, "Nope", 1)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown row edited")
    finally:
        db.DB_PATH = old
    print("boq selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python boq.py selfcheck")
