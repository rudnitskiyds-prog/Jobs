"""Фильтрация и классификация вакансий: финансы, «без опыта», Москва, сектор."""
from __future__ import annotations

import re
from functools import lru_cache

from . import config

W = r"[0-9a-zа-яё]"


@lru_cache(maxsize=None)
def _employer_patterns():
    pats = []
    for name, (sector, variants) in config.EMPLOYERS.items():
        for v in variants:
            v = v.strip(" ,\n").lower()
            if not v:
                continue
            tail = "" if len(v) <= 4 else f"{W}{{0,3}}"
            pats.append((len(v), re.compile(rf"(?<!{W}){re.escape(v)}{tail}(?!{W})"), name, sector))
    pats.sort(key=lambda p: -p[0])
    return pats


def find_employer(text: str) -> tuple[str | None, str | None]:
    """Находит известного работодателя, встречающегося в тексте раньше остальных."""
    low = text.lower()
    best = None
    for _, rx, name, sector in _employer_patterns():
        m = rx.search(low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name, sector)
    return (best[1], best[2]) if best else (None, None)


def sector_of(employer: str | None) -> str | None:
    if employer and employer in config.EMPLOYERS:
        return config.EMPLOYERS[employer][0]
    return None


def _has_any(low: str, words) -> bool:
    return any(w in low for w in words)


def guess_sector(text: str, employer: str | None) -> str:
    """text — название и короткий контекст (не всё описание), иначе сектор «размывается»."""
    sec = sector_of(employer)
    low = text.lower()
    if sec and sec != config.SECTOR_CORP:
        return sec
    if re.search(r"инвест|ценн\w+ бумаг|брокер|трейд|m&a|private equity|asset management|"
                 r"управлени\w+ активами|dcm|ecm|рынк\w+ капитал|valuation|оценк\w+ бизнес", low):
        return config.SECTOR_INVEST
    if re.search(r"банк|кредитн|ипотек|депозит|розничн\w+ бизнес|корпоративн\w+ бизнес", low):
        return config.SECTOR_BANK
    if re.search(r"аудит|консалт|consulting|налогов\w+ консульт|deal advisory|fdd", low):
        return config.SECTOR_AUDIT
    if re.search(r"страхов|актуар", low):
        return config.SECTOR_INSURANCE
    if re.search(r"финтех|fintech|платежн", low):
        return config.SECTOR_FINTECH
    return sec or config.SECTOR_CORP


def is_finance(text: str) -> bool:
    """Короткий текст (название, рубрика): достаточно одного финансового слова."""
    low = text.lower()
    return any(w in low for w in config.FINANCE_KEYWORDS)


def is_finance_desc(text: str, need: int = 2) -> bool:
    """Длинное описание: нужно несколько разных «сильных» финансовых терминов."""
    low = text.lower()
    return sum(1 for w in config.FINANCE_STRONG if w in low) >= need


def is_finance_vacancy(title: str, desc: str, employer: str | None) -> bool:
    sec = sector_of(employer)
    if sec and sec != config.SECTOR_CORP:
        return True
    return is_finance(title) or is_finance_desc(desc, 3)


def is_junior(text: str) -> bool:
    return _has_any(text.lower(), config.JUNIOR_KEYWORDS)


def is_senior_title(title: str) -> bool:
    low = title.lower()
    if _has_any(low, ["стажер", "стажёр", "intern", "младш", "junior", "trainee", "ассистент", "помощник"]):
        return False
    return any(re.search(p, low) for p in config.SENIOR_PATTERNS)


def requires_experience(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in config.SENIOR_PATTERNS[:2] + config.SENIOR_PATTERNS[6:7])


def is_excluded_title(title: str) -> bool:
    low = f" {title.lower()} "
    return _has_any(low, config.EXCLUDE_TITLE_KEYWORDS)


def location_ok(text: str) -> bool:
    """True, если в тексте есть Москва/удалёнка или вообще не указан другой город."""
    low = text.lower()
    if _has_any(low, config.MOSCOW_WORDS) or _has_any(low, config.REMOTE_WORDS):
        return True
    return not any(re.search(rf"(?<!{W}){re.escape(c)}", low) for c in config.OTHER_CITIES)


def guess_kind(text: str) -> str:
    low = text.lower()
    if re.search(r"стажир|стажер|стажёр|intern|trainee|практикант", low):
        return "Стажировка"
    if re.search(r"лидерск\w+ программ|программ\w+ (?:для|развития) (?:молод|студент|выпускник)|graduate program|кейс-чемпионат", low):
        return "Программа"
    return "Вакансия"


def score(v) -> float:
    """Чем выше — тем выше в выдаче при одинаковой дате."""
    s = 0.0
    if v.sector in config.PRIORITY_SECTORS:
        s += 3
    elif v.sector in (config.SECTOR_AUDIT, config.SECTOR_PUBLIC, config.SECTOR_INSURANCE, config.SECTOR_FINTECH):
        s += 1.5
    if v.salary_from or v.salary_to:
        s += 1
    if v.employer:
        s += 1
    if v.kind == "Стажировка":
        s += 0.5
    return s
