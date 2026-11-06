"""Future Today (fut.ru) — каталог стажировок и программ для студентов."""
from __future__ import annotations

import json
import re
import time

from .. import classify, config
from ..common import Vacancy, clean_company, excerpt, fetch, log, make_id, parse_conditions, parse_salary

BASE = "https://fut.ru"
FINANCE_TAGS = {"Банки", "Финансы", "Аудит", "Аудит и консалтинг", "Консалтинг",
                "Инвестиции", "Страхование", "Финтех", "Экономика"}
CITY_TAGS = {"Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск", "Нижний Новгород", "Уфа"}
COND_TAGS = {"Гибрид", "Онлайн", "В офисе", "Гибкий график", "Полный день", "Берут с 3 курса",
             "Берут выпускников", "Берут 1-2 курс", "до 3 месяцев", "Лидерская программа"}


def _page(session, n: int):
    r = fetch(session, f"{BASE}/internship", params={"page": n} if n > 1 else None)
    if not r:
        return None, 0
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        return None, 0
    data = json.loads(m.group(1))["props"]["pageProps"]["data"]
    pubs = [p for g in data.get("publications", []) for p in (g if isinstance(g, list) else [g])]
    return pubs, data.get("meta", {}).get("last_page", 1)


def collect(session):
    pubs_all = {}
    first, last = _page(session, 1)
    if first is None:
        return []
    for p in first:
        pubs_all[p["uuid"]] = p
    for n in range(2, min(last, 15) + 1):
        pubs, _ = _page(session, n)
        for p in pubs or []:
            pubs_all[p["uuid"]] = p
        time.sleep(0.7)

    out = []
    for p in pubs_all.values():
        if p.get("event_status") not in (None, "published"):
            continue
        tags = [t["caption"] for t in p.get("tags", [])]
        company = clean_company((p.get("company") or {}).get("caption"))
        known, _ = classify.find_employer(company or "")
        company = known or company
        title = p.get("title") or ""
        desc = " ".join(filter(None, [p.get("description"), p.get("slogan")]))
        text = f"{title}\n{company}\n{desc}\n{' '.join(tags)}"
        sec = classify.sector_of(company)
        if company in (None, "", "Компания"):
            continue
        is_fin = bool(FINANCE_TAGS & set(tags)) or classify.is_finance(title) or \
            classify.is_finance_desc(desc, 2) or (sec and sec != config.SECTOR_CORP)
        if not is_fin:
            continue
        cities = CITY_TAGS & set(tags)
        if cities and "Москва" not in cities:
            continue
        link = p.get("generatedLink") or p.get("link") or ""
        url = link if link.startswith("http") else BASE + link.split("?")[0]
        conditions = [t for t in tags if t in COND_TAGS]
        for c in parse_conditions(desc):
            if c not in conditions:
                conditions.append(c)
        sal_tags = [t for t in tags if re.match(r"^(?:от|до)?\s*\d", t)]
        directions = [t for t in tags if t not in COND_TAGS and t not in CITY_TAGS and t not in sal_tags
                      and t not in ("Стажировка", "Вся Россия", "Другое", "Другая сфера")]
        salary, lo, hi = parse_salary(" ".join(sal_tags) + " ₽") if sal_tags else (None, None, None)
        v = Vacancy(
            id=make_id("futru", p["uuid"]),
            title=title,
            employer=company,
            url=url,
            source="Future Today (fut.ru)",
            source_type="futru",
            published=None,
            salary=salary or ("Оплачиваемая" if "Оплачиваемая" in conditions else None),
            salary_from=lo,
            salary_to=hi,
            department=("Направления: " + ", ".join(directions[:6])) if directions else None,
            conditions=conditions,
            location="Москва" if cities else "Москва / онлайн",
            kind="Программа" if "Лидерская программа" in tags else "Стажировка",
            sector=classify.guess_sector(title + " " + " ".join(directions), company),
            description=excerpt(desc),
            tags=tags,
            deadline=None,
        )
        v.score = classify.score(v)
        out.append(v)
    log.info("fut.ru: программ %d, подходящих %d", len(pubs_all), len(out))
    return out
