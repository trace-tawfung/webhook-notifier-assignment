FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY webhook_notifier.py .
COPY webhook_test_message.py .
COPY webhook_benchmark_test_message.py .

CMD ["python", "webhook_notifier.py"]