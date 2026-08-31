"""
Regression harness for the Malaysia Law Assistant.

Runs eval_questions.json against the live File Search store and scores three
things a legal answer has to get right:

  cite    -- did it cite the Act the answer actually lives in, and the right
             section, and state the right figure?
  refuse  -- for questions whose answer is NOT in the corpus, did it decline
             instead of confabulating from a near neighbour?
  cross   -- 'notice', 'registration' and 'termination' appear in hundreds of
             Acts. Did retrieval land on the right body of law?

Run it after any change to the prompt, the chunking, or the corpus.

    python eval.py                 # all questions
    python eval.py --mode refuse   # just the refusal cases
    python eval.py --legal         # score the Legal-detail style instead
    python eval.py --save baseline.json

Exit code is non-zero if anything fails, so it can gate a rebuild.
"""

import argparse
import json
import re
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUESTIONS = ROOT / "eval_questions.json"


def load_app():
    """Import app.py for its prompt and ask(), without booting Streamlit."""
    class _Ctx:
        def __call__(self, *a, **k): return self
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __bool__(self): return False

    class _State(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__

    fake = types.ModuleType("streamlit")
    fake.cache_resource = lambda f: f
    fake.__getattr__ = lambda n: _Ctx()
    fake.sidebar = _Ctx()
    fake.session_state = _State()
    sys.modules["streamlit"] = fake

    sys.path.insert(0, str(ROOT))
    import app
    return app


REFUSAL_MARKERS = (
    "couldn't find", "could not find", "not contain", "do not have",
    "don't have", "not included", "not in the acts", "does not contain",
    "not available in", "outside the", "not part of",
)


def refused(answer):
    """A refusal leads with the refusal.

    Scanning the whole answer produced false positives: a correct answer that
    ends "...fees are set by subsidiary legislation, which is not included in
    this corpus" scored as a refusal. Genuine refusals say so up front.
    """
    return any(m in answer[:250].lower() for m in REFUSAL_MARKERS)


def cited_acts(answer, citations):
    """Act numbers, from the citation objects and, failing those, the prose.

    The API sometimes returns no citation objects at all, so the prose is a
    necessary fallback -- but "Employees Provident Fund Act 1991" would
    otherwise register as Act 1991. Principal Act numbers run to ~880, so a
    bare four-digit number in prose is a year, not an Act.
    """
    found = set()
    for c in citations:
        for m in re.finditer(r"\(Act\s+(A?\d{1,4})\)", c, re.I):
            found.add(m.group(1))

    for m in re.finditer(r"\bAct\s+(A?\d{1,4})\b", answer, re.I):
        n = m.group(1)
        if n[0].upper() == "A" or int(n) <= 999:
            found.add(n)
    return found


def cited_sections(answer):
    out = set()
    for m in re.finditer(r"\bs(?:ection)?\.?\s*(\d{1,3}[A-Z]{0,2})\b", answer, re.I):
        out.add(m.group(1).upper())
    return out


def score(case, answer, citations):
    """Return (passed, list of reasons it failed)."""
    problems = []

    if case["mode"] == "refuse":
        if not refused(answer):
            problems.append("did NOT refuse")
        return not problems, problems

    if refused(answer):
        problems.append("refused a question it should have answered")
        return False, problems

    acts = cited_acts(answer, citations)
    want_act = case.get("expect_act")
    if want_act and want_act not in acts:
        problems.append(f"wrong Act: wanted {want_act}, cited {sorted(acts) or 'none'}")

    want_sec = case.get("expect_section")
    if want_sec and want_sec.upper() not in cited_sections(answer):
        problems.append(f"section {want_sec} not cited")

    want_text = case.get("expect_text") or []
    if want_text and not any(t.lower() in answer.lower() for t in want_text):
        problems.append(f"none of {want_text} appeared")

    return not problems, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cite", "refuse"], help="run one mode only")
    ap.add_argument("--legal", action="store_true",
                    help="score Legal-detail style (default is Plain English)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--save", help="write full results to this JSON file")
    ap.add_argument("--verbose", action="store_true", help="print every answer")
    args = ap.parse_args()

    app = load_app()
    from google import genai

    state_file = ROOT / "corpus" / "store.json"
    if not state_file.exists():
        sys.exit("corpus/store.json missing - run ingest.py first")
    store = json.loads(state_file.read_text(encoding="utf-8"))["store_name"]

    cases = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    if args.mode:
        cases = [c for c in cases if c["mode"] == args.mode]

    client = genai.Client()
    print(f"{len(cases)} cases against {store}")
    print(f"style: {'Legal detail' if args.legal else 'Plain English'}\n")

    def run(case):
        try:
            answer, cites = app.ask(client, store, [], case["q"], None,
                                    not args.legal)
        except Exception as e:
            return case, False, [f"ERROR: {str(e)[:120]}"], "", []
        ok, problems = score(case, answer, cites)
        return case, ok, problems, answer, cites

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, cases))

    passed = 0
    by_mode = {}
    for case, ok, problems, answer, cites in results:
        passed += ok
        m = by_mode.setdefault(case["mode"], [0, 0])
        m[1] += 1
        m[0] += ok
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {case['id']:32} {case['mode']}")
        for p in problems:
            print(f"         -> {p}")
        if args.verbose or not ok:
            snippet = re.sub(r"\s+", " ", answer)[:220]
            print(f"         answer: {snippet}")

    print(f"\n{passed}/{len(results)} passed")
    for m, (ok, total) in sorted(by_mode.items()):
        print(f"  {m:8} {ok}/{total}")

    if args.save:
        Path(args.save).write_text(json.dumps([
            {"id": c["id"], "mode": c["mode"], "passed": ok,
             "problems": p, "answer": a, "citations": ci}
            for c, ok, p, a, ci in results], indent=2), encoding="utf-8")
        print(f"\nwrote {args.save}")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
