"""Start the hosted demo from an empty disk: fetch recent data and the trained models, then serve.

    streamlit run streamlit_app.py           # Streamlit Community Cloud (the API runs inside the page's process)
    python -m aecompass.deploy.serve         # any Docker host: API and page as two processes

A free host starts with an empty disk every time it wakes up, and `data/` is never committed. So on start-up:
  1. download the last two months of raw snapshots from the repository's public GitHub Release `data`
     (the hourly collector keeps them current); forecasting needs only the last 35 days;
  2. fetch the last two days from the official archive, so the newest waits are included;
  3. download `models.tar.gz` from the same release: the models the weekly `train` workflow fitted on all
     the history, plus the interval widths from the evaluation. Training is not done here: it needs more
     memory than the free host has.
The chat is off (AECOMPASS_CHAT=off): the agent needs a local AI model that the host does not have.
"""

from __future__ import annotations

import gzip
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from aecompass.collect import archive
from aecompass.collect.aed import DEFAULT_ROOT, months_between

RELEASE = os.environ.get("AECOMPASS_DATA_URL", "https://github.com/ChTej00/HK-A-E-Compass/releases/download/data")
DATA_DIR = Path("data")
MODEL_FILES = {"meta.json", "offsets.json"}  # plus one .txt per model, listed in meta.json
API_PORT = 8000
HOSTED_DEFAULTS = {"AECOMPASS_CHAT": "off", "AECOMPASS_REFRESH_MINUTES": "15", "AECOMPASS_API_URL": f"http://127.0.0.1:{API_PORT}"}


def fetch_recent(client: httpx.Client, root: Path = DEFAULT_ROOT, today: date | None = None, days: int = 40) -> list[str]:
    """Download the raw monthly files covering the last `days` days. Returns the months found."""
    today = today or archive.now_hkt().date()
    root.mkdir(parents=True, exist_ok=True)
    found = []
    for month in months_between(today - timedelta(days=days), today):
        r = client.get(f"{RELEASE}/aed_raw_{month}.jsonl.gz")
        if r.status_code == 404:
            continue
        r.raise_for_status()
        (root / f"aed_raw_{month}.jsonl").write_bytes(gzip.decompress(r.content))
        found.append(month)
    if not found:
        raise RuntimeError(f"No recent raw data found at {RELEASE}")
    return found


def fetch_models(client: httpx.Client, data_dir: Path = DATA_DIR) -> list[str]:
    """Download and unpack models.tar.gz into data/models. Only plain files under models/ are accepted."""
    r = client.get(f"{RELEASE}/models.tar.gz")
    if r.status_code == 404:
        raise RuntimeError(f"{RELEASE}/models.tar.gz is missing. Run the train workflow once: gh workflow run train.yml")
    r.raise_for_status()
    names = []
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if member.isdir() and parts == ("models",):
                continue
            if not (member.isfile() and len(parts) == 2 and parts[0] == "models" and parts[1].endswith((".json", ".txt"))):
                raise RuntimeError(f"unexpected entry in models.tar.gz: {member.name!r}")
            target = data_dir / "models" / parts[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
            names.append(parts[1])
    missing = MODEL_FILES - set(names)
    if missing:
        raise RuntimeError(f"models.tar.gz has no {', '.join(sorted(missing))}")
    return sorted(names)


def prepare() -> None:
    from aecompass.recommend.cli import refresh

    t0 = time.time()
    with httpx.Client(follow_redirects=True, timeout=300) as client:
        months = fetch_recent(client)
        models = fetch_models(client)
    print(f"downloaded {', '.join(months)} and {len(models)} model files in {time.time() - t0:.0f}s", flush=True)
    refresh()  # newest two days from the official archive, then rebuild the clean table
    print(f"caught up with the archive at {time.time() - t0:.0f}s", flush=True)


def use_hosted_defaults() -> None:
    for key, value in HOSTED_DEFAULTS.items():
        os.environ.setdefault(key, value)


def start_api_thread() -> None:
    """Run the API inside this process, for hosts that run a single program (Streamlit Community Cloud)."""
    import uvicorn

    from aecompass.api.app import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True, name="api").start()
    wait_for_api()


def wait_for_api(seconds: int = 300) -> None:
    for _ in range(seconds):
        try:
            if httpx.get(f"http://127.0.0.1:{API_PORT}/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("the API did not start")


def page_path() -> str:
    """The Streamlit script, wherever the package is installed (not imported: importing it draws the page)."""
    return str(Path(importlib.util.find_spec("aecompass.web").submodule_search_locations[0]) / "app.py")


def main() -> int:
    """Two processes, for a Docker host: the API on an internal port, the page on the public one."""
    use_hosted_defaults()
    port = os.environ.get("PORT", "7860")
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
