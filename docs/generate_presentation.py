"""Generate a concise, professional Revit MCP deck (16:9 widescreen, 6 slides)."""

from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# --- palette ---
NAVY = RGBColor(0x0F, 0x2A, 0x43)
ACCENT = RGBColor(0x1C, 0x8A, 0xC9)
GREEN = RGBColor(0x2E, 0xA8, 0x77)
LIGHT = RGBColor(0xF3, 0xF6, 0xF9)
GRAY = RGBColor(0x5A, 0x6B, 0x7B)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1A, 0x24, 0x2E)
FONT = "Segoe UI"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]


def _set(run, size, color, bold=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def rect(slide, x, y, w, h, fill):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    s.fill.solid(); s.fill.fore_color.rgb = fill
    s.line.fill.background(); s.shadow.inherit = False
    return s


def textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    return tf


def header(slide, title, kicker):
    rect(slide, 0, 0, SW, SH, WHITE)
    rect(slide, 0, 0, Inches(0.28), SH, ACCENT)
    rect(slide, Inches(0.6), Inches(0.55), Inches(1.6), Inches(0.08), ACCENT)
    tf = textbox(slide, Inches(0.6), Inches(0.7), Inches(12.1), Inches(1.3))
    p = tf.paragraphs[0]
    r = p.add_run(); _set(r, 13, ACCENT, bold=True); r.text = kicker.upper()
    p2 = tf.add_paragraph()
    r2 = p2.add_run(); _set(r2, 30, NAVY, bold=True); r2.text = title


def bullets(slide, x, y, w, items, head_size=19):
    body = textbox(slide, x, y, w, Inches(5.0))
    for i, (head, sub) in enumerate(items):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        p.space_after = Pt(11)
        rb = p.add_run(); _set(rb, head_size, INK, bold=True); rb.text = f"▪  {head}"
        if sub:
            r2 = p.add_run(); _set(r2, head_size, GRAY); r2.text = f"  —  {sub}"


# ---------- Slide 1 : Title ----------
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, SW, SH, NAVY)
rect(s, 0, Inches(4.6), SW, Inches(0.10), ACCENT)
tf = textbox(s, Inches(0.9), Inches(2.2), Inches(11.5), Inches(2.4))
p = tf.paragraphs[0]; r = p.add_run(); _set(r, 54, WHITE, bold=True); r.text = "Revit MCP"
p2 = tf.add_paragraph(); r2 = p2.add_run(); _set(r2, 26, ACCENT, bold=True)
r2.text = "Natural-Language BIM Automation"
p3 = tf.add_paragraph(); p3.space_before = Pt(10)
r3 = p3.add_run(); _set(r3, 18, RGBColor(0xC7, 0xD6, 0xE2))
r3.text = "Connecting Anthropic Claude to Autodesk Revit"
tf2 = textbox(s, Inches(0.9), Inches(5.0), Inches(11.5), Inches(1.0))
rr = tf2.paragraphs[0].add_run(); _set(rr, 14, RGBColor(0x9F, 0xB3, 0xC4))
rr.text = "Specification-First  •  Safe-by-Design  •  Verified on Revit 2027"

# ---------- Slide 2 : Problem -> Solution (two columns) ----------
s = prs.slides.add_slide(BLANK)
header(s, "The Problem  →  The Solution", "Overview")
# left card (problem)
rect(s, Inches(0.6), Inches(2.0), Inches(5.85), Inches(4.6), LIGHT)
rect(s, Inches(0.6), Inches(2.0), Inches(5.85), Inches(0.6), GRAY)
tf = textbox(s, Inches(0.6), Inches(2.0), Inches(5.85), Inches(0.6), MSO_ANCHOR.MIDDLE)
pr = tf.paragraphs[0]; pr.alignment = PP_ALIGN.CENTER
r = pr.add_run(); _set(r, 16, WHITE, bold=True); r.text = "THE PROBLEM"
bullets(s, Inches(0.85), Inches(2.8), Inches(5.4), [
    ("Easy to say, slow to do", "intent is one sentence; Revit is many clicks"),
    ("Manual & repetitive", "type, level, exact coordinates — per element"),
    ("No network API", "an AI model can't touch the model on its own")], head_size=16)
# right card (solution)
rect(s, Inches(6.9), Inches(2.0), Inches(5.85), Inches(4.6), RGBColor(0xEA, 0xF3, 0xEF))
rect(s, Inches(6.9), Inches(2.0), Inches(5.85), Inches(0.6), GREEN)
tf = textbox(s, Inches(6.9), Inches(2.0), Inches(5.85), Inches(0.6), MSO_ANCHOR.MIDDLE)
pr = tf.paragraphs[0]; pr.alignment = PP_ALIGN.CENTER
r = pr.add_run(); _set(r, 16, WHITE, bold=True); r.text = "THE SOLUTION"
bullets(s, Inches(7.15), Inches(2.8), Inches(5.4), [
    ("Describe it in plain English", "“a 4 m wall on L2 with a door”"),
    ("It places real BIM elements", "grounded in your actual model"),
    ("Safe by default", "preview, confirm, one-click undo")], head_size=16)

# ---------- Slide 3 : Architecture ----------
s = prs.slides.add_slide(BLANK)
header(s, "How It Works", "Architecture")
boxes = [("Claude", "the brain", NAVY), ("MCP Server", "Python • tools", ACCENT),
         ("Revit Add-in", "C# • UI bridge", NAVY), ("Revit Model", "walls, doors…", GREEN)]
bx, by, bw, bh, gap = Inches(0.7), Inches(2.9), Inches(2.7), Inches(1.7), Inches(0.42)
for i, (t, sub, col) in enumerate(boxes):
    x = bx + i * (bw + gap)
    rect(s, x, by, bw, bh, col)
    tf = textbox(s, x, by, bw, bh, MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); _set(r, 19, WHITE, bold=True); r.text = t
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run(); _set(r2, 12, RGBColor(0xDC, 0xE7, 0xF0)); r2.text = sub
    if i < 3:
        ar = textbox(s, x + bw, by, gap, bh, MSO_ANCHOR.MIDDLE)
        pa = ar.paragraphs[0]; pa.alignment = PP_ALIGN.CENTER
        ra = pa.add_run(); _set(ra, 22, ACCENT, bold=True); ra.text = "➔"
cap = textbox(s, Inches(0.7), Inches(5.0), Inches(11.9), Inches(1.2))
rc = cap.paragraphs[0].add_run(); _set(rc, 15, GRAY)
rc.text = ("MCP over stdio  •  localhost-only socket + token  •  every Revit API call "
           "marshalled onto Revit’s UI thread via an ExternalEvent")

# ---------- Slide 4 : Safety model ----------
s = prs.slides.add_slide(BLANK)
header(s, "Safety Model", "Nothing changes without your OK")
steps = [("STAGE", "build a plan"), ("PREVIEW", "read-only check"), ("CONFIRM", "you approve"),
         ("COMMIT", "one transaction"), ("UNDO", "one-click revert")]
sx, sy, sw, sh, g = Inches(0.7), Inches(2.5), Inches(2.18), Inches(1.25), Inches(0.22)
for i, (st, su) in enumerate(steps):
    x = sx + i * (sw + g)
    col = GREEN if st in ("CONFIRM", "UNDO") else ACCENT
    rect(s, x, sy, sw, sh, col)
    tf = textbox(s, x, sy, sw, sh, MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); _set(r, 16, WHITE, bold=True); r.text = st
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run(); _set(r2, 11, RGBColor(0xE7, 0xF1, 0xF7)); r2.text = su
note = textbox(s, Inches(0.7), Inches(4.2), Inches(11.9), Inches(2.6))
for i, t in enumerate([
        "No mutation without an explicit confirmation token",
        "Every batch is one atomic, fully undoable transaction",
        "References resolved against the live model — no hallucinated types or levels",
        "Risky placements roll back cleanly instead of half-applying"]):
    p = note.paragraphs[0] if i == 0 else note.add_paragraph()
    p.space_after = Pt(8)
    rb = p.add_run(); _set(rb, 17, GREEN, bold=True); rb.text = "✓  "
    rt = p.add_run(); _set(rt, 17, INK); rt.text = t

# ---------- Slide 5 : Capabilities + Proven live ----------
s = prs.slides.add_slide(BLANK)
header(s, "What It Can Do — & Proven Live", "Capabilities & Results")
bullets(s, Inches(0.65), Inches(2.05), Inches(12.0), [
    ("Discover", "levels, grids, types, families, existing elements, selection"),
    ("Place", "walls, doors, windows, floors, rooms, and new levels"),
    ("Compose", "hosted doors/windows + whole rooms in one coordinated plan"),
    ("Converse", "plain-English summaries; asks you to choose when ambiguous")])
rect(s, Inches(0.6), Inches(5.55), Inches(12.15), Inches(1.25), NAVY)
tf = textbox(s, Inches(0.85), Inches(5.55), Inches(11.7), Inches(1.25), MSO_ANCHOR.MIDDLE)
p = tf.paragraphs[0]
r = p.add_run(); _set(r, 15, WHITE, bold=True); r.text = "PROVEN LIVE on Revit 2027:  "
r2 = p.add_run(); _set(r2, 15, RGBColor(0xC7, 0xD6, 0xE2))
r2.text = "wall + hosted door in one plan • 4-wall room + floor + door (atomic undo) • 6/6 resilience + 14 unit tests"

# ---------- Slide 6 : Roadmap + Closing ----------
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, SW, SH, NAVY)
rect(s, Inches(0.9), Inches(1.35), Inches(1.8), Inches(0.08), ACCENT)
tf = textbox(s, Inches(0.9), Inches(0.7), Inches(11.5), Inches(0.9))
r = tf.paragraphs[0].add_run(); _set(r, 30, WHITE, bold=True); r.text = "Roadmap & What’s Next"
body = textbox(s, Inches(0.9), Inches(1.8), Inches(11.5), Inches(3.0))
for i, (h, sub) in enumerate([
        ("Commit robustness", "auto-handle Revit dialogs so placement never stalls"),
        ("Colour & appearance", "“recolour the building in 3D” via view overrides"),
        ("DWG → 3D", "build the model from a 2D plan drawing"),
        ("More disciplines", "structural & MEP; multi-version Revit support")]):
    p = body.paragraphs[0] if i == 0 else body.add_paragraph()
    p.space_after = Pt(9)
    rb = p.add_run(); _set(rb, 18, ACCENT, bold=True); rb.text = f"▪  {h}"
    rt = p.add_run(); _set(rt, 18, RGBColor(0xD6, 0xE2, 0xEC)); rt.text = f"  —  {sub}"
tf3 = textbox(s, Inches(0.9), Inches(5.5), Inches(11.5), Inches(1.4))
r = tf3.paragraphs[0].add_run(); _set(r, 26, WHITE, bold=True); r.text = "From words to BIM — safely."
p2 = tf3.add_paragraph(); p2.space_before = Pt(8)
r2 = p2.add_run(); _set(r2, 14, RGBColor(0x9F, 0xB3, 0xC4))
r2.text = "github.com/Lalitchitoshiya/Revit-MCP"

out = r"d:\Revit MCP\docs\Revit-MCP-Presentation.pptx"
prs.save(out)
print("Saved:", out, "| slides:", len(prs.slides._sldIdLst))
