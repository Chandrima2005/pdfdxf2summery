FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/app/.cache
WORKDIR /app

COPY requirements.txt requirements-embeddings.txt ./
RUN pip install -r requirements.txt \
 && pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-embeddings.txt

COPY . .
# Sample data + pre-downloaded embedding model, so the first question is fast.
RUN python -m cad_copilot.samples --out data/samples \
 && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')" \
 && chmod -R a+rwX /app

EXPOSE 7860
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "7860"]
