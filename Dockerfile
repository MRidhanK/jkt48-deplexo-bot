FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir -U discord.py

# Copy SEMUA file dari folder server/ (termasuk dashboard.html)
COPY server/ ./

EXPOSE 8765
CMD ["python", "-u", "discord_notifier.py"]