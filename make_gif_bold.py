"""
Bold RAG pipeline GIF — large colourful icons, large type.

    pip install pillow
    python make_gif_bold.py
    python make_gif_bold.py --sub 4 --ms 110     # smoother
"""

import argparse
import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install pillow")

W, H = 1400, 880
OUT = Path(__file__).resolve().parent

BG    = "#F2F6FB"
CARD  = "#FFFFFF"
INK   = "#22242C"
GREY  = "#AEB8C4"
FAINT = "#E3E9F0"
SHADE = "#DCE4EC"

PINK   = "#E2699B"
AMBER  = "#E7A235"
VIOLET = "#9A6BD8"
TEAL   = "#2AAE9E"
RED    = "#E05C5C"
BLUE   = "#3D87D6"
GREEN  = "#37A76B"
ORANGE = "#F08A3C"

BOLD = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
MONO = [r"C:\Windows\Fonts\consolab.ttf", r"C:\Windows\Fonts\consola.ttf"]


def font(size, mono=False):
    for p in (MONO if mono else BOLD) + [r"C:\Windows\Fonts\arial.ttf"]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# ------------------------------------------------------------------ icons
def i_docs(d, x, y, s, c):
    d.rounded_rectangle([x + 8, y + 4, x + s - 14, y + s - 10], 6,
                        fill="#FFFFFF", outline=c, width=5)
    d.rounded_rectangle([x, y + 12, x + s - 22, y + s], 6,
                        fill=c + "" if False else "#FFF0F6", outline=c, width=5)
    for i in range(3):
        d.line([x + 10, y + 28 + i * 13, x + s - 32, y + 28 + i * 13],
               fill=c, width=4)


def i_book(d, x, y, s, c):
    d.rounded_rectangle([x, y + 4, x + s, y + s - 4], 7,
                        fill="#FFF7E8", outline=c, width=5)
    d.line([x + s / 2, y + 4, x + s / 2, y + s - 4], fill=c, width=5)
    for i in range(3):
        d.line([x + 10, y + 20 + i * 13, x + s / 2 - 8, y + 20 + i * 13],
               fill=c, width=4)
        d.line([x + s / 2 + 8, y + 20 + i * 13, x + s - 10, y + 20 + i * 13],
               fill=c, width=4)


def i_cards(d, x, y, s, c):
    for i, off in enumerate((0, 14, 28)):
        d.rounded_rectangle([x, y + off, x + s, y + off + 18], 5,
                            fill="#F6EFFC", outline=c, width=5)


def i_vectors(d, x, y, s, c):
    r = 6
    for row in range(3):
        for col in range(3):
            cx, cy = x + 8 + col * 22, y + 8 + row * 22
            fill = c if (row + col) % 2 == 0 else "#FFFFFF"
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill,
                      outline=c, width=3)


def i_db(d, x, y, s, c):
    h = s - 8
    d.ellipse([x, y, x + s, y + 20], fill="#FDECEC", outline=c, width=5)
    d.rectangle([x, y + 10, x + s, y + h - 10], fill="#FDECEC")
    d.line([x, y + 10, x, y + h - 10], fill=c, width=5)
    d.line([x + s, y + 10, x + s, y + h - 10], fill=c, width=5)
    for off in (h * .38, h * .66):
        d.arc([x, y + off - 10, x + s, y + off + 10], 0, 180, fill=c, width=5)
    d.ellipse([x, y + h - 20, x + s, y + h], fill="#FDECEC", outline=c, width=5)
    d.arc([x, y + h - 20, x + s, y + h], 0, 180, fill=c, width=5)


def i_person(d, x, y, s, c):
    d.ellipse([x + 2, y + 2, x + s - 2, y + s - 2], fill="#EAF2FC",
              outline=c, width=5)
    cx = x + s / 2
    d.ellipse([cx - 12, y + 14, cx + 12, y + 38], fill=c)
    d.pieslice([cx - 22, y + 40, cx + 22, y + 84], 180, 360, fill=c)


def i_search(d, x, y, s, c):
    r = s * .34
    cx, cy = x + r + 6, y + r + 6
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#EAF2FC",
              outline=c, width=6)
    d.line([cx + r * .7, cy + r * .7, x + s, y + s], fill=c, width=8)
    d.line([cx - 9, cy, cx + 9, cy], fill=c, width=4)
    d.line([cx, cy - 9, cx, cy + 9], fill=c, width=4)


def i_pages(d, x, y, s, c):
    d.rounded_rectangle([x + 12, y, x + s, y + s - 12], 6,
                        fill="#FFFFFF", outline=c, width=5)
    d.rounded_rectangle([x, y + 12, x + s - 12, y + s], 6,
                        fill="#EBF7F0", outline=c, width=5)
    for i in range(3):
        d.line([x + 10, y + 26 + i * 13, x + s - 22, y + 26 + i * 13],
               fill=c, width=4)


def i_prompt(d, x, y, s, c):
    d.rounded_rectangle([x, y, x + s - 14, y + s], 6,
                        fill="#F6EFFC", outline=c, width=5)
    for i in range(3):
        d.line([x + 10, y + 16 + i * 14, x + s - 26, y + 16 + i * 14],
               fill=c, width=4)
    cx, cy = x + s - 12, y + s - 12
    d.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], fill="#FFFFFF",
              outline=c, width=5)
    d.line([cx - 7, cy, cx + 7, cy], fill=c, width=5)
    d.line([cx, cy - 7, cx, cy + 7], fill=c, width=5)


def i_brain(d, x, y, s, c):
    """Circuit brain: two lobes plus nodes and traces."""
    d.ellipse([x, y + 4, x + s * .62, y + s], fill="#FFF3E8", outline=c, width=5)
    d.ellipse([x + s * .38, y + 4, x + s, y + s], fill="#FFF3E8",
              outline=c, width=5)
    cx, cy = x + s / 2, y + s / 2 + 2
    d.line([cx, y + 14, cx, y + s - 14], fill=c, width=4)
    for dx in (-1, 1):
        d.line([cx, cy - 16, cx + dx * 22, cy - 16], fill=c, width=4)
        d.line([cx, cy + 14, cx + dx * 26, cy + 14], fill=c, width=4)
        d.line([cx + dx * 22, cy - 16, cx + dx * 22, cy - 30], fill=c, width=4)
        for px, py in ((cx + dx * 22, cy - 30), (cx + dx * 26, cy + 14)):
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=c)
    d.ellipse([cx - 7, y + 8, cx + 7, y + 22], fill=c)
    d.ellipse([cx - 7, y + s - 22, cx + 7, y + s - 8], fill=c)


def i_check(d, x, y, s, c):
    d.ellipse([x, y, x + s, y + s], fill="#E8F6EE", outline=c, width=6)
    d.line([x + s * .26, y + s * .52, x + s * .44, y + s * .70], fill=c, width=9)
    d.line([x + s * .44, y + s * .70, x + s * .76, y + s * .30], fill=c, width=9)


_QF = {}


def i_qmark(d, x, y, s, c):
    """Arcs read as a padlock at this size, so draw a real '?' glyph."""
    d.ellipse([x, y, x + s, y + s], fill="#FDF3E2", outline=c, width=6)
    f = _QF.get(int(s))
    if f is None:
        f = _QF[int(s)] = font(int(s * .78))
    w = d.textlength("?", font=f)
    d.text((x + s / 2 - w / 2, y + s * .06), "?", font=f, fill=c)


# ------------------------------------------------------- nodes and wiring
# x, y, w, h, label, sub, colour, icon, steps
NODES = [
    (60,   100, 240, 168, "Source PDFs", "6,532 files",     PINK,   i_docs,    (0,)),
    (340,  100, 240, 168, "Corpus",      "976 Acts",        AMBER,  i_book,    (1,)),
    (620,  100, 240, 168, "Chunks",      "1 section each",  VIOLET, i_cards,   (2,)),
    (900,  100, 240, 168, "Embeddings",  "3,072-d",         TEAL,   i_vectors, (3,)),

    (1120, 330, 240, 180, "Vector DB",   "cosine top-k",    RED,    i_db,      (3, 6)),

    (60,   330, 240, 168, "Your question", "plain English", BLUE,   i_person,  (4,)),
    (340,  330, 240, 168, "Query vector",  "same model",    BLUE,   i_search,  (5,)),

    (60,   580, 240, 168, "Retrieved",   "statute text",    GREEN,  i_pages,   (6,)),
    (340,  580, 240, 168, "Prompt",      "rules + chunks",  VIOLET, i_prompt,  (7,)),
    (620,  580, 240, 168, "LLM",         "reads them",      ORANGE, i_brain,   (8,)),

    (950,  566, 320, 110, "Cited answer", "12 days, s.60E", GREEN,  i_check,   (9,)),
    (950,  700, 320, 110, "Not found",    "not in the Acts", AMBER, i_qmark,   (9,)),
]

EDGES = [
    ([(300, 184), (336, 184)], 1),
    ([(580, 184), (616, 184)], 2),
    ([(860, 184), (896, 184)], 3),
    ([(1020, 268), (1020, 372), (1116, 372)], 3),
    ([(300, 414), (336, 414)], 5),
    ([(580, 462), (1116, 462)], 6),
    ([(1240, 510), (1240, 542), (150, 542), (150, 576)], 6),
    ([(300, 664), (336, 664)], 7),
    ([(580, 664), (616, 664)], 8),
    ([(860, 664), (900, 664), (900, 621), (946, 621)], 9),
    ([(860, 664), (900, 664), (900, 755), (946, 755)], 9),
]

CAPTIONS = [
    "1  ·  collect every Act from the AGC portal",
    "2  ·  clean and structure them into a corpus",
    "3  ·  cut each Act into its own sections",
    "4  ·  turn each section into a vector, and store it",
    "5  ·  someone asks a question",
    "6  ·  embed the question, find the nearest sections",
    "7  ·  pull back the closest statute text",
    "8  ·  build the prompt: rules + sections + question",
    "9  ·  the model reads them — it never recalls from memory",
    "10  ·  answer with the section, or say it isn't there",
]


def badge(d, cx, cy, n, f):
    d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill="#FFE9A8",
              outline="#D69A22", width=6)
    w = d.textlength(n, font=f)
    d.text((cx - w / 2, cy - 22), n, font=f, fill="#8A6210")


def arrow(d, pts, colour, width):
    d.line(pts, fill=colour, width=width, joint="curve")
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    s = 15
    a = math.atan2(y2 - y1, x2 - x1)
    d.polygon([(x2, y2),
               (x2 - s * math.cos(a - .45), y2 - s * math.sin(a - .45)),
               (x2 - s * math.cos(a + .45), y2 - s * math.sin(a + .45))],
              fill=colour)


def point_on(pts, t):
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    lens = [math.dist(a, b) for a, b in segs]
    total = sum(lens) or 1
    want = t * total
    for (a, b), L in zip(segs, lens):
        if want <= L:
            f = want / L if L else 0
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        want -= L
    return pts[-1]


def render(step, sub, n_sub, F):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    phase = sub / n_sub

    d.rounded_rectangle([22, 22, W - 22, H - 22], 26, fill=CARD,
                        outline="#CBD8E6", width=4)
    d.text((56, 40), "Malaysia Law RAG", font=F["h1"], fill=INK)
    # Beside the title, not under it — row 1 starts at y=100.
    d.text((520, 56), "how a question becomes a citation",
           font=F["h2"], fill=GREY)

    for pts, s in EDGES:
        live = (s == step)
        arrow(d, pts, INK if live else FAINT, 7 if live else 5)
        if live:
            px, py = point_on(pts, phase)
            d.ellipse([px - 13, py - 13, px + 13, py + 13],
                      fill="#FFE9A8", outline="#D69A22", width=4)

    badged = False
    for x, y, w, h, label, sub_t, colour, icon, steps in NODES:
        live = (step in steps)
        bob = math.sin(phase * 2 * math.pi + x * .01) * (4 if live else 0)
        g = 8 if live else 0
        bx, by, bw, bh = x - g, y + bob - g, w + g * 2, h + g * 2

        d.rounded_rectangle([bx + 6, by + 8, bx + bw + 6, by + bh + 8], 20,
                            fill=SHADE)
        # Icons and labels keep their colour whether or not the step is
        # active; only the border weight and a highlight tint change. Greying
        # them out made three-quarters of the frame look switched off.
        d.rounded_rectangle([bx, by, bx + bw, by + bh], 20, fill=CARD,
                            outline=colour, width=8 if live else 4)

        if h > 130:                       # tall card: icon above the words
            icon(d, bx + bw / 2 - 38, by + 18, 76, colour)
            ty = by + 108
            tw = d.textlength(label, font=F["t"])
            d.text((bx + bw / 2 - tw / 2, ty), label, font=F["t"], fill=INK)
            sw = d.textlength(sub_t, font=F["s"])
            d.text((bx + bw / 2 - sw / 2, ty + 38), sub_t, font=F["s"],
                   fill=colour)
        else:                             # wide card: icon beside the words
            icon(d, bx + 22, by + bh / 2 - 32, 64, colour)
            d.text((bx + 110, by + 22), label, font=F["t"], fill=INK)
            d.text((bx + 110, by + 62), sub_t, font=F["s"], fill=colour)

        # Step 10 lights two cards; one badge is enough, and a second would
        # sit on the arrow junction between them.
        if live and not badged:
            badge(d, bx - 4, by - 4, str(step + 1), F["t"])
            badged = True

    d.text((56, H - 76), CAPTIONS[step], font=F["cap"], fill=INK)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", type=int, default=3)
    ap.add_argument("--ms", type=int, default=150)
    args = ap.parse_args()

    F = dict(h1=font(46), h2=font(24), t=font(31), s=font(20, mono=True),
             cap=font(27))

    frames, durations = [], []
    for step in range(10):
        for sub in range(args.sub):
            frames.append(render(step, sub, args.sub, F))
            durations.append(args.ms)
        durations[-1] = args.ms + 420

    path = OUT / "rag_pipeline_bold.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    print("wrote %s  (%d frames, %.0f KB)"
          % (path, len(frames), path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
