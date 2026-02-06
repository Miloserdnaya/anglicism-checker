FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py checker.py dictionaries.py ./

# Папка для PDF и индекса (монтируется как volume при деплое)
RUN mkdir -p /app/data/pdf

ENV PORT=8000
ENV DATA_DIR=/app/data
EXPOSE 8000

# app.py читает PORT из переменной окружения Railway
CMD ["python", "app.py"]
