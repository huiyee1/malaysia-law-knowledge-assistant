"""
Upload the extracted corpus into a Gemini File Search store.

Groups sections.jsonl back into one text file per Act, with an explicit
citation header above every section so the retrieved chunk always carries
its own provenance, then uploads with act-level metadata for filtering.

    pip install google-genai
    set GEMINI_API_KEY=...            (Windows)   export on Linux/macOS

    python ingest.py --acts 265,177   # start narrow: Employment + IR Acts
    python ingest.py                  # everything in sections.jsonl

State is written to corpus/store.json, so re-running resumes rather than
re-uploading (indexing is billed per token, once).
"""

import argparse
import hashlib
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from google import genai
except ImportError:
    sys.exit("Missing dependency. Run:  pip install google-genai")

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
SECTIONS = CORPUS / "sections.jsonl"
ACT_TEXT_DIR = CORPUS / "acts"
STATE = CORPUS / "store.json"

STORE_DISPLAY_NAME = "malaysia-federal-law"
EMBEDDING_MODEL = "models/gemini-embedding-2"

# The API caps max_tokens_per_chunk at 512. The median section is ~172
# tokens, so most survive whole, but 13.8% run longer and get split -- and a
# continuation chunk would otherwise carry no citation. write_act_file works
# around that by repeating the header inside long sections.
CHUNKING = {
    "white_space_config": {
        "max_tokens_per_chunk": 512,
        "max_overlap_tokens": 64,
    }
}

# ~512 tokens of English is roughly 2000 characters; stay under it so a
# repeated header and its text land in the same chunk.
MAX_BLOCK_CHARS = 1500

MAX_RETRIES = 4          # transient 429/5xx across ~700 uploads
UPLOAD_TIMEOUT = 900     # seconds to wait on one document before giving up
DEFAULT_WORKERS = 4      # concurrent uploads


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state):
    CORPUS.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


PRIMARY_CATEGORIES = ("updated", "translated", "revised")


def group_by_act(only_acts=None, categories=PRIMARY_CATEGORIES):
    """Return {act_key: (act_title, category, act_no, [section dicts])}.

    Keyed on category + number + title, not the number alone: amendment Acts
    reuse the principal Act's number in their filename, so grouping by number
    would merge "Employment (Amendment) Act 2022" into "Employment Act 1955"
    and every citation out of that document would be wrong.
    """
    if not SECTIONS.exists():
        sys.exit(f"{SECTIONS} not found. Run build_corpus.py first.")

    acts = defaultdict(list)
    meta = {}
    with SECTIONS.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if categories and r["category"] not in categories:
                continue
            if only_acts and (r["act_no"] or "") not in only_acts:
                continue
            key = f"{r['category']}:{r['act_no']}:{r['act_title']}"
            acts[key].append(r)
            meta[key] = (r["act_title"], r["category"], r["act_no"])

    return {k: (*meta[k], v) for k, v in acts.items()}


def write_act_file(act_key, act_title, sections):
    """One text file per Act; every section prefixed with its citation."""
    ACT_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(act_key))
    # Windows caps a full path at 260 characters, and some Act titles run to
    # 190. Truncate and append a hash so the name stays unique.
    if len(safe) > 80:
        digest = hashlib.sha1(str(act_key).encode("utf-8")).hexdigest()[:8]
        safe = f"{safe[:80]}_{digest}"
    path = ACT_TEXT_DIR / f"{safe}.txt"

    parts = [f"{act_title}\n{'=' * len(act_title)}\n"]
    for s in sections:
        head = f"[{act_title} — s.{s['section_no']}"
        if s["marginal_note"]:
            head += f" — {s['marginal_note']}"
        head += "]"
        if s["part"]:
            head += f"\n({s['part']})"
        for j, block in enumerate(split_blocks(s["text"])):
            tag = head if j == 0 else head.replace("]", " (cont.)]", 1)
            parts.append(f"\n{tag}\n{block}\n")

    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def split_blocks(text, limit=MAX_BLOCK_CHARS):
    """Break a long section on paragraph boundaries so each piece can carry
    its own citation header. Short sections pass through untouched."""
    if len(text) <= limit:
        return [text]

    blocks, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > limit:
            blocks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        blocks.append(buf)

    # A single paragraph longer than the limit still has to be cut.
    out = []
    for b in blocks:
        while len(b) > limit:
            cut = b.rfind(" ", 0, limit)
            out.append(b[:cut if cut > limit // 2 else limit])
            b = b[cut if cut > limit // 2 else limit:].lstrip()
        if b:
            out.append(b)
    return out


def get_or_create_store(client, state):
    if "store_name" in state:
        print(f"Reusing store {state['store_name']}")
        return state["store_name"]

    store = client.file_search_stores.create(
        config={
            "display_name": STORE_DISPLAY_NAME,
            "embedding_model": EMBEDDING_MODEL,
        }
    )
    state["store_name"] = store.name
    save_state(state)
    print(f"Created store {store.name}")
    return store.name


RETRYABLE = ("429", "500", "502", "503", "504", "timeout", "deadline",
             "unavailable", "resource_exhausted", "connection")


def upload(client, store_name, path, act_no, act_title, category):
    op = client.file_search_stores.upload_to_file_search_store(
        file=str(path),
        file_search_store_name=store_name,
        config={
            "display_name": f"{act_title} (Act {act_no})" if act_no else act_title,
            "chunking_config": CHUNKING,
            "custom_metadata": [
                {"key": "act_no", "string_value": str(act_no or "")},
                {"key": "act_title", "string_value": act_title},
                {"key": "category", "string_value": category},
            ],
        },
    )
    # Poll with a widening interval: small Acts finish in seconds, the Income
    # Tax Act takes considerably longer, and a fixed 3s sleep wastes calls.
    delay = 1.5
    waited = 0.0
    while not op.done:
        time.sleep(delay)
        waited += delay
        delay = min(delay * 1.4, 15)
        if waited > UPLOAD_TIMEOUT:
            raise TimeoutError(f"indexing still running after {waited:.0f}s")
        op = client.operations.get(op)
    return op


def upload_with_retry(client, store_name, path, act_no, act_title, category):
    """Transient 429/5xx is normal across 700 sequential uploads."""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return upload(client, store_name, path, act_no, act_title, category)
        except Exception as e:
            last = e
            msg = str(e).lower()
            if not any(k in msg for k in RETRYABLE):
                raise
            back = min(2 ** attempt * 2, 60)
            time.sleep(back)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acts", help="comma-separated act numbers, e.g. 265,177")
    ap.add_argument("--limit", type=int, help="stop after N acts (smoke test)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"concurrent uploads (default {DEFAULT_WORKERS}); "
                         "lower it if you start seeing 429s")
    ap.add_argument("--include-amendments", action="store_true",
                    help="also index standalone amendment Acts. Off by "
                         "default: the 'updated' text is already consolidated, "
                         "so amendment Acts add fragments like 'section 3 is "
                         "deleted' that read as current law out of context.")
    args = ap.parse_args()

    only = {a.strip() for a in args.acts.split(",")} if args.acts else None
    # build_corpus already guarantees an Act appears under exactly one
    # category, so translated/revised here are only the Acts that 'updated'
    # does not carry at all -- never a second copy of the same law.
    cats = PRIMARY_CATEGORIES + (("amendment",) if args.include_amendments else ())

    client = genai.Client()  # reads GEMINI_API_KEY
    state = load_state()
    state.setdefault("uploaded", {})
    store_name = get_or_create_store(client, state)

    acts = group_by_act(only, cats)
    if not acts:
        sys.exit("No matching acts in sections.jsonl")

    todo = [k for k in acts if k not in state["uploaded"]]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(acts)} acts matched, {len(todo)} still to upload\n")

    # Upload the biggest Acts first. They dominate the wall clock, so starting
    # them early keeps the workers busy instead of trailing a long tail.
    todo.sort(key=lambda k: sum(len(s["text"]) for s in acts[k][3]), reverse=True)

    print(f"{len(acts)} acts matched, {len(todo)} still to upload "
          f"({args.workers} workers)\n")

    lock = threading.Lock()
    done = {"n": 0, "ok": 0}
    failures = []
    started = time.time()

    def work(key):
        act_title, category, act_no, sections = acts[key]
        path = write_act_file(key, act_title, sections)
        try:
            upload_with_retry(client, store_name, path, act_no, act_title,
                              category)
            result = None
        except Exception as e:
            result = str(e)[:300]

        with lock:
            done["n"] += 1
            n, total = done["n"], len(todo)
            if result is None:
                done["ok"] += 1
                state["uploaded"][str(key)] = {
                    "act_no": act_no,
                    "act_title": act_title,
                    "category": category,
                    "sections": len(sections),
                }
                save_state(state)          # resumable after any interruption
                status = "ok"
            else:
                failures.append((act_title, result))
                status = "FAILED"

            rate = (time.time() - started) / n
            eta = rate * (total - n)
            print(f"  [{n}/{total}] {status:6} {act_title[:46]:46} "
                  f"{len(sections):4d} secs   ETA {eta/60:5.1f}m")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, todo))

    total_sections = sum(v["sections"] for v in state["uploaded"].values())
    elapsed = (time.time() - started) / 60
    print(f"\nStore: {store_name}")
    print(f"Acts indexed: {len(state['uploaded'])}  Sections: {total_sections}")
    print(f"This run: {done['ok']} ok, {len(failures)} failed, {elapsed:.1f} min")

    if failures:
        print("\nFailures (re-run the same command to retry just these):")
        for title, err in failures[:15]:
            print(f"  {title[:50]:50} {err[:90]}")
        if len(failures) > 15:
            print(f"  ... and {len(failures) - 15} more")

    print("\nNow run:  streamlit run app.py")


if __name__ == "__main__":
    main()
