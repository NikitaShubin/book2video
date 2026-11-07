FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    BOOK2VIDEO_CACHE=/cache \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    OMP_NUM_THREADS=8 \
    MKL_NUM_THREADS=8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        fonts-dejavu-core \
        gosu \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./

# TeraTTSv2 is ONNX, but it is loaded through transformers' AutoModel, which
# needs the PyTorch backend even for inference.  A CPU wheel is enough for the
# ONNX runtime: no PyTorch CUDA build is needed on either image.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.6.0

# Install the application without onnxruntime; the CPU and GPU targets below
# add the matching runtime package.  This keeps the CUDA libraries out of the
# default image.
COPY src ./src
RUN pip install --no-cache-dir .

# Playwright is used only for HTML link previews.  The browser binary is
# downloaded once into the image; builds run it with --no-sandbox because the
# container is already the isolation boundary.
RUN mkdir -p /ms-playwright \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /models /cache /data /out \
    && chown -R app:app /models /cache /data /out /app

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER root

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["voices"]


# Optional NVIDIA image.  Driver libraries are supplied by the host through
# the NVIDIA container runtime; onnxruntime-gpu and the CUDA user-space
# libraries come from PyPI.  Without --gpus all it falls back to CPU.
FROM base AS gpu
RUN pip install --no-cache-dir '.[gpu]'
RUN python -c "import onnxruntime as ort; print('onnxruntime', ort.__version__)"


# CPU stays the last stage so a plain `docker build .` builds the portable
# default image.
FROM base AS cpu
RUN pip install --no-cache-dir '.[cpu]'
RUN python -c "import onnxruntime as ort; print('onnxruntime', ort.__version__)"
