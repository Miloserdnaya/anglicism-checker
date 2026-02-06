FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py checker.py dictionaries.py ./

# Папка для PDF и индекса (монтируется как volume при деплое)
RUN mkdir -p /app/data/pdf

ENV PORT=8000
EXPOSE $PORT

ENV DATA_DIR=/app/data
# Railway передаёт PORT динамически — используем переменную окружения
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
