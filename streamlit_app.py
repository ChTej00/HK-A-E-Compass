"""Entry point for Streamlit Community Cloud (free hosting). Locally, use `streamlit run src/aecompass/web/app.py`.

On the first visit after the app wakes up, this downloads recent data and the trained models from the
GitHub Release `data`, then starts the API inside this process. Streamlit re-runs this file on every
click; `st.cache_resource` makes the start-up happen once per process.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))  # works whether or not the package was pip-installed

import streamlit as st  # noqa: E402

from aecompass.deploy import serve  # noqa: E402
from aecompass.web import app as page  # noqa: E402


@st.cache_resource(show_spinner="Starting up: fetching the newest waits and the forecasting models (about a minute)...")
def start() -> bool:
    serve.use_hosted_defaults()
    page.API = serve.HOSTED_DEFAULTS["AECOMPASS_API_URL"]
    serve.prepare()
    serve.start_api_thread()
    return True


start()
page.API = serve.HOSTED_DEFAULTS["AECOMPASS_API_URL"]
page.main()
