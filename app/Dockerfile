# Build context is the repo root (see docker-compose.yml) so this can copy
# the shared resolvers/tools/graph/db/llm packages alongside app/ itself.
FROM python:3.12-slim

WORKDIR /srv

# Installed as its own step, pinned to the dedicated CPU-only wheel index --
# mixing this index into requirements-app.txt via --extra-index-url made pip
# re-check it for every other package too, which was extremely slow.
RUN pip install --no-cache-dir --timeout 300 --retries 5 \
    --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu

COPY requirements-app.txt .
RUN pip install --no-cache-dir --timeout 300 --retries 5 -r requirements-app.txt

COPY config.py .
COPY resolvers/ resolvers/
COPY tools/ tools/
COPY graph/ graph/
COPY db/ db/
COPY llm/ llm/
COPY nlp/ nlp/
COPY app/ app/
COPY data/ data/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
