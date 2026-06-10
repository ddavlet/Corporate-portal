FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

FROM base AS cron

RUN apt-get update && apt-get install -y --no-install-recommends cron \
  && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Tashkent

RUN chmod +x /app/cron/entrypoint.sh

CMD ["/app/cron/entrypoint.sh"]

FROM base AS web

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
