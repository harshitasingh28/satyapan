# Satyapan API for Google Cloud Run (linux/amd64). Build with Cloud Build: deploy/deploy_api.sh
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MALLOC_ARENA_MAX=2 PORT=8080 SATYAPAN_DATA_DIR=/tmp/satyapan TESSERACT_LANGS=eng+hin+tel

# FFmpeg for video keyframes and audio, Tesseract with English, Hindi and Telugu for OCR
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    tesseract-ocr-tel libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY satyapan ./satyapan
COPY templates ./templates
COPY scripts ./scripts
COPY seed ./seed
COPY deploy/start.sh ./start.sh

RUN useradd --create-home --uid 10001 app && chmod +x start.sh
USER app
EXPOSE 8080
CMD ["./start.sh"]
