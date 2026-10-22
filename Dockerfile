# Complaint Radar scoring API
FROM python:3.13-slim

# LightGBM needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.11.28

# Dependencies first (cached unless pyproject/uv.lock change), then the project itself
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
# Alerts are read from CR_ALERTS_PATH; mount the serving file, e.g. -v $PWD/data/serving:/app/data/serving:ro
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "complaint_radar.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
