"""
Веб-сервис проверки слов по официальным словарям РФ.
Слово в словаре → можно использовать. Слова нет → рекомендуемая замена.
"""

import os
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from checker import analyze_word, extract_words_from_html, extract_words_from_pdf
from dictionaries import DictionaryManager, DICTIONARY_SOURCES

DATA_DIR = Path(os.environ["DATA_DIR"]) if os.environ.get("DATA_DIR") else Path(__file__).resolve().parent / "data"
dict_manager = DictionaryManager(DATA_DIR)

# Фоновая загрузка словарей (избегаем таймаута Railway ~5 мин)
_init_state = {"status": "idle", "message": "", "error": None}
_init_lock = threading.Lock()

app = FastAPI(
    title="Проверка англицизмов",
    description="Проверка слов по официальным словарям РФ (ИРЯ РАН, ИЛИ РАН, СПбГУ)",
)


@app.get("/health")
async def health():
    """Лёгкий эндпоинт для health-check Railway."""
    return {"status": "ok"}


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


def _run_init():
    """Фоновая загрузка и индексация словарей."""
    global _init_state
    with _init_lock:
        if _init_state["status"] == "running":
            return
        _init_state["status"] = "running"
        _init_state["error"] = None
        _init_state["message"] = "Скачивание PDF..."
    try:
        download_result = dict_manager.download_dictionaries()
        with _init_lock:
            _init_state["message"] = "Индексация..."
        if isinstance(download_result, dict) and "error" in download_result:
            raise Exception(download_result["error"])
        pdf_count = len(list(dict_manager.pdf_dir.glob("*.pdf"))) if dict_manager.pdf_dir.exists() else 0
        if pdf_count == 0:
            failed = [f"{k}: {v}" for k, v in (download_result or {}).items() if v not in ("downloaded", "already_exists")]
            raise Exception("Не удалось загрузить. Ошибки: " + ("; ".join(failed) if failed else "нет PDF"))
        index_result = dict_manager.index_pdfs()
        if isinstance(index_result, dict) and "error" in index_result:
            raise Exception(index_result["error"])
        with _init_lock:
            _init_state["status"] = "done"
            _init_state["message"] = f"Готово. {index_result.get('words', 0)} слов."
    except Exception as e:
        with _init_lock:
            _init_state["status"] = "error"
            _init_state["error"] = str(e)
            _init_state["message"] = str(e)


@app.get("/api/status")
async def status():
    """Статус сервиса и словарей."""
    pdf_count = len(list(dict_manager.pdf_dir.glob("*.pdf"))) if dict_manager.pdf_dir.exists() else 0
    with _init_lock:
        init_state = dict(_init_state)
    return {
        "pdfs_downloaded": dict_manager.has_pdfs,
        "pdf_count": pdf_count,
        "index_ready": dict_manager.is_ready,
        "index_exists": dict_manager.index_file.exists(),
        "dictionaries": list(DICTIONARY_SOURCES.keys()),
        "init_status": init_state["status"],
        "init_message": init_state["message"],
        "init_error": init_state.get("error"),
    }


@app.post("/api/init")
async def init_dictionaries():
    """Запускает загрузку и индексацию в фоне. Возвращает сразу. Опрашивайте /api/status."""
    with _init_lock:
        if _init_state["status"] == "running":
            return {"status": "running", "message": "Загрузка уже идёт. Обновите страницу для статуса."}
        if dict_manager.is_ready:
            return {"status": "done", "message": "Словари уже загружены."}
    t = threading.Thread(target=_run_init, daemon=True)
    t.start()
    return {"status": "started", "message": "Загрузка запущена. Обновите статус через 10–20 сек."}


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
    <p><button id="btnRefresh" class="secondary" onclick="getStatus()">Обновить статус</button></p>

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
        <p id="init-status" style="margin-top: 0.5rem; font-size: 0.9rem; min-height: 1.4em; color: #495057;"></p>
    </div>

    <div class="card" id="results-card" style="display:none">
        <h3>Результаты</h3>
        <p style="margin-bottom: 0.5rem;">
            <button class="secondary" onclick="downloadCSV()">Скачать CSV</button>
            <button class="secondary" onclick="downloadTZ()">Скачать ТЗ</button>
            <span id="tz-message" style="margin-left: 0.5rem; font-size: 0.9rem;"></span>
        </p>
        <table id="results"></table>
    </div>

    <script>
        let pollInterval = null;
        async function getStatus(showRefreshAfterSlow = true) {
            const status = document.getElementById('status');
            const btnRefresh = document.getElementById('btnRefresh');
            status.style.color = '';
            if (showRefreshAfterSlow) {
                status.textContent = 'Проверка статуса...';
                btnRefresh.style.display = 'none';
            }
            const slowMsg = showRefreshAfterSlow ? setTimeout(() => {
                status.textContent = 'Сервер запускается или недоступен. Нажмите «Обновить статус».';
                status.style.color = '#666';
                btnRefresh.style.display = 'inline-block';
            }, 5000) : null;
            try {
                const r = await fetch('/api/status');
                clearTimeout(slowMsg);
                const s = await r.json();
                const initSt = document.getElementById('init-status');
                if (s.init_status === 'running') {
                    const msg = (s.init_message || 'Загрузка...') + ' (5–15 мин, не закрывайте вкладку)';
                    status.textContent = msg;
                    if (initSt) { initSt.textContent = msg; initSt.style.color = '#0d6efd'; }
                } else if (s.init_status === 'done' || s.index_ready) {
                    status.textContent = 'Словари загружены и проиндексированы.';
                    if (initSt) { initSt.textContent = 'Готово. Словари загружены.'; initSt.style.color = '#2b8a3e'; }
                } else if (s.init_status === 'error') {
                    const errMsg = 'Ошибка: ' + (s.init_error || s.init_message || '');
                    status.textContent = errMsg;
                    status.style.color = '#c92a2a';
                    if (initSt) { initSt.textContent = errMsg; initSt.style.color = '#c92a2a'; }
                } else {
                    status.textContent = s.pdfs_downloaded || (s.pdf_count && s.pdf_count > 0) 
                        ? 'PDF: ' + (s.pdf_count || 0) + ' из 5. Нажмите «Загрузить и проиндексировать».' 
                        : 'Словари не загружены. Нажмите кнопку ниже (скачивание ~100 МБ, 5–15 мин в фоне).';
                    if (initSt && !s.index_ready) initSt.textContent = '';
                }
                if ((s.init_status === 'running' || s.init_status === 'started') && !pollInterval) {
                    pollInterval = setInterval(() => getStatus(false), 6000);
                } else if (s.init_status === 'done' || s.init_status === 'error' || s.index_ready) {
                    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
                }
            } catch (e) {
                clearTimeout(slowMsg);
                status.textContent = 'Ошибка соединения. Нажмите «Обновить статус», чтобы повторить.';
                status.style.color = '#c92a2a';
                btnRefresh.style.display = 'inline-block';
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
            st.textContent = 'Запускаю загрузку…';
            st.style.color = '#0d6efd';
            try {
                const r = await fetch('/api/init', { method: 'POST' });
                let d;
                try { d = await r.json(); } catch (_) { d = {}; }
                if (!r.ok) throw new Error(d.detail || (typeof d.detail === 'string' ? d.detail : d.message) || 'Сервер вернул ' + r.status);
                if (d.status === 'done') {
                    st.textContent = d.message || 'Словари уже загружены.';
                    st.style.color = '#2b8a3e';
                    getStatus(false);
                } else {
                    st.textContent = d.message || 'Загрузка запущена. Статус обновляется…';
                    st.style.color = '#0d6efd';
                    if (!pollInterval) pollInterval = setInterval(() => getStatus(false), 5000);
                    getStatus(false);
                    setTimeout(() => getStatus(false), 2000);
                }
            } catch (e) {
                st.textContent = 'Ошибка: ' + (e.message || e);
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
            const tzMsg = document.getElementById('tz-message');
            if (tzMsg) tzMsg.textContent = '';
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
                if (!row.in_dict && row.occurrences && row.occurrences.length) {
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
            const escape = v => '"' + String(v != null ? v : '').replace(/"/g, '""') + '"';
            const header = 'Слово;В словаре;В каком словаре;Рекомендация;Где находится';
            const rows = lastResults.map(r => {
                const inDict = r.in_dict ? 'да' : 'нет';
                const dictList = r.in_official_dicts && r.in_official_dicts.length
                    ? [...new Set(r.in_official_dicts.map(d => d.dict))].join('; ')
                    : '—';
                const rec = r.in_dict ? 'можно использовать' : (r.russian_equivalent ? 'замените на: ' + r.russian_equivalent : '—');
                let where = '—';
                if (!r.in_dict && r.occurrences && r.occurrences.length) {
                    const o = r.occurrences[0];
                    where = (o.page ? 'Стр. ' + o.page + ': ' : '') + (o.context || '');
                    if (r.occurrences.length > 1) where += ' (+' + (r.occurrences.length - 1) + ' вхождений)';
                }
                return [r.word, inDict, dictList, rec, where].map(escape).join(';');
            });
            const csv = String.fromCharCode(0xFEFF) + header + '\\n' + rows.join('\\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'anglicism-check-results.csv';
            a.click();
            URL.revokeObjectURL(a.href);
        }

        function showTZMessage(msg, isError) {
            const el = document.getElementById('tz-message');
            if (!el) return;
            el.textContent = msg;
            el.style.color = isError ? '#c92a2a' : '#495057';
            setTimeout(function() { el.textContent = ''; }, 8000);
        }

        function downloadTZ() {
            if (!lastResults.length) {
                showTZMessage('Сначала выполните проверку слов, URL или PDF.', true);
                return;
            }
            const withEquiv = lastResults.filter(r => !r.in_dict && r.russian_equivalent);
            const noEquiv = lastResults.filter(r => !r.in_dict && !r.russian_equivalent);
            const noEquivMapped = noEquiv.map(r => ({ ...r, russian_equivalent: '(подобрать аналог вручную)', equivalent_in_dicts: [] }));
            const toReplace = withEquiv.concat(noEquivMapped);
            if (toReplace.length === 0) {
                showTZMessage('Все слова уже в словарях — ТЗ не требуется. Скачайте CSV для отчёта.', false);
                return;
            }
            const date = new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
            const src = lastSource || '-';
            let tz = 'ТЕХНИЧЕСКОЕ ЗАДАНИЕ\\nна замену англицизмов на слова-аналоги из официальных словарей РФ\\n\\nДата: ' + date + '\\nИсточник проверки: ' + src + '\\n\\n' +
                '═══════════════════════════════════════════════════════════════════\\n1. ЗАДАЧА\\n\\n' +
                'Выполнить замену слов (англицизмов), отсутствующих в официальных словарях\\nрусского языка как государственного языка РФ, на рекомендуемые аналоги.\\n' +
                'Аналоги приведены из четырёх официальных словарей и могут использоваться.\\n\\nСловари-источники аналогов:\\n' +
                '• Орфографический словарь (ИРЯ РАН)\\n• Орфоэпический словарь (ИРЯ РАН)\\n• Словарь иностранных слов (ИЛИ РАН)\\n• Толковый словарь гос. языка РФ (СПбГУ)\\n\\n' +
                '═══════════════════════════════════════════════════════════════════\\n2. ТЕЗИСЫ (СЛОВО ДЛЯ ЗАМЕНЫ - АНАЛОГ ИЗ СЛОВАРЯ, ГДЕ НАХОДИТСЯ)\\n\\n';
            toReplace.forEach((r, i) => {
                const equivDict = r.equivalent_in_dicts && r.equivalent_in_dicts.length
                    ? ' (в словаре: ' + r.equivalent_in_dicts.join('; ') + ')'
                    : '';
                tz += (i + 1) + '. «' + r.word + '» - заменить на: ' + r.russian_equivalent + equivDict + '\\n';
                const occs = r.occurrences || [];
                if (occs.length > 0) {
                    occs.slice(0, 5).forEach(o => {
                        const loc = o.page ? 'Стр. ' + o.page + ': ' : '';
                        tz += '   • ' + loc + '«' + (o.context || '-') + '»\\n';
                    });
                    if (occs.length > 5) tz += '   • ... и ещё ' + (occs.length - 5) + ' вхождений\\n';
                } else {
                    tz += '   • Найти вручную (учтите словоформы: падежи, числа, глагольные формы)\\n';
                }
                tz += '\\n';
            });
            tz += '═══════════════════════════════════════════════════════════════════\\n3. ИНСТРУКЦИЯ ДЛЯ ИСПОЛНИТЕЛЯ\\n\\n' +
                '• Заменить каждое слово на указанный аналог с учётом контекста и стиля.\\n' +
                '• Аналоги взяты из официальных словарей РФ - их можно использовать.\\n' +
                '• При необходимости скорректировать грамматику предложения после замены.\\n' +
                '• Слова, не попавшие в список, оставить без изменений (они уже в словаре).\\n\\n' +
                '═══════════════════════════════════════════════════════════════════\\n4. КОНТРОЛЬ\\n\\n' +
                'По завершении работ проверить, что:\\n- все указанные слова заменены на аналоги из словарей;\\n' +
                '- текст читается естественно;\\n- термины, имена собственные и устоявшиеся обозначения сохранены по смыслу.\\n';
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
