"""Start the hosted demo from nothing: fetch the data, train the models, then run the API and the page.

    python -m aecompass.deploy.serve            # used by the Hugging Face Space (deploy/space/Dockerfile)

A free hosted container starts with an empty disk every time it wakes up, and `data/` is never committed.
So on start-up this:
  1. downloads the monthly raw snapshot files from the repository's public GitHub Release tagged `data`
     (the collector workflow keeps them up to date every hour), plus `offsets.json`, the interval widths
     measured by the evaluation;
  2. fetches the last two days from the official archive so the newest waits are included;
  3. trains the forecasting models on everything, with the same recipe as `python -m aecompass.forecast.train`;
  4. starts the API on an internal port and the web page on the public one.
The chat is off (AECOMPASS_CHAT=off): the agent needs a local AI model that the host does not have.
"""

from __future__ import annotations

import gzip
import importlib.util
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import httpx

from aecompass.collect import archive
from aecompass.collect.aed import DEFAULT_ROOT, months_between

RELEASE = os.environ.get("AECOMPASS_DATA_URL", "https://github.com/ChTej00/HK-A-E-Compass/releases/download/data")
FIRST_MONTH = date(2025, 10, 1)  # the history starts in October 2025 (README "Data sources")
MODEL_DIR = Path("data/models")
API_PORT = 8000


def fetch_release(client: httpx.Client, root: Path = DEFAULT_ROOT, today: date | None = None) -> list[str]:
    """Download every month's raw file that exists in the release. Returns the months found."""
    root.mkdir(parents=True, exist_ok=True)
    found = []
    for month in months_between(FIRST_MONTH, today or archive.now_hkt().date()):
        r = client.get(f"{RELEASE}/aed_raw_{month}.jsonl.gz")
        if r.status_code == 404:
            continue
        r.raise_for_status()
        (root / f"aed_raw_{month}.jsonl").write_bytes(gzip.decompress(r.content))
        found.append(month)
    if not found:
        raise RuntimeError(f"No raw data found at {RELEASE}")
    r = client.get(f"{RELEASE}/offsets.json")
    if r.status_code == 404:
        raise RuntimeError(
            f"{RELEASE}/offsets.json is missing. Upload it once from a machine that has run the evaluation: "
            "gh release upload data data/models/offsets.json --clobber"
        )
    r.raise_for_status()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "offsets.json").write_bytes(r.content)
    return found


def prepare() -> None:
    from aecompass.forecast import train
    from aecompass.recommend.cli import refresh

    t0 = time.time()
    with httpx.Client(follow_redirects=True, timeout=300) as client:
        months = fetch_release(client)
    print(f"downloaded {len(months)} months ({months[0]} to {months[-1]}) in {time.time() - t0:.0f}s", flush=True)
    refresh()  # newest two days from the official archive, then rebuild the clean table
    print(f"caught up with the archive at {time.time() - t0:.0f}s", flush=True)
    offsets = (MODEL_DIR / "offsets.json").read_bytes()
    train.main()  # finds no evaluation predictions here, so it writes an empty offsets.json ...
    (MODEL_DIR / "offsets.json").write_bytes(offsets)  # ... which is replaced by the measured one
    print(f"models trained at {time.time() - t0:.0f}s", flush=True)


def page_path() -> str:
    """The Streamlit script, wherever the package is installed (not imported: importing it draws the page)."""
    return str(Path(importlib.util.find_spec("aecompass.web").submodule_search_locations[0]) / "app.py")


def wait_for_api(seconds: int = 300) -> None:
    for _ in range(seconds):
        try:
            if httpx.get(f"http://127.0.0.1:{API_PORT}/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("the API did not start")


def main() -> int:
    os.environ.setdefault("AECOMPASS_CHAT", "off")
    os.environ.setdefault("AECOMPASS_REFRESH_MINUTES", "15")
    os.environ.setdefault("AECOMPASS_API_URL", f"http://127.0.0.1:{API_PORT}")
    port = os.environ.get("PORT", "7860")  # Hugging Face Spaces expects 7860
    prepare()
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "aecompass.api.app:app", "--host", "127.0.0.1", "--port", str(API_PORT)])
    wait_for_api()
    page = subprocess.Popen([sys.executable, "-m", "streamlit", "run", page_path(), "--server.port", port,
                             "--server.address", "0.0.0.0", "--server.headless", "true",
                             "--browser.gatherUsageStats", "false"])
    # If either process stops, stop the other and exit, so the host restarts the whole container.
    while api.poll() is None and page.poll() is None:
        time.sleep(5)
    for process in (api, page):
        if process.poll() is None:
            process.terminate()
    return 1


if __name__ == "__main__":
    sys.exit(main())
