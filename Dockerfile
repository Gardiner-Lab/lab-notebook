FROM python:3.12-slim

WORKDIR /app

# The same user id as the other tools, as the suite's volumes expect.
RUN useradd -m -u 1000 appuser && mkdir -p /notebook && chown -R appuser:appuser /app /notebook

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn==23.0.0

COPY app/ ./app/

USER appuser

EXPOSE 5004

ENV PYTHONUNBUFFERED=1 \
    NOTEBOOK_DATABASE_PATH=/notebook/notebook.db \
    MOCLO_DATABASE_PATH=/moclo/moclo.db \
    EDITOR_DATABASE_PATH=/editor/plasmid_editor.db \
    SUITE_DATABASE_PATH=/suite/suite.db \
    URL_PREFIX=/notebook \
    PORT=5004

# 127.0.0.1, not localhost, which can mean IPv6 first.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5004/notebook/health')" || exit 1

# One worker with threads keeps SQLite writes simple and ordered.
CMD ["gunicorn", "--bind", "0.0.0.0:5004", "--workers", "1", "--threads", "4", "--timeout", "60", "app.main:app"]
