# One image for both the API and the web page; docker-compose.yml runs it twice with different commands.
# Data, trained models and the knowledge base are not baked in: they live in ./data, mounted at run time,
# because data/ is never committed (see README).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Hong_Kong

# LightGBM needs the OpenMP runtime, which the slim image leaves out.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first, in their own layer, so editing code doesn't reinstall everything.
COPY pyproject.toml ./
RUN mkdir -p src/aecompass && touch src/aecompass/__init__.py \
    && pip install ".[app]" \
    && pip uninstall -y aecompass

COPY src ./src
RUN pip install --no-deps .

# Don't run as root inside the container.
RUN useradd --create-home --uid 1000 app && mkdir -p data && chown app data
USER app

EXPOSE 8000 8501
CMD ["uvicorn", "aecompass.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
