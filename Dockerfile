# Engine container for Railway (always-on process holding WebSocket feeds).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY engine/requirements.txt ./engine/requirements.txt
RUN pip install --no-cache-dir -r engine/requirements.txt

COPY engine ./engine

EXPOSE 8000

# Railway provides $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn engine.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
