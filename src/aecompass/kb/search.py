"""Find the passages that best match a question.

This is the "retrieval" in retrieval-augmented generation (RAG): instead of trusting what a model
remembers about Hong Kong's A&E rules, we look the answer up in official text and hand the model only
those passages, each with its source, to answer from and cite.

Two ways of matching are provided behind the same `search(query, k)` method:

- `KeywordSearch`: scores passages by the words they share with the question, weighting rare words more
  (TF-IDF). No model, instant, easy to explain. Cannot match a Chinese question to English text.
- `EmbeddingSearch`: an embedding model turns each passage and the question into a list of numbers that
  captures meaning, and passages whose numbers point the same way as the question's are returned ("vector
  search"). Matches paraphrases and other languages; needs a model running in Ollama.

- `HybridSearch`: runs both and merges the two rankings, so a passage that either method ranks highly
  comes through. Keyword search is good at exact terms ("Category II"); embeddings are good at meaning.

`evals/run_retrieval.py` compares them on the same questions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from aecompass.kb.build import CHUNKS_PATH
from aecompass.kb.sources import BY_ID, Source


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    source: Source
    text: str
    score: float


def load_chunks(path: Path = CHUNKS_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python -m aecompass.kb.build")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _Base:
    min_score = 0.0  # below this a passage is not shown at all: better to say "not found" than to mislead

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    def _scores(self, query: str) -> np.ndarray:
        raise NotImplementedError

    def search(self, query: str, k: int = 3) -> list[Hit]:
        scores = self._scores(query)
        order = np.argsort(-scores)[:k]
        return [
            Hit(self.chunks[i]["chunk_id"], BY_ID[self.chunks[i]["source_id"]], self.chunks[i]["text"], float(scores[i]))
            for i in order if scores[i] > self.min_score
        ]


class KeywordSearch(_Base):
    name = "keyword (TF-IDF)"
    min_score = 0.05

    def __init__(self, chunks: list[dict]):
        super().__init__(chunks)
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.matrix = self.vectorizer.fit_transform(c["text"] for c in chunks)

    def _scores(self, query: str) -> np.ndarray:
        return (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()


class EmbeddingSearch(_Base):
    min_score = 0.3

    def __init__(self, chunks: list[dict], model: str = "bge-m3", host: str | None = None,
                 cache: Path | None = None, client: httpx.Client | None = None):
        super().__init__(chunks)
        self.model, self.name = model, f"embedding ({model})"
        host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")  # same setting as the chat model
        host = host if host.startswith("http") else f"http://{host}"
        self.http = client or httpx.Client(base_url=host, timeout=httpx.Timeout(600, connect=5))
        cache = cache or CHUNKS_PATH.with_name(f"embeddings_{model.replace(':', '_').replace('/', '_')}.npy")
        if cache.exists() and len(np.load(cache)) == len(chunks):
            self.matrix = np.load(cache)
        else:
            self.matrix = self._embed([c["text"] for c in chunks])
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, self.matrix)

    def _embed(self, texts: list[str]) -> np.ndarray:
        r = self.http.post("/api/embed", json={"model": self.model, "input": texts})
        r.raise_for_status()
        vectors = np.array(r.json()["embeddings"], dtype="float32")
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)  # unit length, so a dot product is the cosine

    def _scores(self, query: str) -> np.ndarray:
        return self.matrix @ self._embed([query])[0]


class HybridSearch:
    """Merge the rankings of several searchers by reciprocal rank fusion.

    Each searcher gives every passage a rank (1 = best). A passage's merged score is the sum of
    1 / (60 + rank) over the searchers, so being near the top of either list counts, and no scores from
    different methods ever have to be compared directly. 60 is the conventional constant.
    """

    def __init__(self, searchers: list, depth: int = 10):
        self.searchers, self.depth = searchers, depth
        self.name = "hybrid (" + " + ".join(s.name for s in searchers) + ")"

    def search(self, query: str, k: int = 3) -> list[Hit]:
        merged: dict[str, float] = {}
        best: dict[str, Hit] = {}
        for searcher in self.searchers:
            for rank, hit in enumerate(searcher.search(query, self.depth), start=1):
                merged[hit.chunk_id] = merged.get(hit.chunk_id, 0.0) + 1.0 / (60 + rank)
                best.setdefault(hit.chunk_id, hit)
        top = sorted(merged, key=merged.get, reverse=True)[:k]
        return [Hit(i, best[i].source, best[i].text, merged[i]) for i in top]
