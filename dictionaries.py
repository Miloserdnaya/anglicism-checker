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
        """Возвращает начальную форму (лемму) для падежей, склонений, мн. числа.
        Для составных слов с дефисом (арт-директором) сначала пробуем эвристику — pymorphy2
        может давать некорректный результат."""
        w = word.lower()
        if not re.search(r"[а-яё]", w) or len(word) < 3:
            return None
        # Составные слова: арт-директорами → арт-директор (эвристика надёжнее)
        if "-" in w:
            simple = self._get_lemma_simple(word)
            if simple:
                return simple
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
        """Простая эвристика: срез типичных окончаний (fallback без pymorphy2).
        Поддерживает составные слова и простые глагольные формы."""
        w = word.lower()
        reflexive = False
        if w.endswith(("ся", "сь")):
            reflexive = True
            w = w[:-2]
        reflexive_tail = "ся" if reflexive else ""
        word_ok = re.compile(r"^[а-яё\-]+$")  # буквы и дефис для составных
        index_lookup = getattr(self, "_index", {}) or {}

        def _pick_form(forms: list[str]) -> Optional[str]:
            forms = [f for f in forms if f]
            if not forms:
                return None
            if index_lookup:
                for form in forms:
                    if form in index_lookup:
                        return form
            return forms[0]

        if w.endswith("ею") and len(w) > 3:
            base = w[:-1]  # убираем только "ю": музею → музе, Андрею → Андре
            if index_lookup:
                if base + "й" in index_lookup:
                    return base + "й"
                if base + "я" in index_lookup:
                    return base + "я"

        # Составные с дефисом: арт-директорами → арт-директор (до verb_present)
        if "-" in w:
            for suf in ("ами", "ями", "ому", "ему", "ов", "ев", "ах", "ях", "а", "я", "у", "ю"):
                if len(w) > len(suf) + 2 and w.endswith(suf):
                    candidate = w[:-len(suf)]
                    if candidate and word_ok.match(candidate):
                        if candidate in index_lookup:
                            return candidate
                        c_yo = candidate.replace("е", "ё")
                        if c_yo in index_lookup:
                            return c_yo

        verb_past_suffixes = ("л", "ла", "ло", "ли")
        for suf in verb_past_suffixes:
            if len(w) > len(suf) + 2 and w.endswith(suf):
                candidate = w[:-len(suf)]
                if not candidate or not word_ok.match(candidate):
                    continue
                forms = [
                    candidate + "ть" + reflexive_tail,
                    candidate + "ти" + reflexive_tail,
                ]
                picked = _pick_form(forms)
                if picked:
                    return picked

        # Причастия (до личных форм — -вший/-щий не должны матчиться с -й)
        part_inf_endings = ["ть", "ти", "ить", "ать", "ять", "еть"]
        participle_suffixes = [
            ("ующий", part_inf_endings), ("ующая", part_inf_endings), ("ующее", part_inf_endings), ("ующие", part_inf_endings),
            ("ющий", part_inf_endings), ("ющая", part_inf_endings), ("ющее", part_inf_endings), ("ющие", part_inf_endings),
            ("ящий", part_inf_endings), ("ящая", part_inf_endings), ("ящее", part_inf_endings), ("ящие", part_inf_endings),
            ("вший", part_inf_endings), ("вшая", part_inf_endings), ("вшее", part_inf_endings), ("вшие", part_inf_endings),
            ("емый", part_inf_endings), ("емая", part_inf_endings), ("емое", part_inf_endings), ("емые", part_inf_endings),
            ("омый", part_inf_endings), ("омая", part_inf_endings), ("омое", part_inf_endings), ("омые", part_inf_endings),
            ("енный", part_inf_endings + ["ить", "еть"]), ("енная", part_inf_endings + ["ить", "еть"]),
            ("ённый", part_inf_endings + ["ить", "еть"]), ("ённая", part_inf_endings + ["ить", "еть"]),
            ("нный", part_inf_endings), ("нная", part_inf_endings), ("нное", part_inf_endings), ("нные", part_inf_endings),
            ("тый", part_inf_endings + ["ь"]), ("тая", part_inf_endings + ["ь"]), ("тое", part_inf_endings + ["ь"]), ("тые", part_inf_endings + ["ь"]),
        ]
        for suf, endings in participle_suffixes:
            if len(w) > len(suf) + 1 and w.endswith(suf):
                stem = w[:-len(suf)]
                if not stem or not word_ok.match(stem):
                    continue
                ends = list(dict.fromkeys(endings))
                candidates = [stem + e + reflexive_tail for e in ends if e != "ь" or stem]
                if "ь" in ends and stem and len(stem) > 1:
                    candidates.append(stem[:-1] + "ть" + reflexive_tail)
                trimmed = stem[:-1] if len(stem) > 2 else ""
                if trimmed:
                    candidates += [trimmed + e + reflexive_tail for e in ends if e != "ь"]
                    if "ь" in ends:
                        candidates.append(trimmed + "ть" + reflexive_tail)
                picked = _pick_form(candidates)
                if picked:
                    return picked

        verb_present_suffixes = (
            "ете", "ёте", "ите",
            "ем", "ём", "им",
            "ут", "ют", "ат", "ят",
            "ешь", "ёшь", "ишь",
            "ет", "ёт", "ит",
            "у", "ю",
            "й", "йте", "ьте", "и", "ь",
        )
        for suf in verb_present_suffixes:
            if len(w) > len(suf) + 1 and w.endswith(suf):
                if suf in ("ю", "у") and w.endswith("ную"):
                    continue
                stem = w[:-len(suf)]
                if not stem or not word_ok.match(stem):
                    continue
                endings_to_try = ["ть", "ти", "ить", "ать", "ять", "еть"]
                if stem.endswith(("ч", "щ")):
                    endings_to_try.append("ь")
                if stem.endswith(("г", "ж")):
                    endings_to_try.append("чь")
                candidates = [
                    stem + end + reflexive_tail for end in endings_to_try if stem
                ]
                trimmed = stem[:-1] if len(stem) > 2 else ""
                if trimmed:
                    candidates += [
                        trimmed + end + reflexive_tail for end in endings_to_try
                    ]
                if stem.endswith("ш"):
                    alt_stem = stem[:-1] + "с"
                    candidates += [alt_stem + "ать" + reflexive_tail, alt_stem + "ить" + reflexive_tail]
                if stem.endswith("ж"):
                    candidates += [stem[:-1] + "з" + "ать" + reflexive_tail, stem[:-1] + "з" + "ить" + reflexive_tail]
                    alt_stem = stem[:-1] + "г"
                    candidates += [alt_stem + "чь" + reflexive_tail]
                # Будущее 3л.: откроется → открыться (откро → открыть)
                if stem.endswith("о") and suf in ("ет", "ют", "ут", "ат", "ят") and len(stem) > 2:
                    candidates += [stem[:-1] + "ыть" + reflexive_tail]
                # Повелит. -йте/-й: -овать/-евать (используйте → использовать)
                if suf in ("йте", "й") and stem.endswith("й") and len(stem) > 2:
                    base = stem[:-1]
                    candidates += [
                        base + "ать" + reflexive_tail,
                        base + "ять" + reflexive_tail,
                        base + "овать" + reflexive_tail,
                        base + "евать" + reflexive_tail,
                    ]
                # Повелит. -ите: назовите → назвать (ово → ва)
                if suf == "ите" and stem.endswith("ови") and len(stem) > 4:
                    candidates += [stem[:-2] + "вать" + reflexive_tail]
                picked = _pick_form(candidates)
                if picked:
                    return picked

        gerund_suffixes = {
            "вшись": ["ться"],
            "шись": ["ться"],
            "вши": ["ть", "ти"],
            "ши": ["ть", "ти"],
            "в": ["ть", "ти"],
            "я": ["ть", "ти"],
            "ючи": ["ть", "ти"],
            "учи": ["ть", "ти"],
        }
        for suf, endings in gerund_suffixes.items():
            if len(w) > len(suf) + 1 and w.endswith(suf):
                stem = w[:-len(suf)]
                if not stem or not word_ok.match(stem):
                    continue
                candidates = [stem + end + reflexive_tail for end in endings]
                picked = _pick_form(candidates)
                if picked:
                    return picked

        # Сущ. твор. мн. -ами/-ями: маркетологами → маркетолог (ранняя проверка)
        for instr_pl in ("ами", "ями"):
            if len(w) > len(instr_pl) + 3 and w.endswith(instr_pl):
                stem_instr = w[:-len(instr_pl)]
                if stem_instr and stem_instr[-1] not in "аеёиоуыэюя" and word_ok.match(stem_instr):
                    if stem_instr in index_lookup:
                        return stem_instr

        # Существительные на -ие/-ние: род.п. структурирования → структурирование
        if len(w) > 5 and w.endswith("ия"):
            stem_ie = w[:-2]  # структурировани
            if stem_ie and len(stem_ie) >= 4 and word_ok.match(stem_ie):
                if stem_ie.endswith(("и", "н")):  # типично для -ие/-ние
                    lemma_ie = stem_ie + "е"  # структурирование
                    picked = _pick_form([lemma_ie])
                    if picked:
                        return picked

        adjective_suffixes = {"ого", "ему", "его", "ом", "ем", "ой", "ою", "ею", "ую", "ые", "ых", "ыми", "ими"}
        multi_suffixes = ("ового", "его", "ому", "ему", "ого", "ами", "ями", "ах", "ях", "ов", "ев",
                          "ам", "ям", "ом", "ем", "ой", "ей", "ую", "ые", "ых", "ыми", "ими", "ою", "ею")
        single_suffixes = ("а", "я", "у", "ю", "о", "е", "ы", "и")
        general_suffixes = multi_suffixes + single_suffixes
        for suf in general_suffixes:
            if len(w) > len(suf) + 2 and w.endswith(suf):
                candidate = w[:-len(suf)]
                if not candidate or not word_ok.match(candidate):
                    continue
                # Прилаг. на -овый: брендинговом → брендингов → брендинг
                if candidate.endswith(("ов", "ев")) and len(candidate) > 3:
                    base = candidate[:-2]
                    if base and word_ok.match(base):
                        return base
                # Прилаг. на -ный/-ной/-ний: востребованн→востребованный, ручн→ручной
                if suf in adjective_suffixes and candidate.endswith("н") and len(candidate) > 2:
                    adj_picked = _pick_form([
                        candidate + "ый", candidate + "ой", candidate + "ий", candidate + "ный",
                    ])
                    if adj_picked:
                        return adj_picked
                # Повелит. на -и: выдели → выделить (и там, где verb_present не сработал)
                if suf == "и" and candidate and candidate[-1] not in "аеёиоуыэюя":
                    verb_lemma = _pick_form([
                        candidate + "ить", candidate + "еть", candidate + "ать", candidate + "ять",
                    ])
                    if verb_lemma:
                        return verb_lemma
                picked = _pick_form(
                    [
                        candidate,
                        candidate + "й",
                        candidate + "я",
                        candidate + "а",  # формулировками → формулировка
                        candidate + "ый",
                        candidate + "ий",
                        candidate + "ой",
                    ]
                )
                if picked:
                    return picked

        short_adj_suffixes = ("на", "но", "ны", "ен", "ено", "ены", "ён", "ёно", "ёны")
        for suf in short_adj_suffixes:
            if len(w) > len(suf) + 1 and w.endswith(suf):
                if suf in ("на", "но", "ны") and w[-2] == "н":
                    stem = w[:-1]
                else:
                    stem = w[:-len(suf)]
                if not stem or not word_ok.match(stem):
                    continue
                candidates = [stem + "ый", stem + "ий", stem + "ой"]
                picked = _pick_form(candidates)
                if picked:
                    return picked

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
