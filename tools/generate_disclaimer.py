"""
Generate StackNote branded disclaimer end card (1080x1920).
Run once: python tools/generate_disclaimer.py
Output: assets/disclaimer.png

Brand kit:
  Background: #1F1F1F  |  Primary green: #39B54A  |  Secondary green: #178A2E
  Headlines: Anton (bold, all caps)  |  Body: Montserrat Medium
  Tagline: "REAL MONEY. REAL TALK. REAL SIMPLE."
           MONEY / TALK / SIMPLE in green
"""

from PIL import Image, ImageDraw, ImageFont
import os

# ── Brand tokens ────────────────────────────────────────────────────────────
BG          = (10, 10, 10)       # near-black
GREEN       = (57, 181, 74)      # #39B54A
GREEN_DARK  = (23, 138, 46)      # #178A2E
WHITE       = (255, 255, 255)
GRAY        = (160, 160, 160)
CHARCOAL    = (31, 31, 31)       # #1F1F1F surface layer

ANTON       = "assets/fonts/Anton-Regular.ttf"
MONTSERRAT  = "assets/fonts/Montserrat-Variable.ttf"

W, H = 1080, 1920

# ── Canvas ───────────────────────────────────────────────────────────────────
img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── Helper: load font with fallback ─────────────────────────────────────────
def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

# ── Green accent bar at top ──────────────────────────────────────────────────
draw.rectangle([(0, 0), (W, 10)], fill=GREEN)

# ── Logo mark: stacked note cards (3 cards, slight offset) ──────────────────
cx, cy = W // 2, 480
cw, ch = 300, 220
r = 20  # corner radius

# Card 3 — dark bottom
draw.rounded_rectangle(
    [(cx - cw//2 + 22, cy - ch//2 + 22), (cx + cw//2 + 22, cy + ch//2 + 22)],
    radius=r, fill=(20, 20, 20), outline=(45, 45, 45), width=2
)
# Card 2 — green middle
draw.rounded_rectangle(
    [(cx - cw//2 + 11, cy - ch//2 + 11), (cx + cw//2 + 11, cy + ch//2 + 11)],
    radius=r, fill=GREEN_DARK, outline=GREEN, width=2
)
# Card 1 — white top
draw.rounded_rectangle(
    [(cx - cw//2, cy - ch//2), (cx + cw//2, cy + ch//2)],
    radius=r, fill=(235, 235, 235), outline=(210, 210, 210), width=1
)

# Dollar sign on top card
f_dollar = font(ANTON, 110)
draw.text((cx, cy), "$", font=f_dollar, fill=(20, 20, 20), anchor="mm")

# ── STACK  NOTE wordmark ─────────────────────────────────────────────────────
f_brand = font(ANTON, 88)
gap = 6
s_bbox = draw.textbbox((0, 0), "STACK", font=f_brand)
n_bbox = draw.textbbox((0, 0), "NOTE",  font=f_brand)
total_w = (s_bbox[2] - s_bbox[0]) + gap + (n_bbox[2] - n_bbox[0])
bx = (W - total_w) // 2
by = 680

draw.text((bx, by), "STACK", font=f_brand, fill=WHITE)
draw.text((bx + (s_bbox[2] - s_bbox[0]) + gap, by), "NOTE", font=f_brand, fill=GREEN)

# ── Tagline: REAL MONEY. REAL TALK. / REAL SIMPLE. ──────────────────────────
# Green on MONEY / TALK / SIMPLE
f_tag = font(MONTSERRAT, 30)

def draw_mixed_line(y, segments):
    """segments: list of (text, color). Rendered inline, centered."""
    total_w = sum(draw.textbbox((0,0), t, font=f_tag)[2] - draw.textbbox((0,0), t, font=f_tag)[0]
                  for t, _ in segments)
    x = (W - total_w) // 2
    for text, color in segments:
        bbox = draw.textbbox((0, 0), text, font=f_tag)
        draw.text((x, y), text, font=f_tag, fill=color)
        x += bbox[2] - bbox[0]

draw_mixed_line(810, [
    ("REAL ", WHITE), ("MONEY", GREEN), (". REAL ", WHITE), ("TALK", GREEN), (".", WHITE)
])
draw_mixed_line(852, [
    ("REAL ", WHITE), ("SIMPLE", GREEN), (".", WHITE)
])

# Thin green separator
draw.rectangle([(W//2 - 40, 900), (W//2 + 40, 906)], fill=GREEN)

# ── NOT FINANCIAL ADVICE header ─────────────────────────────────────────────
f_nfa = font(ANTON, 34)
nfa = "NOT FINANCIAL ADVICE"
nb = draw.textbbox((0, 0), nfa, font=f_nfa)
draw.text(((W - (nb[2]-nb[0])) // 2, 930), nfa, font=f_nfa, fill=GREEN)

# ── Disclaimer body ──────────────────────────────────────────────────────────
f_body = font(MONTSERRAT, 26)
disclaimer_lines = [
    ("This content is for educational and", GRAY),
    ("entertainment purposes only.", GRAY),
    ("", None),
    ("Always do your own research before", GRAY),
    ("making any financial decisions.", GRAY),
    ("", None),
    ("Past performance does not guarantee", GRAY),
    ("future results.", GRAY),
]

dy = 990
for text, color in disclaimer_lines:
    if not text:
        dy += 16
        continue
    bb = draw.textbbox((0, 0), text, font=f_body)
    draw.text(((W - (bb[2]-bb[0])) // 2, dy), text, font=f_body, fill=color)
    dy += 38

# ── Channel info block ───────────────────────────────────────────────────────
f_ch = font(ANTON, 22)
f_handle = font(MONTSERRAT, 24)

# Thin line separator
draw.rectangle([(80, 1290), (W - 80, 1292)], fill=(40, 40, 40))

ch_text = "@StackNote"
cb = draw.textbbox((0, 0), ch_text, font=f_handle)
draw.text(((W - (cb[2]-cb[0])) // 2, 1308), ch_text, font=f_handle, fill=GRAY)

# ── FOLLOW FOR MORE CTA ──────────────────────────────────────────────────────
f_cta = font(ANTON, 48)
cta = "FOLLOW FOR MORE"
cb2 = draw.textbbox((0, 0), cta, font=f_cta)
cw2 = cb2[2] - cb2[0]
cx2 = (W - cw2) // 2
draw.text((cx2, 1660), cta, font=f_cta, fill=WHITE)
# Green underline
draw.rectangle([(cx2, 1716), (cx2 + cw2, 1722)], fill=GREEN)

# Icons row hint (text-based since no SVG renderer)
f_icon_label = font(MONTSERRAT, 22)
topics = ["CREDIT CARDS", "SAVINGS", "DEBT", "INVESTING"]
icon_y = 1760
total_icon_w = sum(
    draw.textbbox((0,0), t, font=f_icon_label)[2] - draw.textbbox((0,0), t, font=f_icon_label)[0] + 30
    for t in topics
) - 30
ix = (W - total_icon_w) // 2
for t in topics:
    bb = draw.textbbox((0, 0), t, font=f_icon_label)
    tw = bb[2] - bb[0]
    draw.text((ix, icon_y), t, font=f_icon_label, fill=GREEN)
    ix += tw + 30

# Dots separator between topics
# (already handled by spacing)

# ── Green accent bar at bottom ───────────────────────────────────────────────
draw.rectangle([(0, H - 10), (W, H)], fill=GREEN)

# ── Save ─────────────────────────────────────────────────────────────────────
os.makedirs("assets", exist_ok=True)
out = "assets/disclaimer.png"
img.save(out, "PNG")
print(f"Saved: {out}  ({os.path.getsize(out)//1024}KB)")
