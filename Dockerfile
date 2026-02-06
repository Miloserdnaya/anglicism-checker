FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py checker.py dictionaries.py ./

# Папка для PDF и индекса (монтируется как volume при деплое)
RUN mkdir -p /app/data/pdf

EXPOSE 8000

ENV DATA_DIR=/app/data
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
