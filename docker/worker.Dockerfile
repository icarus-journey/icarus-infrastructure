FROM python:3.13-slim

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /tmp/requisitos.txt
RUN python -m pip install --disable-pip-version-check --no-cache-dir -r /tmp/requisitos.txt

CMD ["python", "-m", "icarus_worker.main"]
