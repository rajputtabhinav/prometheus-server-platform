FROM python:3.13-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

CMD ["python", "-m", "prometheus_agent.main"]

