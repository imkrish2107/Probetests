"""Draw a test floor plan with known room sizes (Pillow, no other deps).

Run: .venv/bin/python backend/boq_test/make_plan.py
Writes backend/boq_test/plan.png and prints the true sizes.
"""
from pathlib import Path

from PIL import Image, ImageDraw

# room: (x_ft, y_ft, w_ft, h_ft) on a 40x30 ft plot; scale 20 px/ft
ROOMS = {
    "Living": (1, 1, 14, 12),
    "Bedroom": (16, 1, 12, 10),
    "Kitchen": (16, 12, 10, 8),
    "Bath": (27, 12, 7, 5),
}
SCALE = 20


def draw(path: Path) -> dict:
    img = Image.new("RGB", (840, 640), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 830, 630], outline="black", width=6)
    true = {}
    for name, (x, y, w, h) in ROOMS.items():
        x0, y0, x1, y1 = (x * SCALE, y * SCALE,
                          (x + w) * SCALE, (y + h) * SCALE)
        d.rectangle([x0, y0, x1, y1], outline="black", width=4)
        d.text((x0 + 12, (y0 + y1) // 2 - 20), name, fill="black")
        d.text((x0 + 12, (y0 + y1) // 2 + 5), f"{w}' x {h}'", fill="black")
        true[name] = (w, h)
    # door gaps: white bars on two walls; windows: double lines on outer wall
    d.rectangle([300, 4, 360, 16], fill="white")
    d.rectangle([600, 624, 660, 636], fill="white")
    for wx in (100, 500, 700):
        d.line([wx, 10, wx + 60, 10], fill="black", width=2)
        d.line([wx, 16, wx + 60, 16], fill="black", width=2)
    img.save(path)
    return true


if __name__ == "__main__":
    out = Path(__file__).with_name("plan.png")
    print(draw(out))
    print(out)
