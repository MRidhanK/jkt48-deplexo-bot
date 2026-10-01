FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./
EXPOSE 8765
CMD ["python", "-u", "discord_notifier.py"]
LABEL "deplexo"="true" "deplexo.app"="jkt-bot-2shoot"