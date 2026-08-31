"""
Render the RAG pipeline as an animated GIF.

Draws the diagram frame by frame and lights each step in turn, so the file
can be dropped straight into slides or chat.

    pip install pillow
    python make_gif.py            -> rag_pipeline.gif
    python make_gif.py --dark     -> dark background variant
"""

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install pillow")

W, H = 1240, 760
OUT = Path(__file__).resolve().parent

LIGHT = dict(
    bg="#F4F6F8", panel="#FFFFFF", ink="#161A24", muted="#6B7482",
    rule="#D8DDE5", dim="#B9C1CC",
    src_f="#EDF1F6", src_s="#64748B",
    db_f="#FAF0DC",  db_s="#B07818",
    qry_f="#E6F0FB", qry_s="#2C6BB0",
    gen_f="#EFEAFA", gen_s="#6B4FBB",
    ok_f="#E4F2EA",  ok_s="#2C7A52",
    no_f="#FBEAE7",  no_s="#B0453C",
    badge_f="#FBEFD2", badge_s="#C08A22",
    glow="#F2C46A",
)
DARK = dict(
    bg="#0E1116", panel="#161A21", ink="#E4E8EF", muted="#8D96A6",
    rule="#29303B", dim="#3A4351",
    src_f="#1B212B", src_s="#93A0B4",
    db_f="#2C2214",  db_s="#D9A25C",
    qry_f="#15233A", qry_s="#7FB0EC",
    gen_f="#221C36", gen_s="#A991E8",
    ok_f="#13251B",  ok_s="#6FC49B",
    no_f="#2B1816",  no_s="#E08A83",
    badge_f="#3A2E16", badge_s="#D9A25C",
    glow="#D9A25C",
)

FONTS = [
    r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\consola.ttf",
]


def font(path_idx, size):
    for p in (FONTS[path_idx], r"C:\Windows\Fonts\arialbd.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# node: (x, y, w, h, title, sub, palette-key, steps-it-is-active-for)
# Steps are 0-indexed here and displayed as step+1. The vector database is
# active twice -- written at step 4, read at step 7 -- so steps is a tuple.
NODES = [
    (60,  92,  190, 104, "Source PDFs",      "6,532 files · 12.4 GB",  "src", (0,)),
    (312, 92,  190, 104, "Corpus",           "976 Acts · 32,387 secs", "src", (1,)),
    (564, 92,  190, 104, "Chunks",           "1 section · ≤512 tok",   "src", (2,)),
    (816, 92,  190, 104, "Embeddings",       "3,072 dimensions",       "src", (3,)),

    (700, 268, 480, 108, "VECTOR DATABASE",
     "709 docs · cosine top-k · no threshold", "db", (3, 6)),

    (60,  268, 190, 104, "User question",    "“how much holiday…”",    "qry", (4,)),
    (312, 268, 190, 104, "Query embedding",  "same model · 3,072-d",   "qry", (5,)),

    (60,  454, 190, 104, "Retrieved sections", "statute text + cite",  "gen", (6,)),
    (312, 454, 220, 104, "Augmented prompt", "rules + chunks + q",     "gen", (7,)),
    (594, 454, 190, 104, "LLM reads them",   "gemini-3.7-flash",       "gen", (8,)),

    (846, 430, 334, 62,  "Grounded answer",  "“12 days (s.60E)”",      "ok",  (9,)),
    (846, 516, 334, 62,  "Not in the text",  "“I couldn’t find that…”", "no", (9,)),
]

# edges: (points, step-it-belongs-to, label)
EDGES = [
    ([(250, 144), (306, 144)], 1, None),
    ([(502, 144), (558, 144)], 2, None),
    ([(754, 144), (810, 144)], 3, None),
    ([(911, 196), (911, 262)], 3, "store"),
    ([(250, 320), (306, 320)], 5, None),
    ([(502, 320), (694, 320)], 6, "search"),
    ([(940, 376), (940, 412), (155, 412), (155, 448)], 6, "top-k sections"),
    ([(250, 506), (306, 506)], 7, None),
    ([(532, 506), (588, 506)], 8, None),
    ([(784, 506), (816, 506), (816, 461), (840, 461)], 9, "grounded"),
    ([(784, 506), (816, 506), (816, 547), (840, 547)], 9, "not found"),
]

BANDS = [
    (60, 72, "STEPS 1–4  ·  RUNS ONCE, OFFLINE"),
    (60, 248, "STEPS 5–10  ·  EVERY QUESTION"),
]


def blend(c1, c2, t):
    """Mix two hex colours."""
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_icon(d, kind, x, y, colour):
    """Small glyph, drawn from primitives."""
    if kind == "src":
        d.rounded_rectangle([x, y, x + 26, y + 32], 3, outline=colour, width=2)
        for i in range(3):
            d.line([x + 6, y + 10 + i * 7, x + 20, y + 10 + i * 7], fill=colour, width=2)
    elif kind == "db":
        d.ellipse([x, y, x + 34, y + 12], outline=colour, width=2)
        d.line([x, y + 6, x, y + 26], fill=colour, width=2)
        d.line([x + 34, y + 6, x + 34, y + 26], fill=colour, width=2)
        d.ellipse([x, y + 20, x + 34, y + 32], outline=colour, width=2)
    elif kind == "qry":
        d.ellipse([x, y, x + 24, y + 24], outline=colour, width=2)
        d.line([x + 21, y + 21, x + 32, y + 32], fill=colour, width=3)
    elif kind == "gen":
        d.rounded_rectangle([x + 5, y + 5, x + 29, y + 29], 4, outline=colour, width=2)
        for px in (x + 12, x + 22):
            d.line([px, y, px, y + 5], fill=colour, width=2)
            d.line([px, y + 29, px, y + 34], fill=colour, width=2)
        for py in (y + 12, y + 22):
            d.line([x, py, x + 5, py], fill=colour, width=2)
            d.line([x + 29, py, x + 34, py], fill=colour, width=2)
    elif kind == "ok":
        d.line([x + 3, y + 16, x + 12, y + 26], fill=colour, width=3)
        d.line([x + 12, y + 26, x + 29, y + 5], fill=colour, width=3)
    elif kind == "no":
        d.ellipse([x + 2, y + 4, x + 28, y + 30], outline=colour, width=2)
        d.line([x + 15, y + 10, x + 15, y + 20], fill=colour, width=2)
        d.point((x + 15, y + 25), fill=colour)


def arrow(d, pts, colour, width=3):
    d.line(pts, fill=colour, width=width, joint="curve")
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    s = 7
    if x1 == x2:
        dy = s if y2 > y1 else -s
        d.polygon([(x2, y2), (x2 - s, y2 - dy), (x2 + s, y2 - dy)], fill=colour)
    else:
        dx = s if x2 > x1 else -s
        d.polygon([(x2, y2), (x2 - dx, y2 - s), (x2 - dx, y2 + s)], fill=colour)


def render(step, P, f_title, f_sub, f_band, f_badge, f_h1):
    img = Image.new("RGB", (W, H), P["bg"])
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([24, 24, W - 24, H - 24], 18, fill=P["panel"],
                        outline=P["rule"], width=2)
    d.text((60, 40), "Malaysia Law RAG — how a question becomes a citation",
           font=f_h1, fill=P["ink"])

    for bx, by, txt in BANDS:
        d.text((bx, by), txt, font=f_band, fill=P["badge_s"])

    for pts, s, label in EDGES:
        live = (s == step)
        col = P["glow"] if live else P["dim"]
        arrow(d, pts, col, 4 if live else 3)
        if label:
            lx, ly = pts[-1]
            d.text((lx + 10, ly - 20), label, font=f_sub,
                   fill=P["ink"] if live else P["muted"])

    for x, y, w, h, title, sub, key, steps in NODES:
        live = (step in steps)
        fill = P[key + "_f"]
        line = P[key + "_s"]
        if not live:
            fill = "#%02x%02x%02x" % blend(fill, P["panel"], .45)
            line = "#%02x%02x%02x" % blend(line, P["panel"], .5)
        d.rounded_rectangle([x, y, x + w, y + h], 12, fill=fill,
                            outline=line, width=4 if live else 2)

        # Short boxes put the icon beside the text; tall ones put it above.
        if h < 80:
            draw_icon(d, key, x + 14, y + 15, line)
            tx, ty = x + 60, y + 10
        else:
            draw_icon(d, key, x + 16, y + 16, line)
            tx, ty = x + 16, y + 56

        d.text((tx, ty), title, font=f_title,
               fill=P["ink"] if live else P["muted"])
        d.text((tx, ty + 24), sub, font=f_sub,
               fill=P["ink"] if live else P["muted"])

        if live:
            bx, by = x + w - 20, y - 4
            d.ellipse([bx - 19, by - 19, bx + 19, by + 19],
                      fill=P["badge_f"], outline=P["badge_s"], width=3)
            n = str(step + 1)
            tw = d.textlength(n, font=f_badge)
            d.text((bx - tw / 2, by - 12), n, font=f_badge, fill=P["badge_s"])

    caption = [
        "1  collect the Acts", "2  build the corpus", "3  chunk by section",
        "4  embed and store", "5  user asks", "6  embed the query",
        "7  retrieve nearest sections", "8  build the augmented prompt",
        "9  the model reads, it does not recall",
        "10  answer with a citation, or decline",
    ][step]
    d.text((60, H - 62), caption, font=f_title, fill=P["ink"])
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--ms", type=int, default=1100, help="ms per step")
    args = ap.parse_args()

    P = DARK if args.dark else LIGHT
    f_h1 = font(0, 26)
    f_title = font(0, 17)
    f_sub = font(2, 13)
    f_band = font(0, 14)
    f_badge = font(0, 20)

    frames = [render(s, P, f_title, f_sub, f_band, f_badge, f_h1)
              for s in range(10)]

    name = "rag_pipeline_dark.gif" if args.dark else "rag_pipeline.gif"
    path = OUT / name
    durations = [args.ms] * 10
    durations[-1] = args.ms * 2          # hold on the outcome
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    print("wrote %s  (%d frames, %.0f KB)"
          % (path, len(frames), path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
