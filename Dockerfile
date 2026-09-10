FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN addgroup --system notifier \
    && adduser --system --ingroup notifier notifier \
    && mkdir -p /app/data \
    && chown -R notifier:notifier /app

USER notifier

CMD ["python", "-m", "app.main"]

