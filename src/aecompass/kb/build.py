"""Download the official pages and cut them into passages the agent can search.

    python -m aecompass.kb.build        # writes data/kb/chunks.jsonl (a few seconds)

A whole press release is too long and too mixed to hand to a model, so each one is cut into passages
("chunks") of a few paragraphs. A search then returns only the passages that match a question, and each
passage remembers which page it came from, so the answer can cite it.
"""

from __future__ import annotations

import html
import io
import json
import re
import time
from pathlib import Path

import httpx
import pypdf

from aecompass.kb.sources import SOURCES, Source

CHUNKS_PATH = Path("data/kb/chunks.jsonl")
TARGET_WORDS = 130  # passages are built up from whole paragraphs until they reach about this size
MAX_WORDS = 220


def extract_text(page: str) -> list[str]:
    """The press release's paragraphs, without the page furniture around them."""
    start = page.find('id="pressrelease"')
    if start < 0:
        raise ValueError("press release body not found")
    body = page[page.find(">", start) + 1 :]
    body = body[: body.find("</span>")]
    body = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", body, flags=re.I)
    body = html.unescape(re.sub(r"<[^>]+>", " ", body)).replace("\xa0", " ")
    paragraphs = [re.sub(r"\s+", " ", line).strip() for line in body.split("\n")]
    paragraphs = [p for p in paragraphs if p]
    for i, p in enumerate(paragraphs):  # everything from the sign-off onward is boilerplate
        if p.startswith("Ends/"):
            paragraphs = paragraphs[:i]
            break
    return paragraphs


def extract_pdf_text(content: bytes) -> list[str]:
    """A short PDF annex (a fee table) as one block of text; table rows come out as lines."""
    pages = [page.extract_text() for page in pypdf.PdfReader(io.BytesIO(content)).pages]
    lines = [re.sub(r"\s+", " ", line).strip() for line in "\n".join(pages).split("\n")]
    return ["\n".join(line for line in lines if line)]


def chunk(paragraphs: list[str]) -> list[str]:
    """Group whole paragraphs into passages of roughly TARGET_WORDS; a very long paragraph is split by sentence."""
    pieces = []
    for p in paragraphs:
        if len(p.split()) <= MAX_WORDS:
            pieces.append(p)
            continue
        sentences, current = re.split(r"(?<=[.!?])\s+", p), []
        for s in sentences:
            current.append(s)
            if sum(len(x.split()) for x in current) >= TARGET_WORDS:
                pieces.append(" ".join(current))
                current = []
        if current:
            pieces.append(" ".join(current))
    chunks, current = [], []
    words = lambda parts: sum(len(x.split()) for x in parts)
    for piece in pieces:
        if current and words(current) + len(piece.split()) > MAX_WORDS:  # would grow too long: close it first
            chunks.append("\n".join(current))
            current = []
        current.append(piece)
        if sum(len(x.split()) for x in current) >= TARGET_WORDS:
            chunks.append("\n".join(current))
            current = []
    if current:
        if chunks and words(current) < 40 and words([chunks[-1]]) + words(current) <= MAX_WORDS:
            chunks[-1] += "\n" + "\n".join(current)  # do not leave a tiny tail on its own
        else:
            chunks.append("\n".join(current))
    return chunks


def build(sources: list[Source] = SOURCES, out: Path = CHUNKS_PATH) -> int:
    rows = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for source in sources:
            r = client.get(source.url)
            r.raise_for_status()
            if source.kind == "pdf":
                passages = extract_pdf_text(r.content)  # a one-page table: kept whole so rows stay with their headings
            else:
                passages = chunk(extract_text(r.text))
            for i, text in enumerate(passages):
                rows.append({"chunk_id": f"{source.id}#{i}", "source_id": source.id, "text": text})
            print(f"{source.id}: {len(passages)} passages")
            time.sleep(1)  # be polite to the server
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    print(f"wrote {build()} passages to {CHUNKS_PATH}")
