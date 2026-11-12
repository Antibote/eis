FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY dataset/ dataset/
COPY experiments/ experiments/
COPY --from=web /app/frontend/dist frontend/dist
ENV EIS_DATA_DIR=/data PYTHONUNBUFFERED=1 HF_HOME=/models
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "eis.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
