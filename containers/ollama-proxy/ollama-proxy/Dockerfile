FROM python:3.12-slim
WORKDIR /app
RUN pip install fastapi uvicorn httpx
COPY proxy.py config.py ./
CMD ["python", "proxy.py"]
