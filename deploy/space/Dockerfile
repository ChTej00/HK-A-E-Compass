# The Hugging Face Space's Dockerfile. Copy this file and README.md (same folder) into a new Docker Space.
# It builds from the public GitHub repository, so pushing to GitHub and restarting the Space updates it.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as user 1000.
RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Hong_Kong \
    AECOMPASS_CHAT=off
WORKDIR /home/user/app

ARG REPO=https://github.com/ChTej00/HK-A-E-Compass.git
ARG REF=master
RUN git clone --depth 1 --branch "$REF" "$REPO" . \
    && pip install --user ".[app]"

EXPOSE 7860
CMD ["python", "-m", "aecompass.deploy.serve"]
