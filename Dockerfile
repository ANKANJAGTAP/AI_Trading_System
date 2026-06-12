FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=Asia/Kolkata

WORKDIR /app

# postgresql-client: pg_isready for wait-for-db. tzdata + IST localtime so that
# KiteTicker's naive exchange_timestamp (built via datetime.fromtimestamp, which
# uses local time) is IST — matching the DB session tz and now_ist().
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client tzdata \
    && ln -sf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x ops/entrypoint.sh

# Entrypoint dispatches on the command: api | engine | migrate
ENTRYPOINT ["ops/entrypoint.sh"]
CMD ["api"]
