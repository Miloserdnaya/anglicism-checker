"""
Веб-сервис проверки слов по официальным словарям РФ.
Слово в словаре → можно использовать. Слова нет → рекомендуемая замена.
"""

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from checker import analyze_word, extract_words_from_html, extract_words_from_pdf
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

    items = extract_words_from_html(html, with_positions=True)
    results = [
        analyze_word(item["word"], dict_manager, occurrences=item.get("occurrences"))
        for item in items
    ]
    return results


@app.post("/api/check-pdf", response_model=list)
async def check_pdf(file: UploadFile = File(...)):
    """Загрузите PDF-файл — извлекаем текст и проверяем слова на англицизмы."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Загрузите файл в формате PDF")
    try:
        pdf_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {e}")
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл не должен превышать 50 МБ")
    try:
        items = extract_words_from_pdf(pdf_bytes, with_positions=True)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    results = [
        analyze_word(item["word"], dict_manager, occurrences=item.get("occurrences"))
        for item in items
    ]
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

    <div class="card">
        <h3>Проверить PDF</h3>
        <input type="file" id="pdfFile" accept=".pdf" style="margin-bottom: 0.5rem;">
        <p><button onclick="checkPdf()">Найти англицизмы в PDF</button></p>
    </div>

    <div class="card" id="init-card">
        <h3>Словари</h3>
        <p>Официальные PDF-словари (ИРЯ РАН, ИЛИ РАН, СПбГУ) скачиваются с ruslang.ru и индексируются локально.</p>
        <button onclick="initDictionaries()">Загрузить и проиндексировать словари</button>
        <p id="init-status" style="margin-top: 0.5rem; font-size: 0.9rem;"></p>
    </div>

    <div class="card" id="results-card" style="display:none">
        <h3>Результаты</h3>
        <p style="margin-bottom: 0.5rem;">
            <button class="secondary" onclick="downloadCSV()">Скачать CSV</button>
            <button class="secondary" onclick="downloadTZ()">Скачать ТЗ</button>
        </p>
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
            lastSource = 'список слов';
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
            lastSource = url;
            showResults(data);
        }

        async function checkPdf() {
            const input = document.getElementById('pdfFile');
            if (!input.files || !input.files[0]) { alert('Выберите PDF-файл'); return; }
            const form = new FormData();
            form.append('file', input.files[0]);
            const r = await fetch('/api/check-pdf', { method: 'POST', body: form });
            if (!r.ok) { const e = await r.json(); alert(e.detail || 'Ошибка'); return; }
            const data = await r.json();
            lastSource = input.files[0].name;
            showResults(data);
        }

        let lastResults = [];
        let lastSource = '';

        function showResults(data) {
            lastResults = data;
            const card = document.getElementById('results-card');
            const table = document.getElementById('results');
            let html = '<tr><th>Слово</th><th>В словаре</th><th>В каком словаре</th><th>Рекомендация</th><th>Где находится</th></tr>';
            for (const row of data) {
                const inDict = row.in_dict ? 'да' : 'нет';
                const dictList = row.in_official_dicts && row.in_official_dicts.length
                    ? [...new Set(row.in_official_dicts.map(d => d.dict))].join('; ')
                    : '—';
                const recommendation = row.in_dict 
                    ? 'можно использовать' 
                    : (row.russian_equivalent ? 'замените на: ' + row.russian_equivalent : '—');
                const inDictHtml = row.in_dict ? '<span class="ok">да</span>' : '<span class="anglicism">нет</span>';
                let where = '—';
                if (row.occurrences && row.occurrences.length) {
                    const first = row.occurrences[0];
                    where = (first.page ? 'Стр. ' + first.page + ': ' : '') + (first.context || '');
                    if (row.occurrences.length > 1) where += ' (+' + (row.occurrences.length - 1) + ')';
                }
                html += `<tr><td>${row.word}</td><td>${inDictHtml}</td><td>${dictList}</td><td>${recommendation}</td><td style="max-width:200px;font-size:0.85em">${where}</td></tr>`;
            }
            table.innerHTML = html;
            card.style.display = 'block';
        }

        function downloadCSV() {
            if (!lastResults.length) return;
            const escape = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
            const header = 'Слово;В словаре;В каком словаре;Рекомендация;Где находится';
            const rows = lastResults.map(r => {
                const inDict = r.in_dict ? 'да' : 'нет';
                const dictList = r.in_official_dicts?.length
                    ? [...new Set(r.in_official_dicts.map(d => d.dict))].join('; ')
                    : '—';
                const rec = r.in_dict ? 'можно использовать' : (r.russian_equivalent ? 'замените на: ' + r.russian_equivalent : '—');
                let where = '—';
                if (r.occurrences?.length) {
                    const o = r.occurrences[0];
                    where = (o.page ? 'Стр. ' + o.page + ': ' : '') + (o.context || '');
                    if (r.occurrences.length > 1) where += ' (+' + (r.occurrences.length - 1) + ' вхождений)';
                }
                return [r.word, inDict, dictList, rec, where].map(escape).join(';');
            });
            const csv = '\\uFEFF' + header + '\\n' + rows.join('\\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'anglicism-check-results.csv';
            a.click();
            URL.revokeObjectURL(a.href);
        }

        function downloadTZ() {
            if (!lastResults.length) return;
            const toReplace = lastResults.filter(r => !r.in_dict && r.russian_equivalent);
            if (!toReplace.length) {
                alert('Нет слов для замены: все слова либо в словаре, либо без рекомендуемого аналога.');
                return;
            }
            const date = new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
            let tz = `ТЕХНИЧЕСКОЕ ЗАДАНИЕ
на замену англицизмов на слова-аналоги из официальных словарей РФ

Дата: ${date}
Источник проверки: ${lastSource || '—'}

═══════════════════════════════════════════════════════════════════
1. ЗАДАЧА

Выполнить замену слов (англицизмов), отсутствующих в официальных словарях 
русского языка как государственного языка РФ, на рекомендуемые аналоги.
Аналоги приведены из четырёх официальных словарей и могут использоваться.

Словари-источники аналогов:
• Орфографический словарь (ИРЯ РАН)
• Орфоэпический словарь (ИРЯ РАН)
• Словарь иностранных слов (ИЛИ РАН)
• Толковый словарь гос. языка РФ (СПбГУ)

═══════════════════════════════════════════════════════════════════
2. ТЕЗИСЫ (СЛОВО ДЛЯ ЗАМЕНЫ → АНАЛОГ ИЗ СЛОВАРЯ, ГДЕ НАХОДИТСЯ)

`;
            toReplace.forEach((r, i) => {
                const equivDict = r.equivalent_in_dicts && r.equivalent_in_dicts.length
                    ? ' (в словаре: ' + r.equivalent_in_dicts.join('; ') + ')'
                    : '';
                tz += `${i + 1}. «${r.word}» → заменить на: ${r.russian_equivalent}${equivDict}\n`;
                const occs = r.occurrences || [];
                if (occs.length > 0) {
                    occs.slice(0, 5).forEach(o => {
                        const loc = o.page ? `Стр. ${o.page}: ` : '';
                        tz += `   • ${loc}«${o.context || '—'}»\n`;
                    });
                    if (occs.length > 5) tz += `   • ... и ещё ${occs.length - 5} вхождений\n`;
                } else {
                    tz += `   • Найти вручную (учтите словоформы: падежи, числа, глагольные формы)\n`;
                }
                tz += '\n';
            });
            tz += `
═══════════════════════════════════════════════════════════════════
3. ИНСТРУКЦИЯ ДЛЯ ИСПОЛНИТЕЛЯ

• Заменить каждое слово на указанный аналог с учётом контекста и стиля.
• Аналоги взяты из официальных словарей РФ — их можно использовать.
• При необходимости скорректировать грамматику предложения после замены.
• Слова, не попавшие в список, оставить без изменений (они уже в словаре).

═══════════════════════════════════════════════════════════════════
4. КОНТРОЛЬ

По завершении работ проверить, что:
— все указанные слова заменены на аналоги из словарей;
— текст читается естественно;
— термины, имена собственные и устоявшиеся обозначения сохранены по смыслу.
`;
            const blob = new Blob([tz], { type: 'text/plain;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'ТЗ-замена-англицизмов.txt';
            a.click();
            URL.revokeObjectURL(a.href);
        }

        getStatus();
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
