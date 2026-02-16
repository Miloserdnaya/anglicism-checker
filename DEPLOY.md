# Инструкция по деплою

## Подготовка

1. Выложите проект на GitHub:
   ```bash
   cd anglicism-checker
   git init
   git add .
   git commit -m "Anglicism checker"
   git remote add origin https://github.com/ВАШ_ЛОГИН/anglicism-checker.git
   git push -u origin main
   ```

---

## Railway (рекомендуется)

### Шаг 1. Создайте проект

1. Зайдите на [railway.app](https://railway.app)
2. Войдите через GitHub
3. **New Project** → **Deploy from GitHub repo**
4. Выберите репозиторий `anglicism-checker`
5. Railway автоматически определит Dockerfile и начнёт сборку

### Шаг 2. Добавьте Volume

Словари и индекс нужно хранить постоянно. Без Volume они пропадут при перезапуске.

1. Откройте созданный сервис
2. **Settings** → **Volumes** → **Add Volume**
3. Mount Path: `/app/data`
4. Создайте Volume

### Шаг 3. Получите домен

1. **Settings** → **Networking** → **Generate Domain**
2. Скопируйте URL (например `anglicism-checker-production.up.railway.app`)

### Шаг 4. Проверка при 502

Если видите 502 Bad Gateway:
1. **Deployments → View Logs** — проверьте ошибки при запуске
2. Убедитесь, что добавлен Volume (`/app/data`)
3. Перезапустите: Deployments → ⋮ → Redeploy
4. Проверьте `/health` — должен вернуть `{"status":"ok"}`

### Шаг 5. Первый запуск

1. Откройте URL сервиса
2. Нажмите **«Загрузить и проиндексировать словари»**
3. Подождите 5–10 минут (скачивание PDF ~100 МБ, индексация)
4. Готово — можно проверять слова

### Альтернатива: загрузить свои PDF

Вместо скачивания можно положить PDF в папку до деплоя и закоммитить:

- Скопируйте 5 PDF в `data/pdf/` (см. `data/pdf/README.txt`)
- Уберите `data/` из `.gitignore` (осторожно: репо станет ~150 МБ)
- Закоммитьте и запушьте

---

## Render

1. [render.com](https://render.com) → New → Web Service
2. Подключите GitHub-репозиторий
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. **Важно:** на бесплатном плане нет постоянного диска — после «засыпания» данные теряются. Нужен платный план с Persistent Disk.

---

## Fly.io

```bash
# Установка: curl -L https://fly.io/install.sh | sh
fly launch
fly volumes create data --size 1
# В fly.toml добавьте:
# [mounts]
#   source = "data"
#   destination = "/app/data"
fly deploy
```

---

## Docker (свой сервер)

```bash
docker build -t anglicism-checker .
docker run -p 8000:8000 -v $(pwd)/data:/app/data anglicism-checker
```

Словари положите в `./data/pdf/` перед запуском или нажмите «Загрузить и проиндексировать» в интерфейсе.
