"""Логика проверки слов по официальным словарям РФ."""

import re
from typing import Optional

# Слова из словарей, если индекс пуст (Railway без /api/init)
KNOWN_IN_DICTS = {"ментор", "менторы"}
KNOWN_IN_DICTS_SOURCE = {
    "ментор": "Орфоэпический словарь (ИРЯ РАН)",
    "менторы": "Орфоэпический словарь (ИРЯ РАН)",
}

# Русские эквиваленты для слов, которых нет в словарях
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
    "faq": "Вопросы и ответы",
    "триал": "пробный период",
    "подписка": "абонемент",
    "дизайн": "оформление, проектирование",
    "маркетинг": "сбыт, продвижение",
    "колледж": "среднее специальное учебное заведение",
    "моушн": "движение, анимация",
    "майндсет": "установка, образ мыслей",
    "дедлайн": "срок",
    "фриланс": "удалённая работа",
    "консалтинг": "консультирование",
    "менеджмент": "управление",
    "менеджер": "руководитель, управляющий",
    "бренд": "торговая марка",
    "буллинг": "травля",
    "хайлайт": "основное, главное",
    "хайлайты": "основное, главное",
    "комьюнити": "сообщество",
    "воркшоп": "мастер-класс",
    "онбординг": "введение в должность",
    "апдейт": "обновление",
    "дайджест": "обзор",
    "драйв": "энергия, азарт",
    "инсайт": "понимание, прозрение",
    "лайфхак": "полезный совет",
    "логин": "имя пользователя",
    "лук": "образ, внешний вид",
    "мерч": "фирменная продукция",
    "селфи": "фотография себя",
    "скролл": "прокрутка",
    "спойлер": "раскрытие сюжета",
    "сторис": "история (в соцсетях)",
    "чек-лист": "список проверки",
    "шоурум": "выставочный зал",
}


def analyze_word(word: str, dict_manager=None) -> dict:
    """
    Проверяет слово по официальным словарям.
    - Если слово в словаре → можно использовать
    - Если слова нет в словаре → нет в словаре, рекомендуемая замена
    """
    word = word.strip()
    if not word:
        return {}
    wl = word.lower()

    in_dicts = []
    if dict_manager and dict_manager.is_ready:
        in_dicts = dict_manager.search(word)

    # Учитываем и индекс, и явный список слов, зафиксированных в словарях
    in_dict = len(in_dicts) > 0 or wl in KNOWN_IN_DICTS
    russian_equivalent = RUSSIAN_EQUIVALENTS.get(wl)

    if in_dict:
        dict_list = [{"dict": d["dict"], "page": d["page"]} for d in in_dicts]
        if not dict_list and wl in KNOWN_IN_DICTS:
            dict_name = KNOWN_IN_DICTS_SOURCE.get(wl, "Официальные словари РФ")
            dict_list = [{"dict": dict_name, "page": None}]
        return {
            "word": word,
            "in_dict": True,
            "status": "можно использовать",
            "in_official_dicts": dict_list,
            "russian_equivalent": None,
        }
    else:
        return {
            "word": word,
            "in_dict": False,
            "status": "нет в словаре",
            "in_official_dicts": [],
            "russian_equivalent": russian_equivalent,
        }

# CSS: свойства, значения, псевдоклассы — не контент сайта
_CSS_ARTIFACTS = frozenset({
    "absolute", "active", "after", "all", "alt", "alpha", "auto",
    "before", "block", "bold", "both", "bottom", "capitalize", "center",
    "circle", "column", "columns", "content", "cover", "dashed", "dotted",
    "embed", "end", "even", "fixed", "flex", "focus", "full", "grid",
    "hidden", "hover", "inherit", "initial", "inline", "inset", "italic",
    "justify", "left", "length", "line", "list", "lowercase", "medium",
    "middle", "none", "normal", "nowrap", "odd", "overflow", "pointer",
    "relative", "repeat", "right", "rotate", "row", "rows", "scale",
    "scroll", "self", "solid", "space", "start", "static", "stretch",
    "sticky", "thin", "top", "transparent", "underline", "unset", "uppercase",
    "visible", "wrapper", "wrap",
})
_CSS_PREFIX = re.compile(
    r"^(align|flex|grid|justify|place|gap|padding|margin|object|overflow|position|"
    r"text|font|border|outline|background|color|width|height|min|max|inset|"
    r"flex|grid|order|grow|shrink|basis|aspect|transition|transform|animation|"
    r"advance|address|has|is|wrapper)-",
    re.I
)
_CSS_SUFFIX = re.compile(
    r"-(content|items|self|wrapper|visible|hidden|desktop|mobile|height|width|"
    r"gap|padding|margin|background|radius|color|size|top|bottom|left|right|row|col)s?$",
    re.I
)

# JavaScript / DOM / API — остатки скриптов, не контент
_SCRIPT_ARTIFACTS = frozenset({
    "const", "let", "var", "function", "return", "typeof", "undefined", "null",
    "document", "window", "create", "createelement", "appendchild", "queryselector", "getelementbyid", "addeventlistener", "dataset", "innerhtml",
    "outerhtml", "textcontent", "navigator", "localstorage", "sessionstorage",
    "context", "counter", "dataset", "display",
})


def extract_words_from_html(html: str) -> list[str]:
    """Извлекает все слова со страницы для проверки по словарям.
    Игнорирует script, style, class, data-* и CSS-артефакты — не контент."""
    # Удаляем script, style, noscript — там JS/CSS, не контент
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<noscript[^>]*>[\s\S]*?</noscript>", " ", html, flags=re.I)
    html = re.sub(r"<!--[\s\S]*?-->", " ", html)
    html = re.sub(r'\bclass\s*=\s*["\'][^"\']*["\']', ' class=""', html, flags=re.I)
    html = re.sub(r'\bstyle\s*=\s*["\'][^"\']*["\']', ' style=""', html, flags=re.I)
    html = re.sub(r'\b(?:id|data-[a-z0-9\-]+|on\w+)\s*=\s*["\'][^"\']*["\']', ' ', html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    words = set()

    def _is_technical_artifact(w: str) -> bool:
        if w in _CSS_ARTIFACTS or w in _SCRIPT_ARTIFACTS:
            return True
        if "-" in w and (_CSS_PREFIX.search(w) or _CSS_SUFFIX.search(w)):
            return True
        # Короткие латинские без гласных (aaa, afadac) — class/id, не контент
        if len(w) <= 6 and w.isalpha() and re.match(r"^[a-z]+$", w):
            vowels = sum(1 for c in w if c in "aeiouy")
            if vowels == 0 or (len(w) >= 4 and vowels <= 1):
                return True
        return False

    for m in re.finditer(r"\b[а-яё][а-яё\-]{2,}\b", text, re.I):
        w = m.group(0).lower()
        if not _is_technical_artifact(w):
            words.add(w)
    for m in re.finditer(r"\b[a-z][a-z\-_]{2,}\b", text):
        w = m.group(0).lower()
        if not _is_technical_artifact(w):
            words.add(w)
    return sorted(words)
