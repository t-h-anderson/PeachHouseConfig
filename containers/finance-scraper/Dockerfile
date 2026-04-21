FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app
RUN pip install --no-cache-dir playwright
COPY scraper.py .

CMD ["python", "scraper.py"]
