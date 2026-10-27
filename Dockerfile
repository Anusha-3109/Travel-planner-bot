# TripMate for Google Cloud Run (or any Docker host).
#   docker build -t tripmate .
#   docker run -p 8080:8080 --env-file .env tripmate
# The knowledge base is built into the image, so a cold start doesn't re-embed every place.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Embeds the 2026 places into .chroma/ (downloads the small local embedding model first).
RUN python -m backend.rag.ingest

EXPOSE 8080
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
