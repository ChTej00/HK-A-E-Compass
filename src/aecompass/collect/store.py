"""Raw snapshot storage: one JSON Lines file per month.

JSON Lines (".jsonl") means one JSON object per line. Each line here is one snapshot:

    {"ts": "20261114-0530", "fetched_at": "2026-11-13T21:30:51+00:00", "body": "<the file exactly as served>"}

We keep the body as an untouched string. If we later find a parsing bug, we can re-clean everything
without downloading again. Appending a line is cheap and safe to resume: on restart we read which
timestamps are already stored and only fetch the rest.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class RawStore:
    def __init__(self, root: Path | str, prefix: str):
        self.root = Path(root)
        self.prefix = prefix
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seen: dict[str, set[str]] = {}

    @staticmethod
    def month_of(ts: str) -> str:
        """'20261114-0530' -> '2026-11'"""
        return f"{ts[:4]}-{ts[4:6]}"

    def path(self, month: str) -> Path:
        return self.root / f"{self.prefix}_{month}.jsonl"

    def existing(self, month: str) -> set[str]:
        """Timestamps already stored for a month. Repairs a half-written last line first."""
        if month in self._seen:
            return self._seen[month]
        seen: set[str] = set()
        p = self.path(month)
        if p.exists():
            good_lines = []
            damaged = False
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        seen.add(json.loads(line)["ts"])
                        good_lines.append(line if line.endswith("\n") else line + "\n")
                        damaged = damaged or not line.endswith("\n")
                    except (json.JSONDecodeError, KeyError):
                        damaged = True  # e.g. the process was killed mid-write
            if damaged:
                p.write_text("".join(good_lines), encoding="utf-8")
        self._seen[month] = seen
        return seen

    def has(self, ts: str) -> bool:
        return ts in self.existing(self.month_of(ts))

    def append(self, ts: str, body: str) -> bool:
        """Store one snapshot. Returns False (and stores nothing) if that timestamp is already there."""
        month = self.month_of(ts)
        with self._lock:
            seen = self.existing(month)
            if ts in seen:
                return False
            record = {
                "ts": ts,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "body": body,
            }
            with self.path(month).open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            seen.add(ts)
            return True

    def latest_ts(self) -> str | None:
        """Newest stored timestamp across all months, or None if the store is empty."""
        for p in sorted(self.root.glob(f"{self.prefix}_*.jsonl"), reverse=True):
            month = p.stem.removeprefix(f"{self.prefix}_")
            seen = self.existing(month)
            if seen:
                return max(seen)
        return None
