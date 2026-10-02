# Build context = root repo (jkt48-deplexo). Semua file aplikasi ada di folder server/.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/discord_notifier.py server/check_block.py server/dashboard.html server/subscriptions.json server/entrypoint.sh ./
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh && mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_FILE=/app/dashboard.html \
    SUBS_FILE=/data/subscriptions.json \
    STATE_FILE=/data/state.json

VOLUME ["/data"]
EXPOSE 8765
ENTRYPOINT ["/app/entrypoint.sh"]