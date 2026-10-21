FROM python:3.12-alpine

RUN pip install --no-cache-dir flask waitress

WORKDIR /app

COPY engine.py api.py search.py replace.py app.py ./
COPY templates ./templates
COPY static ./static

ENV CONFIG_DIR=/config PYTHONUNBUFFERED=1
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--threads=4", "app:app"]
