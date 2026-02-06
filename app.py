"""
Веб-сервис проверки слов по официальным словарям РФ.
Слово в словаре → можно использовать. Слова нет → рекомендуемая замена.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from checker import analyze_word, extract_words_from_html
from dictionaries import DictionaryManager, DICTIONARY_SOURCES

DATA_DIR = Path(os.environ["DATA_DIR"]) if os.environ.get("DATA_DIR") else Path(__file__).resolve().parent / "data"
dict_manager = DictionaryManager(DATA_DIR)

app = FastAPI(
    title="Проверка англицизмов",
    description="Проверка слов по официальным словарям РФ (ИРЯ РАН, ИЛИ РАН, СПбГУ)",
)


@app.on_event("startup")
async def startup():
    """При запуске пытаемся загрузить индекс, если он уже есть."""
    dict_manager.load_index()


class CheckWordsRequest(BaseModel):
    words: list[str]


class CheckUrlRequest(BaseModel):
    url: str


@app.get("/")
async def index():
    """Веб-интерфейс."""
    return HTMLResponse(get_html())


@app.get("/api/status")
async def status():
    """Статус сервиса и словарей."""
    return {
        "pdfs_downloaded": dict_manager.has_pdfs,
        "index_ready": dict_manager.is_ready,
        "dictionaries": list(DICTIONARY_SOURCES.keys()),
    }


@app.post("/api/init")
async def init_dictionaries():
    """Скачивает PDF-словари и строит индекс."""
    download_result = dict_manager.download_dictionaries()
    if "error" in download_result:
        raise HTTPException(status_code=500, detail=download_result)
    index_result = dict_manager.index_pdfs()
    if isinstance(index_result, dict) and "error" in index_result:
        raise HTTPException(status_code=500, detail=index_result["error"])
    return {"download": download_result, "index": index_result}


@app.post("/api/check", response_model=list)
async def check_words(req: CheckWordsRequest):
    """Проверяет список слов на англицизмы."""
    results = [analyze_word(w, dict_manager) for w in req.words if w.strip()]
    return results


@app.post("/api/check-url", response_model=list)
async def check_url(req: CheckUrlRequest):
    """Извлекает текст с URL и проверяет найденные англицизмы."""
    import urllib.request

    try:
        r = urllib.request.Request(req.url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            html = resp.read().decode(errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить URL: {e}")

    words = extract_words_from_html(html)
    results = [analyze_word(w, dict_manager) for w in words]
    return results


def get_html() -> str:
    return """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Проверка англицизмов</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 720px; margin: 0 auto; padding: 2rem; }
        h1 { color: #1a1a2e; }
        .card { background: #f8f9fa; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }
        input, textarea, button { font-size: 1rem; padding: 0.5rem 0.75rem; border: 1px solid #ddd; border-radius: 8px; }
        textarea { width: 100%; min-height: 100px; resize: vertical; }
        button { background: #1a1a2e; color: white; border: none; cursor: pointer; margin-right: 0.5rem; }
        button:hover { background: #16213e; }
        button.secondary { background: #6c757d; }
        #status { font-size: 0.9rem; color: #666; margin-bottom: 1rem; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #e9ecef; }
        .anglicism { color: #c92a2a; }
        .ok { color: #2b8a3e; }
    </style>
</head>
<body>
    <h1>Проверка англицизмов</h1>
    <p id="status">Загрузка статуса...</p>

    <div class="card">
        <h3>Слова</h3>
        <textarea id="words" placeholder="Введите слова через запятую или с новой строки">креатив, скилл, лайв</textarea>
        <p style="margin-top: 0.5rem;">
            <button onclick="checkWords()">Проверить слова</button>
        </p>
    </div>

    <div class="card">
        <h3>Проверить сайт</h3>
        <input type="url" id="url" placeholder="https://example.ru" style="width: 100%; margin-bottom: 0.5rem;" value="https://thecreativity.ru/">
        <button onclick="checkUrl()">Найти англицизмы на странице</button>
    </div>

    <div class="card" id="init-card">
        <h3>Словари</h3>
        <p>Официальные PDF-словари (ИРЯ РАН, ИЛИ РАН, СПбГУ) скачиваются с ruslang.ru и индексируются локально.</p>
        <button onclick="initDictionaries()">Загрузить и проиндексировать словари</button>
        <p id="init-status" style="margin-top: 0.5rem; font-size: 0.9rem;"></p>
    </div>

    <div class="card" id="results-card" style="display:none">
        <h3>Результаты</h3>
        <table id="results"></table>
    </div>

    <script>
        async function getStatus() {
            const r = await fetch('/api/status');
            const s = await r.json();
            const status = document.getElementById('status');
            status.textContent = s.index_ready 
                ? 'Словари загружены и проиндексированы.' 
                : (s.pdfs_downloaded ? 'PDF скачаны. Нажмите «Загрузить и проиндексировать».' : 'Словари не загружены. Нажмите кнопку ниже.');
        }

        async function initDictionaries() {
            const st = document.getElementById('init-status');
            st.textContent = 'Скачивание и индексация...';
            try {
                const r = await fetch('/api/init', { method: 'POST' });
                const d = await r.json();
                st.textContent = 'Готово. Скачано: ' + JSON.stringify(d.download) + '. Индекс: ' + JSON.stringify(d.index);
                getStatus();
            } catch (e) {
                st.textContent = 'Ошибка: ' + e.message;
            }
        }

        async function checkWords() {
            const text = document.getElementById('words').value;
            const words = text.split(/[,\\n]+/).map(w => w.trim()).filter(Boolean);
            if (!words.length) return;
            const r = await fetch('/api/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ words })
            });
            const data = await r.json();
            showResults(data);
        }

        async function checkUrl() {
            const url = document.getElementById('url').value;
            if (!url) return;
            const r = await fetch('/api/check-url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            const data = await r.json();
            showResults(data);
        }

        function showResults(data) {
            const card = document.getElementById('results-card');
            const table = document.getElementById('results');
            let html = '<tr><th>Слово</th><th>В словаре</th><th>В каком словаре</th><th>Рекомендация</th></tr>';
            for (const row of data) {
                const inDict = row.in_dict 
                    ? '<span class="ok">да</span>' 
                    : '<span class="anglicism">нет</span>';
                const dictList = row.in_official_dicts && row.in_official_dicts.length
                    ? [...new Set(row.in_official_dicts.map(d => d.dict))].join('; ')
                    : '—';
                const recommendation = row.in_dict 
                    ? 'можно использовать' 
                    : (row.russian_equivalent ? 'замените на: ' + row.russian_equivalent : '—');
                html += `<tr><td>${row.word}</td><td>${inDict}</td><td>${dictList}</td><td>${recommendation}</td></tr>`;
            }
            table.innerHTML = html;
            card.style.display = 'block';
        }

        getStatus();
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
