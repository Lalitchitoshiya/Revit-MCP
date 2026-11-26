"""Regenerate installer/assets/revitmcp.ico (exe, MSI, Apps & features).

    server/.venv/Scripts/python.exe installer/tools/make_icon.py

Placeholder brand mark: blue rounded tile, white "R" with a connector node.
Replace with the final brand icon before store submission (same file name).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "assets" / "revitmcp.ico"
SIZE = 256
BLUE, WHITE = (31, 111, 235, 255), (255, 255, 255, 255)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=52, fill=BLUE)
try:
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 170)
except OSError:
    font = ImageFont.load_default()
d.text((112, 128), "R", font=font, fill=WHITE, anchor="mm")
# connector: line + node at the top right ("talks to Claude")
d.line((168, 88, 206, 50), fill=WHITE, width=14)
d.ellipse((190, 34, 226, 70), fill=WHITE)
img.save(OUT, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
print(f"wrote {OUT}")
