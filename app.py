"""
Malaysian statute research assistant — Streamlit chat over a Gemini
File Search store built by ingest.py.

    pip install streamlit google-genai
    set GEMINI_API_KEY=...
    streamlit run app.py

The system prompt below is the safety layer. It is deliberately strict:
the model answers only from retrieved statute text, always cites the
section, and never gives tailored advice.
"""

import json
import os
import re
from pathlib import Path

import streamlit as st
from google import genai

# The model sometimes pastes raw retrieval objects into its prose. Rule 8 of
# the system prompt discourages it but does not stop it reliably, so strip
# them out here as well.
TOOL_DUMP_RE = re.compile(r"\[?\s*PerQueryResult\(.*?\)\s*\]?", re.S)

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "corpus" / "store.json"
MODEL = "gemini-3.7-flash"
HISTORY_TURNS = 6  # how much prior conversation to replay each request

ACCURACY_RULES = """\
You are a research assistant for Malaysian federal legislation. You are NOT \
a lawyer and you do not give legal advice.

Rules, in order of priority:

1. Answer ONLY from the statute text retrieved by the file_search tool. If \
the retrieved material does not answer the question, say so plainly: "I \
couldn't find that in the Acts I have access to." Never fill gaps from \
memory — you will get Malaysian law wrong.
2. Cite the Act and section for every proposition, in the form \
(Employment Act 1955, s.60E(1)). The retrieved text carries these in \
headers like [EMPLOYMENT ACT 1955 — s.60E — Annual leave]. Use them.
3. Describe what the law SAYS. Do not tell the user what they should do, \
what their chances are, or how to proceed.
4. If the answer turns on facts the user has not given (length of service, \
whether they are covered by the First Schedule, which state), say which \
facts change the answer instead of assuming them.
5. This corpus is federal principal Acts only. It does not contain case \
law, subsidiary legislation (P.U.(A)/P.U.(B)), state enactments, or Syariah \
law. If a question needs those, say so.
6. The Acts are consolidated snapshots. Later amendments may not be \
reflected. For anything consequential, tell the user to verify the current \
text at lom.agc.gov.my.
7. Write prose only. Never paste raw tool output, search-result objects or \
snippet dumps into the answer -- quote the statute text itself instead.
"""

PLAIN_STYLE = """\
STYLE: write for someone with no legal training at all.

- Open with a direct answer in one or two everyday sentences, in bold. No \
preamble, no restating the question.
- Then a "What the law says" line naming the section, with a quoted phrase \
only where the exact wording changes the meaning. Keep quotes under 25 words.
- Then "What could change this" — a few short bullets covering the facts \
that would alter the answer.
- Explain each legal term the first time you use it, in brackets: \
"continuous service (working for the same employer without a real break)".
- Short sentences, everyday words. Write "must" not "shall", "under" not \
"pursuant to", "even so" not "notwithstanding". Never write "aforementioned", \
"thereof", "hereinafter" or "the said".
- Address the reader as "you" when describing who a rule covers, but never \
tell them what to do. "You get 12 days if..." is fine; "You should..." is not.
- Numbers as digits: 12 days, 4 weeks.
- Stay under about 200 words unless the question genuinely needs more.
"""

LEGAL_STYLE = """\
STYLE: write for a reader who wants the statutory detail.

- Lead with the section that governs, then the detail.
- Quote the operative words of the section when they matter; paraphrasing \
loses legal meaning.
- Keep answers tight.
"""


def system_prompt(plain=True):
    """Accuracy rules never vary; only the presentation style does."""
    return ACCURACY_RULES + "\n" + (PLAIN_STYLE if plain else LEGAL_STYLE)

DISCLAIMER = (
    "Legal **information**, not legal advice. This tool is not a substitute "
    "for a qualified Malaysian advocate & solicitor. Verify against "
    "[lom.agc.gov.my](https://lom.agc.gov.my)."
)


@st.cache_resource
def get_client():
    if not os.environ.get("GEMINI_API_KEY"):
        st.error("GEMINI_API_KEY is not set.")
        st.stop()
    return genai.Client()


@st.cache_resource
def get_store_name():
    if not STATE.exists():
        st.error(f"{STATE} not found — run ingest.py first.")
        st.stop()
    name = json.loads(STATE.read_text(encoding="utf-8")).get("store_name")
    if not name:
        st.error("No store_name in store.json — run ingest.py first.")
        st.stop()
    return name


def build_input(history, question, plain=True):
    """File Search runs through the Interactions API, which has no chat
    helper, so prior turns are replayed as plain text."""
    parts = [system_prompt(plain), ""]
    for role, text in history[-HISTORY_TURNS * 2:]:
        parts.append(f"{'User' if role == 'user' else 'Assistant'}: {text}")
    parts.append(f"User: {question}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def ask(client, store_name, history, question, act_filter=None, plain=True):
    tool = {"type": "file_search", "file_search_store_names": [store_name]}
    if act_filter:
        tool["metadata_filter"] = f'act_no="{act_filter}"'

    interaction = client.interactions.create(
        model=MODEL,
        input=build_input(history, question, plain),
        tools=[tool],
    )

    answer, cites = [], []
    for step in interaction.steps:
        if step.type != "model_output":
            continue
        for block in step.content:
            if block.type != "text":
                continue
            answer.append(block.text)
            for ann in (block.annotations or []):
                if ann.type == "file_citation":
                    label = ann.file_name
                    page = getattr(ann, "page_number", None)
                    if page:
                        label += f" (p.{page})"
                    if label not in cites:
                        cites.append(label)

    text = TOOL_DUMP_RE.sub("", "".join(answer))
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)   # tidy the gap left behind
    return text.strip(), cites


st.set_page_config(page_title="Malaysia Law Assistant", page_icon="⚖️")
st.title("⚖️ Malaysia Law Assistant")
st.caption(DISCLAIMER)

client = get_client()
store_name = get_store_name()

with st.sidebar:
    st.subheader("Answer style")
    plain = st.radio(
        "Style", ["Plain English", "Legal detail"], label_visibility="collapsed",
        help="Plain English leads with a direct answer and explains the "
             "jargon. Legal detail leads with the section and quotes the "
             "operative wording. Both cite the same sections.",
    ) == "Plain English"

    st.subheader("Scope")
    act_filter = st.text_input(
        "Restrict to Act number", placeholder="e.g. 265",
        help="Leave blank to search every indexed Act.")
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()
    if STATE.exists():
        uploaded = json.loads(STATE.read_text(encoding="utf-8")).get("uploaded", {})
        st.caption(f"{len(uploaded)} Acts indexed")

if "messages" not in st.session_state:
    st.session_state.messages = []

for role, text in st.session_state.messages:
    with st.chat_message(role):
        st.markdown(text)

if prompt := st.chat_input("Ask about a Malaysian federal Act..."):
    st.session_state.messages.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching the statute book..."):
            try:
                answer, cites = ask(
                    client, store_name,
                    st.session_state.messages[:-1], prompt,
                    act_filter.strip() or None, plain)
            except Exception as e:
                answer, cites = f"Request failed: {e}", []
        st.markdown(answer)
        if cites:
            with st.expander(f"Sources ({len(cites)})"):
                for c in cites:
                    st.write(f"- {c}")
        st.caption(DISCLAIMER)

    st.session_state.messages.append(("assistant", answer))
