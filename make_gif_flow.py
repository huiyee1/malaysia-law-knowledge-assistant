"""
Flowing-arrow variant of the bold RAG pipeline GIF.

Everything holds still except the arrows: the whole diagram is drawn at full
colour with all ten step badges visible, and the only thing that moves is the
dash pattern marching along every arrow at once.

The loop is seamless because the dash phase advances exactly one full
dash+gap period across the frame set.

    pip install pillow
    python make_gif_flow.py
    python make_gif_flow.py --frames 16 --ms 70    # smoother, slower flow

Icons and colours are reused from make_gif_bold.py; this file only changes
the layout scale and the arrow rendering.
"""

import argparse
import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install pillow")

from make_gif_bold import (
    font, i_docs, i_book, i_cards, i_vectors, i_db, i_person, i_search,
    i_pages, i_prompt, i_brain, i_check, i_qmark,
    PINK, AMBER, VIOLET, TEAL, RED, BLUE, GREEN, ORANGE,
    BG, CARD, INK, GREY, SHADE,
)

W, H = 1340, 830
OUT = Path(__file__).resolve().parent

DASH, GAP = 11, 9          # dotted-dash pattern
ARROW = "#8E9AAA"

# Boxes are ~15% smaller than the bold version: 200x146 instead of 240x168.
# x, y, w, h, label, sub, colour, icon
NODES = [
    (60,   100, 200, 146, "Source PDFs",   "6,532 files",     PINK,   i_docs),
    (350,  100, 200, 146, "Corpus",        "976 Acts",        AMBER,  i_book),
    (640,  100, 200, 146, "Chunks",        "1 section each",  VIOLET, i_cards),
    (930,  100, 200, 146, "Embeddings",    "3,072-d",         TEAL,   i_vectors),

    (1060, 300, 200, 160, "Vector DB",     "cosine top-k",    RED,    i_db),

    (60,   300, 200, 146, "Your question", "plain English",   BLUE,   i_person),
    (350,  300, 200, 146, "Query vector",  "same model",      BLUE,   i_search),

    (60,   540, 200, 146, "Retrieved",     "statute text",    GREEN,  i_pages),
    (350,  540, 200, 146, "Prompt",        "rules + chunks",  VIOLET, i_prompt),
    (640,  540, 200, 146, "LLM",           "reads them",      ORANGE, i_brain),

    (930,  528, 280, 96,  "Cited answer",  "12 days, s.60E",  GREEN,  i_check),
    (930,  650, 280, 96,  "Not found",     "not in the Acts", AMBER,  i_qmark),
]

# points, badge number (None = no badge), badge position, edge label
EDGES = [
    ([(260, 173), (346, 173)],                              "1",  (303, 173), None),
    ([(550, 173), (636, 173)],                              "2",  (593, 173), None),
    ([(840, 173), (926, 173)],                              "3",  (883, 173), None),
    ([(1030, 246), (1030, 340), (1056, 340)],               "4",  (1030, 288), "store"),
    ([(260, 373), (346, 373)],                              "5",  (303, 373), None),
    ([(550, 402), (1056, 402)],                             "6",  (800, 402), "search"),
    ([(1160, 460), (1160, 500), (150, 500), (150, 536)],    "7",  (660, 500), "top-k sections"),
    ([(260, 613), (346, 613)],                              "8",  (303, 613), None),
    ([(550, 613), (636, 613)],                              "9",  (593, 613), None),
    # No labels on these two: the outcome cards are drawn after the edges and
    # would cover any text placed near their left edge.
    ([(840, 613), (880, 613), (880, 576), (926, 576)],      "10", (885, 613), None),
    ([(840, 613), (880, 613), (880, 698), (926, 698)],      None, None,       None),
]

LEGEND = ("1 collect  ·  2 corpus  ·  3 chunk  ·  4 store  ·  5 ask  ·  "
          "6 embed  ·  7 retrieve  ·  8 prompt  ·  9 read  ·  10 answer or decline")


def measure(pts):
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return segs, [math.dist(a, b) for a, b in segs]


def sub_path(segs, lens, d0, d1):
    """The piece of a polyline between two distances along it."""
    out, acc = [], 0.0
    for (a, b), L in zip(segs, lens):
        s0, s1 = acc, acc + L
        if L and s1 >= d0 and s0 <= d1:
            f0 = max(0.0, (d0 - s0) / L)
            f1 = min(1.0, (d1 - s0) / L)
            p0 = (a[0] + (b[0] - a[0]) * f0, a[1] + (b[1] - a[1]) * f0)
            p1 = (a[0] + (b[0] - a[0]) * f1, a[1] + (b[1] - a[1]) * f1)
            if not out:
                out.append(p0)
            out.append(p1)
        acc = s1
    return out


def dashed_arrow(d, pts, colour, width, phase):
    """Dashes marching along the path; the head stays put."""
    segs, lens = measure(pts)
    total = sum(lens)
    head = 17                       # leave room for the arrowhead
    period = DASH + GAP

    pos = -phase
    while pos < total - head:
        a = max(pos, 0.0)
        b = min(pos + DASH, total - head)
        if b > a:
            piece = sub_path(segs, lens, a, b)
            if len(piece) > 1:
                d.line(piece, fill=colour, width=width, joint="curve")
        pos += period

    (x1, y1), (x2, y2) = segs[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    s = 16
    d.polygon([(x2, y2),
               (x2 - s * math.cos(ang - .42), y2 - s * math.sin(ang - .42)),
               (x2 - s * math.cos(ang + .42), y2 - s * math.sin(ang + .42))],
              fill=colour)


def badge(d, cx, cy, n, f):
    d.ellipse([cx - 25, cy - 25, cx + 25, cy + 25], fill="#FFE9A8",
              outline="#D69A22", width=5)
    w = d.textlength(n, font=f)
    d.text((cx - w / 2, cy - 18), n, font=f, fill="#8A6210")


def render(phase, F):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([20, 20, W - 20, H - 20], 24, fill=CARD,
                        outline="#CBD8E6", width=4)
    d.text((52, 38), "Malaysia Law RAG", font=F["h1"], fill=INK)
    d.text((492, 52), "how a question becomes a citation",
           font=F["h2"], fill=GREY)

    for pts, num, bpos, label in EDGES:
        dashed_arrow(d, pts, ARROW, 5, phase)
        if label:
            lx, ly = pts[-1]
            d.text((lx - 150 if lx > W - 300 else lx + 12, ly - 34),
                   label, font=F["s"], fill=GREY)

    for x, y, w, h, lab, sub, colour, icon in NODES:
        d.rounded_rectangle([x + 5, y + 7, x + w + 5, y + h + 7], 18, fill=SHADE)
        d.rounded_rectangle([x, y, x + w, y + h], 18, fill=CARD,
                            outline=colour, width=5)
        if h > 120:                       # tall card: icon above the words
            icon(d, x + w / 2 - 33, y + 16, 66, colour)
            ty = y + 92
            tw = d.textlength(lab, font=F["t"])
            d.text((x + w / 2 - tw / 2, ty), lab, font=F["t"], fill=INK)
            sw = d.textlength(sub, font=F["s"])
            d.text((x + w / 2 - sw / 2, ty + 33), sub, font=F["s"], fill=colour)
        else:                             # wide card: icon beside the words
            icon(d, x + 20, y + h / 2 - 28, 56, colour)
            d.text((x + 94, y + 20), lab, font=F["t"], fill=INK)
            d.text((x + 94, y + 56), sub, font=F["s"], fill=colour)

    for pts, num, bpos, label in EDGES:
        if num:
            badge(d, bpos[0], bpos[1], num, F["b"])

    d.text((52, H - 62), LEGEND, font=F["cap"], fill=GREY)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=12,
                    help="frames per dash cycle; more = smoother")
    ap.add_argument("--ms", type=int, default=80)
    args = ap.parse_args()

    F = dict(h1=font(42), h2=font(22), t=font(27), s=font(17, mono=True),
             b=font(25), cap=font(16, mono=True))

    period = DASH + GAP
    frames = [render(i * period / args.frames, F) for i in range(args.frames)]

    path = OUT / "rag_pipeline_flow.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=args.ms, loop=0, optimize=True)
    print("wrote %s  (%d frames, %.0f KB)"
          % (path, len(frames), path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
