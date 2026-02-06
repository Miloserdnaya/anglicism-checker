"""
Загрузка и индексация официальных PDF-словарей.
Словари скачиваются с ruslang.ru (ИРЯ РАН).
"""

import re
from pathlib import Path
from typing import Optional

# Официальные словари (Распоряжение Правительства РФ № 1102-р от 30.04.2025)
DICTIONARY_SOURCES = {
    "orfograficheskij": {
        "url": "https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/orfograficheskij_slovar.pdf",
        "name": "Орфографический словарь (ИРЯ РАН)",
    },
    "orfoepicheskij": {
        "url": "https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/orfoepicheskij_slovar.pdf",
        "name": "Орфоэпический словарь (ИРЯ РАН)",
    },
    "inostr_slov": {
        "url": "https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/slovar_inostr_slov.pdf",
        "name": "Словарь иностранных слов (ИЛИ РАН)",
    },
    "tolkovyj_1": {
        "url": "https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/tolkovyj_slovar_chast1_A-N.pdf",
        "name": "Толковый словарь гос. языка РФ, ч. 1 А–Н (СПбГУ)",
    },
    "tolkovyj_2": {
        "url": "https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/tolkovyj_slovar_chast2_O-Ja.pdf",
        "name": "Толковый словарь гос. языка РФ, ч. 2 О–Я (СПбГУ)",
    },
}


class DictionaryManager:
    """Загрузка, хранение и поиск в PDF-словарях."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.pdf_dir = self.data_dir / "pdf"
        self.index_file = self.data_dir / "index.json"
        self._index: dict[str, list[dict]] = {}
        self._loaded = False

    def ensure_dirs(self) -> None:
        """Создаёт папки для хранения."""
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    def download_dictionaries(self) -> dict[str, str]:
        """Скачивает PDF, если их ещё нет. Возвращает статус по каждому."""
        self.ensure_dirs()
        try:
            import urllib.request
        except ImportError:
            return {"error": "urllib not available"}

        results = {}
        for key, meta in DICTIONARY_SOURCES.items():
            path = self.pdf_dir / f"{key}.pdf"
            if path.exists():
                results[key] = "already_exists"
                continue
            try:
                req = urllib.request.Request(
                    meta["url"],
                    headers={"User-Agent": "AnglicismChecker/1.0"},
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    path.write_bytes(resp.read())
                results[key] = "downloaded"
            except Exception as e:
                results[key] = f"error: {e}"
        return results

    def _normalize_word(self, word: str) -> str:
        """Нормализует слово для поиска (строчные, ё->е)."""
        w = word.lower().strip()
        w = w.replace("ё", "е")
        return w

    def _extract_words_from_text(self, text: str) -> set[str]:
        """Извлекает слова из текста (кириллица + латиница)."""
        # Убираем только знак ударения U+0301 (ме́нтор → ментор)
        # Не используем NFD — иначе й разлагается в и+breve и превращается в и (дизайн→дизаин)
        text = text.replace("\u0301", "")
        # Склеиваем слова, разорванные пробелом из-за ударения (нейросе́ ть → нейросеть)
        text = re.sub(r"([а-яёА-ЯЁ]) ([ть]+)\b", r"\1\2", text)
        # Убираем скобки, оставляя содержимое (орфоэпический: ме[н']тор → мен'тор)
        text_clean = re.sub(r"\[([^\]]*)\]", r"\1", text)
        words = set()
        # Слова: буквы, дефис, апостроф
        for m in re.finditer(r"[а-яёa-z][а-яёa-z0-9\-']*", text_clean, re.I):
            w = m.group(0).lower()
            if len(w) >= 2:
                words.add(w)
                words.add(w.replace("ё", "е").replace("'", ""))  # мен'тор → ментор
        return words

    def index_pdfs(self) -> dict:
        """Индексирует все PDF в папке. Возвращает статистику."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return {"error": "PyMuPDF не установлен. Выполните: pip install PyMuPDF"}

        self.ensure_dirs()
        index: dict[str, list[dict]] = {}
        stats = {"files": 0, "pages": 0, "words": 0}

        for pdf_path in sorted(self.pdf_dir.glob("*.pdf")):
            key = pdf_path.stem
            name = DICTIONARY_SOURCES.get(key, {}).get("name", key)
            stats["files"] += 1
            try:
                doc = fitz.open(pdf_path)
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    text = page.get_text()
                    stats["pages"] += 1
                    words = self._extract_words_from_text(text)
                    for w in words:
                        if w not in index:
                            index[w] = []
                        entry = {"dict": name, "page": page_num + 1}
                        if entry not in index[w]:
                            index[w].append(entry)
                    stats["words"] += len(words)
                doc.close()
            except Exception as e:
                return {"error": f"{pdf_path.name}: {e}"}

        self._index = index
        self._loaded = True

        # Сохраняем индекс в JSON (упрощённо — только для кэша, можно сжимать)
        try:
            import json
            # Сохраняем компактно
            self.index_file.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        return stats

    def load_index(self) -> bool:
        """Загружает индекс из файла."""
        if not self.index_file.exists():
            return False
        try:
            import json
            self._index = json.loads(self.index_file.read_text(encoding="utf-8"))
            self._loaded = True
            return True
        except Exception:
            return False

    def _get_lemma(self, word: str) -> Optional[str]:
        """Возвращает начальную форму (лемму) для падежей, склонений, мн. числа."""
        if not re.search(r"[а-яё]", word.lower()) or len(word) < 3:
            return None
        try:
            import pymorphy2
            morph = getattr(self, "_morph", None)
            if morph is None:
                self._morph = pymorphy2.MorphAnalyzer()
                morph = self._morph
            parsed = morph.parse(word)[0]
            return parsed.normal_form.lower() if parsed else None
        except ImportError:
            return self._get_lemma_simple(word)
        except Exception:
            return self._get_lemma_simple(word)

    def _get_lemma_simple(self, word: str) -> Optional[str]:
        """Простая эвристика: срез типичных окончаний (fallback без pymorphy2)."""
        w = word.lower()
        for suf in ("ового", "его", "ому", "ему", "ого", "ами", "ями", "ах", "ях", "ов", "ев", "ам", "ям", "ом", "ем", "ой", "ей", "а", "я", "у", "ю", "о", "е", "ы", "и"):
            if len(w) > len(suf) + 2 and w.endswith(suf):
                candidate = w[:-len(suf)]
                if not candidate or not re.match(r"^[а-яё]+$", candidate):
                    continue
                # Прилаг. на -овый: брендинговом → брендингов → брендинг
                if candidate.endswith(("ов", "ев")) and len(candidate) > 3:
                    base = candidate[:-2]
                    if base and re.match(r"^[а-яё]+$", base):
                        return base
                # Прилаг. на -ный: креативного → креативн → креативный
                if suf in ("ого", "ему", "его", "ом", "ем") and candidate.endswith("н") and len(candidate) > 2:
                    return candidate + "ый"  # креативн → креативный
                return candidate
        return None

    def search(self, word: str) -> list[dict]:
        """Ищет слово в словарях (включая словоформы: падежи, склонения, мн. число)."""
        if not self._loaded:
            self.load_index()
        if not self._index:
            return []

        w = self._normalize_word(word)
        # Прямое совпадение
        if w in self._index:
            return self._index[w]
        # Вариант с ё
        w_yo = w.replace("е", "ё")
        if w_yo in self._index:
            return self._index[w_yo]
        # Поиск по лемме (брендинга → брендинг)
        lemma = self._get_lemma(word)
        if lemma:
            lemma_norm = self._normalize_word(lemma)
            if lemma_norm in self._index:
                return self._index[lemma_norm]
            if lemma_norm.replace("е", "ё") in self._index:
                return self._index[lemma_norm.replace("е", "ё")]
        return []

    @property
    def is_ready(self) -> bool:
        """Есть ли загруженные словари и индекс."""
        return self._loaded and bool(self._index)

    @property
    def has_pdfs(self) -> bool:
        """Есть ли скачанные PDF."""
        return self.pdf_dir.exists() and any(self.pdf_dir.glob("*.pdf"))
