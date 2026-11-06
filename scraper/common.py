"""Общие утилиты: HTTP-сессия, модель вакансии, разбор текста."""
from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import requests

from . import config

log = logging.getLogger("scraper")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "ru,en;q=0.8"})
    return s


def fetch(session: requests.Session, url: str, *, params=None, headers=None,
          retries: int = 4, timeout: int = 25) -> requests.Response | None:
    """GET с повторами и экспоненциальной паузой. Возвращает None при неудаче."""
    delay = 2
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404, 401):
                log.warning("%s -> HTTP %s", url, r.status_code)
                return None
            log.info("%s -> HTTP %s (попытка %d)", url, r.status_code, attempt)
        except requests.RequestException as e:
            log.info("%s -> %s (попытка %d)", url, e.__class__.__name__, attempt)
        time.sleep(delay)
        delay *= 2
    log.warning("не удалось загрузить %s", url)
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()[:16]


def html_to_text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</(p|div|li|h\d|tr)>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<li[^>]*>", "• ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    text = html.unescape(fragment).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def clean_line(s: str) -> str:
    # убираем эмодзи и декоративные символы по краям
    s = re.sub(r"^[^\w«\"(]+", "", s, flags=re.U)
    s = re.sub(r"[\s|:—–\-•➖]+$", "", s)
    return s.strip()


@dataclass
class Vacancy:
    id: str
    title: str                       # должность
    employer: str | None             # работодатель
    url: str
    source: str                      # человекочитаемое имя источника
    source_type: str                 # telegram / vk / changellenge / futru / hh / trudvsem
    published: str | None = None     # ISO-дата публикации
    salary: str | None = None        # строка зарплаты для показа
    salary_from: int | None = None
    salary_to: int | None = None
    department: str | None = None    # подразделение / направление
    conditions: list[str] = field(default_factory=list)  # формат, график, занятость
    location: str | None = "Москва"
    kind: str = "Вакансия"           # Стажировка / Вакансия / Программа
    sector: str | None = None
    description: str = ""            # короткая выдержка
    tags: list[str] = field(default_factory=list)
    deadline: str | None = None
    apply_url: str | None = None      # прямая ссылка на отклик, если отличается от url
    # служебные
    first_seen: str | None = None
    last_seen: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ salary --
_NUM = r"\d[\d\s  .,]*\d|\d"


def _to_int(s: str, k: bool = False) -> int | None:
    digits = re.sub(r"[^\d.,]", "", s).replace(",", ".")
    if not digits:
        return None
    try:
        val = float(digits) if digits.count(".") == 1 and len(digits.split(".")[1]) <= 2 else float(digits.replace(".", ""))
    except ValueError:
        return None
    if k:
        val *= 1000
    if val < 1000:  # "60" без "к" — скорее всего тысячи
        val *= 1000
    return int(val)


SALARY_RE = re.compile(
    rf"(?:(?:з/?п|зарплата|оклад|доход|стипендия|оплата|salary)[^\n\d]{{0,25}})?"
    rf"(?:(от)\s*)?({_NUM})\s*(к|k|тыс\.?|т\.р\.?)?\s*"
    rf"(?:(?:до|-|–|—)\s*({_NUM})\s*(к|k|тыс\.?|т\.р\.?)?\s*)?"
    rf"(₽|руб\.?|рублей|р\.|rub|\$|usd|€|eur)",
    re.I,
)
SALARY_UPTO_RE = re.compile(rf"\bдо\s*({_NUM})\s*(к|k|тыс\.?)?\s*(₽|руб\.?|рублей|р\.)", re.I)
SALARY_WORDS_RE = re.compile(
    r"(з/?п|зарплат[аы]|оклад|оплата|стипендия)\s*[:\-–—]?\s*"
    r"(по (?:итогам|результатам) собеседовани[яй]|конкурентн\w+|договорн\w+|обсуждается[^\n.]*|"
    r"рыночн\w+|достойн\w+)",
    re.I,
)
PAID_RE = re.compile(r"\b(оплачиваем\w+|неоплачиваем\w+)\s+(стажиров\w+|практик\w+)", re.I)


def parse_salary(text: str) -> tuple[str | None, int | None, int | None]:
    m = SALARY_RE.search(text)
    if m:
        lo_k, hi_k = bool(m.group(3)), bool(m.group(5))
        lo = _to_int(m.group(2), lo_k or hi_k)
        hi = _to_int(m.group(4), hi_k or lo_k) if m.group(4) else None
        cur = m.group(6).lower()
        sym = "₽" if cur.startswith(("₽", "руб", "р", "rub")) else ("$" if cur in ("$", "usd") else "€")
        if lo and lo > 1_500_000 or hi and hi > 3_000_000:
            lo = hi = None  # призовой фонд/годовой бюджет, а не зарплата
        elif lo and lo >= 10000 or hi and hi >= 10000 or sym != "₽":
            fmt = lambda v: f"{v:,}".replace(",", " ")
            if lo and hi:
                s = f"{fmt(lo)} – {fmt(hi)} {sym}"
            elif m.group(1) or not hi:
                s = f"от {fmt(lo)} {sym}"
            else:
                s = f"{fmt(lo)} {sym}"
            return s, lo, hi
    m = SALARY_UPTO_RE.search(text)
    if m:
        hi = _to_int(m.group(1), bool(m.group(2)))
        if hi and hi >= 10000:
            return f"до {hi:,} ₽".replace(",", " "), None, hi
    m = SALARY_WORDS_RE.search(text)
    if m:
        return m.group(2)[0].upper() + m.group(2)[1:].rstrip(" ;,"), None, None
    m = PAID_RE.search(text)
    if m:
        return m.group(1).capitalize() + " " + m.group(2).lower(), None, None
    return None, None, None


# -------------------------------------------------------------- conditions --
CONDITION_PATTERNS = [
    (r"гибрид", "Гибрид"),
    (r"удал[её]нн?|удал[её]нк|remote|дистанционн", "Удалённо"),
    (r"(?:в|из) офисе?\b|офисн\w+ формат|офлайн", "Офис"),
    (r"полн\w+ (?:рабоч\w+ )?(?:день|занятост)|full[- ]time|5/2|пятидневк", "Полный день"),
    (r"частичн\w+ занятост|неполн\w+ (?:рабоч\w+ )?(?:день|занятост)|part[- ]time|20 часов|30 часов|по \d+ час", "Частичная занятость"),
    (r"гибк\w+ график|свободн\w+ график", "Гибкий график"),
    (r"совмещ\w+ с учеб|совмещать с учеб|учёбой|учебой", "Можно совмещать с учёбой"),
    (r"официальн\w+ трудоустройств|по тк|трудов\w+ договор", "Официальное оформление"),
    (r"оплачиваем\w+ стажиров|оплачиваемая практика|стажировка оплачивается", "Оплачиваемая"),
    (r"дмс", "ДМС"),
    (r"наставни|ментор", "Наставник"),
    (r"(?:возможност\w+|перспектив\w+) (?:трудоустройств|оффер|перехода в штат)|оффер по итогам|трудоустройство по итогам", "Возможен оффер в штат"),
    (r"практик\w+ для (?:вуза|университета)|зач[её]т практик|оформить практику", "Засчитывается как практика"),
    (r"английск", "Нужен английский"),
]


def parse_conditions(text: str) -> list[str]:
    low = text.lower()
    out = []
    for pat, label in CONDITION_PATTERNS:
        if re.search(pat, low) and label not in out:
            out.append(label)
    return out


def excerpt(text: str, limit: int = 600) -> str:
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > limit * 0.6 else cut) + "…"


LEGAL_FORMS = re.compile(
    r"^(?:ПАО|АО|ООО|ЗАО|ОАО|НАО|ФГБУ|ФГУП|ГБУ|ГКУ|АНО|ИП|ГК|"
    r"ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ|(?:ПУБЛИЧНОЕ |НЕПУБЛИЧНОЕ )?АКЦИОНЕРНОЕ ОБЩЕСТВО)\s*", re.I)


def clean_company(name: str | None) -> str | None:
    """«ООО "РОМАШКА"» -> «Ромашка»."""
    if not name:
        return name
    n = LEGAL_FORMS.sub("", name.strip())
    n = n.strip(" «»\"'“”")
    n = re.sub(r'\s*\(.*$', "", n) if len(n) > 50 else n
    if n.isupper() and len(n) > 4:
        n = " ".join(w if len(w) <= 3 else w.capitalize() for w in n.split())
    return n or name
