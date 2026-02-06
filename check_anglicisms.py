#!/usr/bin/env python3
"""
Автоматическая проверка слов на англицизмы.
Использует Викисловарь (ru.wiktionary.org) и опционально — PDF-словари.

Источники для сверки (официальные):
- Орфографический словарь (ИРЯ РАН) — orfo.ruslang.ru
- Орфоэпический словарь (ИРЯ РАН)
- Словарь иностранных слов (ИЛИ РАН)
- Толковый словарь гос. языка РФ (СПбГУ)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from urllib.request import urlopen, Request

# Сопоставление англицизмов и русских эквивалентов (для отчёта)
RUSSIAN_EQUIVALENTS = {
    "креатив": "творчество",
    "креативный": "творческий",
    "креативность": "творчество",
    "креативити": "творчество",
    "платформа": "площадка, сервис",
    "ментор": "наставник",
    "менторы": "наставники",
    "индустрия": "отрасль, сфера",
    "лайв": "прямой эфир",
    "лайвы": "прямые эфиры",
    "трек": "направление, траектория",
    "треки": "направления",
    "скилл": "навык, умение",
    "скиллы": "навыки",
    "контент": "материалы, содержимое",
    "геймдев": "разработка игр",
    "фэшн": "мода",
    "FAQ": "Вопросы и ответы",
    "триал": "пробный период",
    "подписка": "абонемент (в значении subscription)",
    "дизайн": "оформление, проектирование",
    "маркетинг": "сбыт, продвижение",
    "колледж": "(устоявшееся заимствование)",
}


def fetch_wiktionary(word: str) -> Optional[dict]:
    """Получает данные о слове из Викисловаря через API."""
    url = (
        "https://ru.wiktionary.org/w/api.php"
        "?action=query"
        "&titles=" + quote(word) +
        "&prop=revisions"
        "&rvprop=content"
        "&rvslots=main"
        "&format=json"
    )
    try:
        req = Request(url, headers={"User-Agent": "AnglicismChecker/1.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), None)
    if not page or "missing" in page:
        return None

    content = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
    return {"content": content, "title": page.get("title", word)}


def parse_etymology(content: str) -> dict:
    """
    Извлекает этимологию из wikitext Викисловаря.
    Возвращает: {is_anglicism, source_lang, source_word}
    """
    result = {"is_anglicism": False, "source_lang": None, "source_word": None}
    if not content:
        return result

    # Паттерны: {{сэ|en|word|и=ru}}, {{этимология:|en}}, от английского, из английского
    patterns = [
        r'\{\{сэ\|en\|([^}|]+)',
        r'\{\{этимология:[^}]*\|en\}\}',
        r'[оО]т\s+(?:английского|англ\.?)\s+(?:слова\s+)?[«"]?(\w+)[»"]?',
        r'[Ии]з\s+английского',
        r'заимств\.?\s+из\s+англ',
        r'английск[ийаяое]+',
        r'\|\s*en\s*\|',
        r'Слова\s+английского\s+происхождения',
    ]
    text_lower = content.lower()
    for p in patterns:
        if re.search(p, content, re.I):
            result["is_anglicism"] = True
            break

    # Пытаемся извлечь источник
    m = re.search(r'\{\{сэ\|en\|([^}|]+)', content)
    if m:
        result["source_word"] = m.group(1).strip()

    return result


def check_in_pdf(word: str, pdf_path: Path) -> Optional[bool]:
    """Проверяет наличие слова в PDF (если установлен pymupdf)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None  # Библиотека не установлена

    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text = page.get_text()
            # Простой поиск по слову (можно улучшить для словоформ)
            if re.search(rf'\b{re.escape(word)}\b', text, re.I):
                doc.close()
                return True
        doc.close()
        return False
    except Exception:
        return None


def analyze_word(word: str, pdf_dir: Optional[Path] = None) -> dict:
    """Анализирует слово: Викисловарь + опционально PDF."""
    word = word.strip()
    if not word:
        return {}

    wk = fetch_wiktionary(word)
    result = {
        "word": word,
        "in_wiktionary": wk is not None and "error" not in wk,
        "is_anglicism": False,
        "source": None,
        "russian_equivalent": RUSSIAN_EQUIVALENTS.get(word.lower())
        or RUSSIAN_EQUIVALENTS.get(word.lower().rstrip("ы"))
        or RUSSIAN_EQUIVALENTS.get(word.lower() + "ы"),
        "in_pdf_dict": None,
    }

    if wk and "content" in wk:
        ety = parse_etymology(wk["content"])
        result["is_anglicism"] = ety["is_anglicism"]
        result["source"] = ety["source_word"] or ("английский" if ety["is_anglicism"] else None)

    # Проверка в PDF, если задана папка
    if pdf_dir and pdf_dir.exists():
        for pdf in pdf_dir.glob("*.pdf"):
            found = check_in_pdf(word, pdf)
            if found is True:
                result["in_pdf_dict"] = result["in_pdf_dict"] or []
                if not isinstance(result["in_pdf_dict"], list):
                    result["in_pdf_dict"] = [str(pdf.name)]
                else:
                    result["in_pdf_dict"].append(str(pdf.name))

    return result


def main():
    parser = argparse.ArgumentParser(description="Проверка слов на англицизмы")
    parser.add_argument("words", nargs="*", help="Слова для проверки")
    parser.add_argument("-f", "--file", help="Файл со словами (по одному на строку)")
    parser.add_argument("-u", "--url", help="URL страницы — извлечь текст и найти слова (упрощённо)")
    parser.add_argument("-p", "--pdf-dir", help="Папка с PDF-словарями для проверки")
    parser.add_argument("-o", "--output", help="Файл отчёта (markdown)")
    parser.add_argument("--csv", action="store_true", help="Вывод в CSV")
    args = parser.parse_args()

    words = list(args.words or [])
    if args.file:
        p = Path(args.file)
        if p.exists():
            words.extend(p.read_text(encoding="utf-8").strip().splitlines())
    if args.url:
        # Простой список типичных англицизмов для поиска на странице
        try:
            req = Request(args.url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                html = resp.read().decode(errors="ignore")
            # Извлекаем текст (грубо)
            text = re.sub(r"<[^>]+>", " ", html).lower()
            for w in RUSSIAN_EQUIVALENTS:
                if w.lower() in text:
                    words.append(w)
        except Exception as e:
            print(f"Ошибка загрузки URL: {e}", file=sys.stderr)

    words = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    if not words:
        parser.print_help()
        print("\nПримеры:")
        print("  python check_anglicisms.py креатив скилл лайв")
        print("  python check_anglicisms.py -f words.txt")
        print("  python check_anglicisms.py -u https://example.ru")
        return

    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else None
    results = [analyze_word(w, pdf_dir) for w in words]

    # Вывод
    lines = []
    if args.csv:
        lines.append("Слово;Англицизм;Источник;В Викисловаре;Русский эквивалент;В PDF-словаре")
        for r in results:
            lines.append(f"{r['word']};{r['is_anglicism']};{r['source'] or '-'};{r['in_wiktionary']};{r['russian_equivalent'] or '-'};{r['in_pdf_dict'] or '-'}")
    else:
        lines.append("# Отчёт: проверка на англицизмы")
        lines.append("")
        lines.append("| Слово | Англицизм? | Источник | Русский эквивалент |")
        lines.append("|-------|------------|----------|-------------------|")
        for r in results:
            ang = "да" if r["is_anglicism"] else "нет"
            src = r["source"] or "-"
            equiv = r["russian_equivalent"] or "-"
            lines.append(f"| {r['word']} | {ang} | {src} | {equiv} |")
        lines.append("")
        lines.append("*Для официальной проверки сверьте со словарями: orfo.ruslang.ru, ruslang.ru (PDF)*")

    out = "\n".join(lines)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Отчёт сохранён: {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
