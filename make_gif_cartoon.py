"""
Cartoon version of the RAG pipeline GIF.

Hand-drawn feel: outlines are re-jittered every frame so the lines "boil"
the way inked animation does, nodes bob on a sine, the active step scales up
with sparkles, and a packet travels the live edge.

    pip install pillow
    python make_gif_cartoon.py
    python make_gif_cartoon.py --sub 4 --ms 100    # smoother, bigger file
"""

import argparse
import math
import random
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install pillow")

W, H = 1060, 700
OUT = Path(__file__).resolve().parent

BG     = "#EAF3F7"
PAPER  = "#FFFFFF"
INK    = "#2B2B33"
SHADOW = "#C9D8E0"
GREY   = "#9FB2BD"

CORAL  = "#FF8D70"
YELLOW = "#FFD166"
TEAL   = "#4EC5B5"
BLUE   = "#7FB2EE"
LILAC  = "#B69CE9"
MINT   = "#8FD9A7"
PINK   = "#F4A0C4"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\comicbd.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]


def font(size, mono=False):
    paths = ([r"C:\Windows\Fonts\consolab.ttf", r"C:\Windows\Fonts\consola.ttf"]
             if mono else FONT_CANDIDATES)
    for p in paths + [r"C:\Windows\Fonts\arial.ttf"]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# x, y, w, h, label, sub, colour, face, steps active
NODES = [
    (40,  84,  160, 100, "PDFs",        "6,532 files",      CORAL,  "sleepy", (0,)),
    (230, 84,  160, 100, "Corpus",      "976 Acts",         YELLOW, None,     (1,)),
    (420, 84,  160, 100, "Chunks",      "1 section each",   PINK,   None,     (2,)),
    (610, 84,  160, 100, "Embeddings",  "3,072-d vectors",  LILAC,  None,     (3,)),
    (812, 196, 196, 150, "VECTOR DB",   "cosine top-k",     TEAL,   "happy",  (3, 6)),
    (40,  300, 160, 100, "You",         "a question",       BLUE,   "ask",    (4,)),
    (230, 300, 160, 100, "Query vector","same model",       BLUE,   None,     (5,)),
    (40,  470, 160, 100, "Retrieved",   "statute text",     MINT,   None,     (6,)),
    (230, 470, 180, 100, "Prompt",      "rules + chunks",   LILAC,  None,     (7,)),
    (440, 470, 160, 100, "LLM",         "reads them",       CORAL,  "robot",  (8,)),
    (648, 438, 210, 72,  "Cited!",      "12 days, s.60E",   MINT,   None,     (9,)),
    (648, 534, 210, 72,  "Nope",        "not in Acts",      YELLOW, "shrug",  (9,)),
]

EDGES = [
    ([(200, 134), (224, 134)], 1),
    ([(390, 134), (414, 134)], 2),
    ([(580, 134), (604, 134)], 3),
    ([(690, 184), (690, 252), (806, 252)], 3),
    ([(200, 350), (224, 350)], 5),
    ([(390, 350), (700, 350), (700, 312), (806, 312)], 6),
    ([(910, 346), (910, 424), (120, 424), (120, 466)], 6),
    ([(200, 520), (224, 520)], 7),
    ([(410, 520), (434, 520)], 8),
    ([(600, 520), (624, 520), (624, 474), (644, 474)], 9),
    ([(600, 520), (624, 520), (624, 570), (644, 570)], 9),
]

CAPTIONS = [
    "1 — grab every Act from the AGC website",
    "2 — clean them up into a corpus",
    "3 — cut each Act into its own sections",
    "4 — turn each section into numbers, and store them",
    "5 — someone asks a question",
    "6 — turn the question into numbers too",
    "7 — grab the closest-matching sections",
    "8 — stuff them into the prompt with the rules",
    "9 — the model reads them. It never guesses from memory",
    "10 — answer with the section, or admit it isn't there",
]


def wobbly(x, y, w, h, r, jitter, rng):
    """Rounded-rect outline with per-point noise, for a hand-inked look."""
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                       (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(7):
            a = math.radians(a0 + i * 15)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return [(px + rng.uniform(-jitter, jitter), py + rng.uniform(-jitter, jitter))
            for px, py in pts]


def blob(d, pts, fill, width=5):
    d.polygon(pts, fill=fill)
    d.line(pts + [pts[0]], fill=INK, width=width, joint="curve")


def face(d, kind, cx, cy, blink):
    if kind is None:
        return
    ew = 4
    if kind == "robot":
        d.rectangle([cx - 19, cy - 6, cx - 7, cy + 4], fill=INK)
        d.rectangle([cx + 7, cy - 6, cx + 19, cy + 4], fill=INK)
        d.line([cx - 10, cy + 13, cx + 10, cy + 13], fill=INK, width=4)
        d.line([cx, cy - 18, cx, cy - 26], fill=INK, width=3)
        d.ellipse([cx - 4, cy - 33, cx + 4, cy - 25], fill=INK)
        return
    if blink:
        d.line([cx - 20, cy, cx - 8, cy], fill=INK, width=ew)
        d.line([cx + 8, cy, cx + 20, cy], fill=INK, width=ew)
    else:
        d.ellipse([cx - 20, cy - 7, cx - 10, cy + 5], fill=INK)
        d.ellipse([cx + 10, cy - 7, cx + 20, cy + 5], fill=INK)
    if kind == "sleepy":
        d.arc([cx - 12, cy + 6, cx + 12, cy + 22], 200, 340, fill=INK, width=4)
    elif kind == "shrug":
        d.line([cx - 10, cy + 16, cx + 10, cy + 12], fill=INK, width=4)
    elif kind == "ask":
        d.arc([cx - 13, cy + 4, cx + 13, cy + 24], 0, 180, fill=INK, width=4)
    else:
        d.arc([cx - 15, cy + 2, cx + 15, cy + 24], 0, 180, fill=INK, width=5)


def sparkle(d, cx, cy, r, colour):
    for a in range(0, 360, 60):
        rad = math.radians(a)
        x1, y1 = cx + r * .55 * math.cos(rad), cy + r * .55 * math.sin(rad)
        x2, y2 = cx + r * math.cos(rad), cy + r * math.sin(rad)
        d.line([x1, y1, x2, y2], fill=colour, width=4)


def arrow(d, pts, colour, width, rng, jitter):
    j = [(px + rng.uniform(-jitter, jitter), py + rng.uniform(-jitter, jitter))
         for px, py in pts]
    d.line(j, fill=colour, width=width, joint="curve")
    (x1, y1), (x2, y2) = j[-2], j[-1]
    s = 11
    ang = math.atan2(y2 - y1, x2 - x1)
    d.polygon([
        (x2, y2),
        (x2 - s * math.cos(ang - .5), y2 - s * math.sin(ang - .5)),
        (x2 - s * math.cos(ang + .5), y2 - s * math.sin(ang + .5)),
    ], fill=colour)


def point_on(pts, t):
    """Position a fraction t along a polyline."""
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


def render(step, sub, n_sub, f_h1, f_t, f_s, f_cap):
    rng = random.Random(step * 97 + sub * 13)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    blob(d, wobbly(20, 20, W - 40, H - 40, 26, 1.4, rng), PAPER, 6)
    d.text((52, 40), "How the Malaysia Law bot answers you", font=f_h1, fill=INK)

    phase = sub / n_sub
    blink = (step % 3 == 0 and sub == 1)

    for pts, s in EDGES:
        live = (s == step)
        arrow(d, pts, INK if live else GREY, 6 if live else 4, rng,
              2.2 if live else 1.2)
        if live:
            px, py = point_on(pts, phase)
            d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=YELLOW, outline=INK, width=3)

    for x, y, w, h, label, sub_t, colour, fc, steps in NODES:
        live = (step in steps)
        bob = math.sin(phase * 2 * math.pi + x * .01) * (5 if live else 2)
        grow = 6 if live else 0
        bx, by = x - grow, y + bob - grow
        bw, bh = w + grow * 2, h + grow * 2

        d.polygon(wobbly(bx + 7, by + 9, bw, bh, 18, 1.0, random.Random(1)),
                  fill=SHADOW)
        if live:
            sparkle(d, bx + bw - 6, by + 2, 20, YELLOW)
            sparkle(d, bx + 4, by + bh - 2, 15, YELLOW)
        blob(d, wobbly(bx, by, bw, bh, 18, 2.0 if live else 1.2, rng),
             colour if live else PAPER, 6 if live else 4)

        cx = bx + bw / 2
        # Test the declared height, not the grown one: an active box swells by
        # 12px, which would otherwise flip a short box into the tall layout
        # and clip its sub-label.
        if fc and h <= 80:
            # Short box: face sits beside the words, never above them.
            face(d, fc, bx + 36, by + bh / 2 - 4, blink)
            d.text((bx + 72, by + 14), label, font=f_t, fill=INK)
            d.text((bx + 72, by + 42), sub_t, font=f_s,
                   fill=INK if live else GREY)
        else:
            if fc:
                face(d, fc, cx, by + 28, blink)
                ty = by + 52
            else:
                ty = by + (30 if bh > 80 else 16)
            tw = d.textlength(label, font=f_t)
            d.text((cx - tw / 2, ty), label, font=f_t, fill=INK)
            sw = d.textlength(sub_t, font=f_s)
            d.text((cx - sw / 2, ty + 25), sub_t, font=f_s,
                   fill=INK if live else GREY)

        if live:
            n = str(step + 1)
            nx, ny = bx - 6, by - 6
            d.ellipse([nx - 21, ny - 21, nx + 21, ny + 21],
                      fill=YELLOW, outline=INK, width=5)
            nw = d.textlength(n, font=f_t)
            d.text((nx - nw / 2, ny - 13), n, font=f_t, fill=INK)

    if step == 4:
        # Sits above "You", clear of the Query-vector node to its right.
        blob(d, wobbly(44, 214, 216, 46, 16, 1.6, rng), PAPER, 5)
        d.polygon([(86, 256), (78, 278), (114, 258)], fill=PAPER, outline=INK, width=4)
        d.text((62, 226), "how much holiday?", font=f_s, fill=INK)

    cap = CAPTIONS[step]
    d.text((52, H - 62), cap, font=f_cap, fill=INK)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", type=int, default=3, help="frames per step")
    ap.add_argument("--ms", type=int, default=150)
    args = ap.parse_args()

    f_h1 = font(30)
    f_t = font(22)
    f_s = font(14, mono=True)
    f_cap = font(20)

    frames, durations = [], []
    for step in range(10):
        for sub in range(args.sub):
            frames.append(render(step, sub, args.sub, f_h1, f_t, f_s, f_cap))
            durations.append(args.ms)
        durations[-1] = args.ms + 380          # beat at the end of each step

    path = OUT / "rag_pipeline_cartoon.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    print("wrote %s  (%d frames, %.0f KB)"
          % (path, len(frames), path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
