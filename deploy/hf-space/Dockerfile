# Single-container demo image (Hugging Face Spaces, Docker SDK): Postgres, Redis, Qdrant, the API,
# the Celery worker and nginx (SPA + /api proxy) under supervisord. Build context is the directory
# produced by build_space.sh. State lives inside the container and is lost on restart; start.sh
# regenerates secrets and seed.sh recreates the demo workspace each time.
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM qdrant/qdrant:v1.12.4 AS qdrant

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/home/user/.cache/huggingface
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql redis-server nginx-light supervisor tesseract-ocr poppler-utils libgl1 libunwind8 curl openssl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=qdrant /qdrant/qdrant /usr/local/bin/qdrant
RUN useradd --create-home --uid 1000 user
WORKDIR /home/user/app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip==26.2.1 setuptools==84.0.0 \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
COPY app ./app
COPY alembic.ini ./
COPY data/manuals/electric_motor_manual.pdf /home/user/sample/electric_motor_manual.pdf
COPY --from=web /web/dist /home/user/web
COPY supervisord.conf nginx.conf start.sh seed.sh /home/user/
RUN chmod +x /home/user/start.sh /home/user/seed.sh \
    && mkdir -p /home/user/.cache/huggingface /home/user/data /home/user/qdrant-run \
    && chown -R user:user /home/user
USER user
# Bake the two local models into the image so the first request does not download them.
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"
ENV APP_ENV=production PYTHONPATH=/home/user/app DATA_DIR=/home/user/data \
    QDRANT_HOST=127.0.0.1 QDRANT_PORT=6333 \
    LLM_PROVIDER=groq LLM_MODEL=openai/gpt-oss-120b \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
EXPOSE 7860
CMD ["/home/user/start.sh"]
