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
    pdf_count = len(list(dict_manager.pdf_dir.glob("*.pdf"))) if dict_manager.pdf_dir.exists() else 0
    return {
        "pdfs_downloaded": dict_manager.has_pdfs,
        "pdf_count": pdf_count,
        "index_ready": dict_manager.is_ready,
        "index_exists": dict_manager.index_file.exists(),
        "dictionaries": list(DICTIONARY_SOURCES.keys()),
    }


@app.post("/api/init")
async def init_dictionaries():
    """Скачивает PDF-словари и строит индекс."""
    download_result = dict_manager.download_dictionaries()
    if isinstance(download_result, dict) and "error" in download_result:
        raise HTTPException(status_code=500, detail=download_result["error"])
    pdf_count = len(list(dict_manager.pdf_dir.glob("*.pdf"))) if dict_manager.pdf_dir.exists() else 0
    if pdf_count == 0:
        failed = [f"{k}: {v}" for k, v in (download_result or {}).items() if v not in ("downloaded", "already_exists")]
        raise HTTPException(
            status_code=500,
            detail="Не удалось загрузить словари. Проверьте подключение к интернету. Ошибки: " + ("; ".join(failed) if failed else "нет PDF в data/pdf/"),
        )
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
    <p id="status">Загрузка…</p>

    <div class="card">
        <h3>Слова</h3>
        <textarea id="words" placeholder="Введите слова через запятую или с новой строки">креатив, скилл, лайв</textarea>
        <p style="margin-top: 0.5rem;">
            <button id="btnWords" onclick="checkWords()">Проверить слова</button>
            <span id="wordsStatus" style="margin-left: 0.5rem; font-size: 0.9rem; color: #666;"></span>
        </p>
    </div>

    <div class="card">
        <h3>Проверить сайт</h3>
        <input type="url" id="url" placeholder="https://example.ru" style="width: 100%; margin-bottom: 0.5rem;" value="https://thecreativity.ru/">
        <button id="btnUrl" onclick="checkUrl()">Найти англицизмы на странице</button>
        <span id="urlStatus" style="margin-left: 0.5rem; font-size: 0.9rem; color: #666;"></span>
    </div>

    <div class="card">
        <h3>Проверить PDF</h3>
        <input type="file" id="pdfFile" accept=".pdf" style="margin-bottom: 0.5rem;">
        <p><button id="btnPdf" onclick="checkPdf()">Найти англицизмы в PDF</button>
        <span id="pdfStatus" style="margin-left: 0.5rem; font-size: 0.9rem; color: #666;"></span></p>
    </div>

    <div class="card" id="init-card">
        <h3>Словари</h3>
        <p>Официальные PDF-словари скачиваются с ruslang.ru (~100 МБ, 5–10 мин). <strong>На Railway добавьте Volume</strong> (Settings → Volumes → mount /app/data), иначе данные пропадут при перезапуске.</p>
        <button id="btnInit" onclick="initDictionaries()">Загрузить и проиндексировать словари</button>
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
            const status = document.getElementById('status');
            status.textContent = 'Проверка статуса...';
            status.style.color = '';
            const slowMsg = setTimeout(() => {
                status.textContent = 'Сервер запускается (первый запуск может занять до минуты). Подождите…';
                status.style.color = '#666';
            }, 4000);
            try {
                const r = await fetch('/api/status');
                clearTimeout(slowMsg);
                const s = await r.json();
                const pdfInfo = s.pdf_count !== undefined ? ' (PDF: ' + s.pdf_count + ' из 5)' : '';
                status.textContent = s.index_ready 
                    ? 'Словари загружены и проиндексированы.' 
                    : (s.pdfs_downloaded || (s.pdf_count && s.pdf_count > 0) ? 'PDF: ' + (s.pdf_count || 0) + ' из 5. Нажмите «Загрузить и проиндексировать».' : 'Словари не загружены. Нажмите кнопку ниже (скачивание ~100 МБ, 5–10 мин).');
            } catch (e) {
                clearTimeout(slowMsg);
                status.textContent = 'Ошибка соединения. Проверьте интернет или подождите — сервер может запускаться.';
                status.style.color = '#c92a2a';
            }
        }

        function setLoading(btn, loading) {
            if (!btn) return;
            btn.disabled = loading;
            btn.dataset.originalText = btn.dataset.originalText || btn.textContent;
            btn.textContent = loading ? '… Проверяю …' : btn.dataset.originalText;
        }

        async function initDictionaries() {
            const st = document.getElementById('init-status');
            const btn = document.getElementById('btnInit');
            btn.disabled = true;
            st.textContent = 'Скачивание PDF (~100 МБ) и индексация. Это займёт 5–10 минут, не закрывайте страницу…';
            st.style.color = '';
            try {
                const ctrl = new AbortController();
                const t = setTimeout(() => ctrl.abort(), 600000);
                const r = await fetch('/api/init', { method: 'POST', signal: ctrl.signal });
                clearTimeout(t);
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || d.message || 'Ошибка загрузки');
                if (d.download && d.index) {
                    const n = d.index.words || d.index.pages || '-';
                    st.textContent = 'Готово. Скачано ' + Object.keys(d.download || {}).length + ' файлов. Проиндексировано: ' + n + ' слов.';
                    st.style.color = '#2b8a3e';
                } else {
                    st.textContent = 'Готово. ' + JSON.stringify(d);
                }
                getStatus();
            } catch (e) {
                st.textContent = e.name === 'AbortError' 
                    ? 'Превышено время ожидания (10 мин). Попробуйте ещё раз.' 
                    : 'Ошибка: ' + (e.message || e);
                st.style.color = '#c92a2a';
            } finally {
                btn.disabled = false;
            }
        }

        async function checkWords() {
            const text = document.getElementById('words').value;
            const words = text.split(/[,\\n]+/).map(w => w.trim()).filter(Boolean);
            if (!words.length) { alert('Введите слова'); return; }
            const btn = document.getElementById('btnWords');
            const st = document.getElementById('wordsStatus');
            setLoading(btn, true);
            st.textContent = 'Проверяю ' + words.length + ' слов...';
            try {
                const r = await fetch('/api/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ words })
                });
                const data = await r.json();
                lastSource = 'список слов';
                showResults(data);
                st.textContent = 'Готово. Найдено ' + data.length + ' слов.';
            } catch (e) {
                st.textContent = 'Ошибка: ' + e.message;
                st.style.color = '#c92a2a';
            } finally {
                setLoading(btn, false);
            }
        }

        async function checkUrl() {
            const url = document.getElementById('url').value;
            if (!url) { alert('Введите URL'); return; }
            const btn = document.getElementById('btnUrl');
            const st = document.getElementById('urlStatus');
            setLoading(btn, true);
            st.textContent = 'Загружаю страницу и проверяю...';
            try {
                const r = await fetch('/api/check-url', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const data = await r.json();
                lastSource = url;
                showResults(data);
                st.textContent = 'Готово. Найдено ' + data.length + ' слов.';
            } catch (e) {
                st.textContent = 'Ошибка: ' + e.message;
                st.style.color = '#c92a2a';
            } finally {
                setLoading(btn, false);
            }
        }

        async function checkPdf() {
            const input = document.getElementById('pdfFile');
            if (!input.files || !input.files[0]) { alert('Выберите PDF-файл'); return; }
            const btn = document.getElementById('btnPdf');
            const st = document.getElementById('pdfStatus');
            setLoading(btn, true);
            st.textContent = 'Читаю PDF и проверяю...';
            try {
                const form = new FormData();
                form.append('file', input.files[0]);
                const r = await fetch('/api/check-pdf', { method: 'POST', body: form });
                const data = await r.json();
                if (!r.ok) throw new Error(data.detail || 'Ошибка');
                lastSource = input.files[0].name;
                showResults(data);
                st.textContent = 'Готово. Найдено ' + data.length + ' слов.';
            } catch (e) {
                st.textContent = 'Ошибка: ' + e.message;
                st.style.color = '#c92a2a';
            } finally {
                setLoading(btn, false);
            }
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
