FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y gcc curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend/ backend/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "--workers=2", "--worker-class=uvicorn.workers.UvicornWorker", \
     "--bind=0.0.0.0:8000", "--access-logfile=-", "--error-logfile=-", \
     "backend.main:app"]
