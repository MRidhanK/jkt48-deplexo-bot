FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY discord_notifier.py dashboard.html subscriptions.json entrypoint.sh ./
RUN chmod +x entrypoint.sh && mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_FILE=/app/dashboard.html \
    SUBS_FILE=/data/subscriptions.json \
    STATE_FILE=/data/state.json

VOLUME ["/data"]
EXPOSE 8765
ENTRYPOINT ["/app/entrypoint.sh"]