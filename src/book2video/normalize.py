"""Text normalisation for narration.

This module only rewrites things a speech synthesiser cannot pronounce well on
its own: unsupported symbols, abbreviations, units, percentages, year cases and
URLs.  It deliberately does **not** touch word stress: TeraTTSv2 owns that and
its output is used as-is.

TeraTTSv2 already expands plain numbers and most dates through ``num2words``.
We pre-expand the cases it gets wrong (``в 2024 году`` -> prepositional
ordinal) and the symbols it drops (``%``).
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from num2words import num2words

_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bт\.\s*е\.", re.I), "то есть"),
    (re.compile(r"\bт\.\s*д\.", re.I), "так далее"),
    (re.compile(r"\bт\.\s*п\.", re.I), "тому подобное"),
    (re.compile(r"\bт\.\s*к\.", re.I), "так как"),
    (re.compile(r"\bдр\.", re.I), "другие"),
    (re.compile(r"\bнапр\.", re.I), "например"),
    (re.compile(r"\bрис\.", re.I), "рисунок"),
    (re.compile(r"\bтабл\.", re.I), "таблица"),
    (re.compile(r"\bим\.", re.I), "имени"),
    (re.compile(r"\bпроф\.", re.I), "профессор"),
    (re.compile(r"\bакад\.", re.I), "академик"),
)

_YEAR_RE = re.compile(r"\b(1[89]\d\d|20\d\d)\s*(годах|годы|году|года|год|гг\.|г\.)", re.I)
_SENTENCE_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,6})(?=\.(?:\s|$))")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_MONEY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:₽|руб\.?)", re.I)
_DOLLAR_RE = re.compile(r"\$\s*(\d+(?:[.,]\d+)?)")
_EURO_RE = re.compile(r"€\s*(\d+(?:[.,]\d+)?)")
_UNIT_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(тыс\.|млн|млрд|трлн|км|кг|мин|сек|ч)\b", re.I
)

_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_ORDINAL_ENDINGS = {
    "gen": (("ый", "ого"), ("ий", "его"), ("ой", "ого")),
    "prep": (("ый", "ом"), ("ий", "ем"), ("ой", "ом")),
}


def _ordinal_year(year: int, case: str) -> str:
    words = num2words(year, lang="ru", to="ordinal")
    if case == "nom":
        return words
    for old, new in _ORDINAL_ENDINGS.get(case, ()):
        if words.endswith(old):
            return words[: -len(old)] + new
    return words


def _year_replacement(match: re.Match[str]) -> str:
    year = int(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "гг.":
        return f"{match.group(1)} годы"
    if suffix in {"году"}:
        case = "prep"
    elif suffix in {"года"}:
        case = "gen"
    elif suffix in {"годах", "годы"}:
        case = "nom"
    elif suffix in {"г.", "г"}:
        case = "prep" if match.string[max(0, match.start() - 2) : match.start()].strip().lower() == "в" else "nom"
    else:
        case = "nom"
    word = _ordinal_year(year, case)
    if suffix in {"г.", "г"}:
        return f"{word} году" if case == "prep" else f"{word} год"
    if suffix in {"годах", "годы"}:
        return f"{word} {suffix}"
    return f"{word} {suffix}"


def _number_form(value: str, one: str, few: str, many: str) -> str:
    # Decimals take the genitive singular: «3,5 миллиона», «15,5 процента».
    if "," in value or "." in value:
        return few
    try:
        number = int(value)
    except ValueError:
        return many
    if number % 100 in (11, 12, 13, 14):
        return many
    if number % 10 == 1:
        return one
    if number % 10 in (2, 3, 4):
        return few
    return many


def _percent_replacement(match: re.Match[str]) -> str:
    value = match.group(1)
    return f"{value} {_number_form(value, 'процент', 'процента', 'процентов')}"


def _money_replacement(match: re.Match[str]) -> str:
    value = match.group(1)
    return f"{value} {_number_form(value, 'рубль', 'рубля', 'рублей')}"


def _unit_replacement(match: re.Match[str]) -> str:
    value, unit = match.group(1), match.group(2).lower()
    if unit == "тыс.":
        return f"{value} {_number_form(value, 'тысяча', 'тысячи', 'тысяч')}"
    if unit == "млн":
        return f"{value} {_number_form(value, 'миллион', 'миллиона', 'миллионов')}"
    if unit == "млрд":
        return f"{value} {_number_form(value, 'миллиард', 'миллиарда', 'миллиардов')}"
    if unit == "трлн":
        return f"{value} {_number_form(value, 'триллион', 'триллиона', 'триллионов')}"
    if unit == "км":
        return f"{value} {_number_form(value, 'километр', 'километра', 'километров')}"
    if unit == "кг":
        return f"{value} {_number_form(value, 'килограмм', 'килограмма', 'килограммов')}"
    if unit == "мин":
        return f"{value} {_number_form(value, 'минута', 'минуты', 'минут')}"
    if unit == "сек":
        return f"{value} {_number_form(value, 'секунда', 'секунды', 'секунд')}"
    if unit == "ч":
        return f"{value} {_number_form(value, 'час', 'часа', 'часов')}"
    return match.group(0)


def normalize_for_speech(text: str) -> str:
    """Return text that TeraTTSv2 can pronounce without mangling."""
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = text.replace("\u00ad", "").replace("\u200b", "")
    text = text.replace("…", "...")
    text = re.sub(r"\s+", " ", text).strip()

    # TeraTTSv2 has no em/en dash in its vocabulary: an em dash becomes a
    # comma pause, an en dash becomes a plain hyphen.
    text = re.sub(r"^\s*[—–]\s*", "", text)
    text = text.replace("—", ",").replace("–", "-")
    text = text.replace("→", " к ").replace("±", " плюс-минус ")
    text = text.replace("°", " градусов ").replace("×", " на ")
    # A bare angle bracket is read by Tera as a malformed language tag.
    text = text.replace(">", " больше ").replace("<", " меньше ")
    text = text.replace("©", " копирайт ").replace("®", "").replace("™", "")

    # A raw plus sign would be read as Tera's stress marker.
    text = text.replace("+", " плюс ")
    text = text.replace("=", " равно ")
    text = text.replace("&", " и ")
    text = text.replace("№", " номер ")

    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)

    text = _YEAR_RE.sub(_year_replacement, text)
    # TeraTTSv2's number regex deliberately skips digits followed by a dot
    # (to protect version numbers), so "рисунок 6." loses the number.
    text = _SENTENCE_NUMBER_RE.sub(
        lambda m: num2words(int(m.group(1)), lang="ru"), text
    )
    text = _PERCENT_RE.sub(_percent_replacement, text)
    text = _MONEY_RE.sub(_money_replacement, text)
    text = _DOLLAR_RE.sub(lambda m: f"{m.group(1)} долларов", text)
    text = _EURO_RE.sub(lambda m: f"{m.group(1)} евро", text)
    text = _UNIT_RE.sub(_unit_replacement, text)

    # Units that are not covered above.
    text = re.sub(r"\bтыс\.", "тысяч", text, flags=re.I)
    text = re.sub(r"\bмлн\b", "миллионов", text, flags=re.I)
    text = re.sub(r"\bмлрд\b", "миллиардов", text, flags=re.I)
    text = re.sub(r"\bтрлн\b", "триллионов", text, flags=re.I)

    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def spoken_url(url: str) -> str:
    """Turn a URL into a short human-readable phrase for narration.

    The domain and path are kept; query strings and fragments are dropped
    because they are unlistenable and are already available in the QR frame.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts: list[str] = [host] if host else []
    for segment in parsed.path.split("/"):
        segment = unquote(segment).strip()
        if segment:
            parts.append(segment)
    if not parts:
        return "ссылка"

    spoken = ", ".join(parts)
    spoken = spoken.replace(".", " точка ")
    spoken = spoken.replace("-", " дефис ")
    spoken = spoken.replace("_", " подчёркивание ")
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken


def link_narration(url: str) -> str:
    return f"Ссылка: {spoken_url(url)}."


def is_domain_anchor(text: str) -> bool:
    """True when the visible link text is itself a domain (e.g. ``Mail.ru``)."""
    return bool(re.fullmatch(r"[\w-]+(?:\.[\w-]+)+(?:/\S*)?", text.strip(), re.I))


_DEICTIC_ANCHORS = {
    "здесь",
    "тут",
    "ссылка",
    "по ссылке",
    "подробнее",
    "скачать",
    "смотреть",
    "посмотреть",
    "открыть",
}


def needs_qr(link_text: str, url: str) -> bool:
    """Decide whether a link is a real reference worth a QR frame."""
    anchor = link_text.strip().lower()
    if is_domain_anchor(anchor):
        return False
    if anchor in _DEICTIC_ANCHORS:
        return True
    return len(url) > 80
