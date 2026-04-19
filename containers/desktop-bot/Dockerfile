FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends wakeonlan openssh-client iputils-ping \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "python-telegram-bot==21.*"

COPY bot.py /app/bot.py
WORKDIR /app

CMD ["python", "bot.py"]
