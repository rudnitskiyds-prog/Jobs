"""hh.ru — официальный API (нужен токен приложения в переменной окружения HH_TOKEN).

Без токена API отвечает 403, поэтому источник тихо пропускается.
Получить токен: https://dev.hh.ru → «Мои приложения» → создать приложение →
client_credentials токен приложения.
"""
from __future__ import annotations

import os
import time

from .. import classify, config
from ..common import Vacancy, clean_company, excerpt, fetch, html_to_text, log, make_id

API = "https://api.hh.ru/vacancies"


def _fmt_salary(sal: dict | None):
    if not sal:
        return None, None, None
    lo, hi, cur = sal.get("from"), sal.get("to"), sal.get("currency") or "RUR"
    sym = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€"}.get(cur, cur)
    f = lambda x: f"{int(x):,}".replace(",", " ")
    if lo and hi:
        s = f"{f(lo)} – {f(hi)} {sym}"
    elif lo:
        s = f"от {f(lo)} {sym}"
    elif hi:
        s = f"до {f(hi)} {sym}"
    else:
        return None, None, None
    if sal.get("gross") is True:
        s += " до вычета налогов"
    elif sal.get("gross") is False:
        s += " на руки"
    return s, lo, hi


def collect(session):
    token = os.environ.get("HH_TOKEN")
    if not token:
        log.info("hh.ru: HH_TOKEN не задан — источник пропущен")
        return []
    headers = {"Authorization": f"Bearer {token}", "HH-User-Agent": config.USER_AGENT}
    base = {"area": config.HH_AREA_MOSCOW, "per_page": 100, "period": config.MAX_POST_AGE_DAYS}
    queries = [dict(base, experience="noExperience", professional_role=config.HH_PROFESSIONAL_ROLES)]
    for q in config.HH_QUERIES:
        queries.append(dict(base, text=q, search_field="name", professional_role=config.HH_PROFESSIONAL_ROLES))

    items: dict[str, dict] = {}
    for params in queries:
        for page in range(0, 10):
            r = fetch(session, API, params=dict(params, page=page), headers=headers)
            if not r:
                break
            data = r.json()
            for it in data.get("items", []):
                items[it["id"]] = it
            if page + 1 >= data.get("pages", 0):
                break
            time.sleep(0.3)

    out = []
    for it in items.values():
        title = it.get("name", "")
        snip = it.get("snippet") or {}
        text = f"{title}\n{html_to_text(snip.get('requirement') or '')}\n{html_to_text(snip.get('responsibility') or '')}"
        exp = (it.get("experience") or {}).get("id")
        if classify.is_excluded_title(title) or classify.is_senior_title(title):
            continue
        if exp != "noExperience" and not classify.is_junior(title):
            continue
        employer = clean_company((it.get("employer") or {}).get("name"))
        known, _ = classify.find_employer(employer or "")
        salary, lo, hi = _fmt_salary(it.get("salary_range") or it.get("salary"))
        conditions = []
        for key in ("schedule", "employment", "employment_form"):
            val = (it.get(key) or {}).get("name")
            if val and val not in conditions:
                conditions.append(val)
        for wf in it.get("work_format") or []:
            if wf.get("name") and wf["name"] not in conditions:
                conditions.append(wf["name"])
        conditions.append("Без опыта" if exp == "noExperience" else (it.get("experience") or {}).get("name", ""))
        if it.get("accept_temporary"):
            conditions.append("Временная / проектная работа")
        dept = (it.get("department") or {}).get("name")
        v = Vacancy(
            id=make_id("hh", it["id"]),
            title=title,
            employer=known or employer,
            url=it.get("alternate_url") or f"https://hh.ru/vacancy/{it['id']}",
            source="hh.ru",
            source_type="hh",
            published=it.get("published_at"),
            salary=salary,
            salary_from=lo,
            salary_to=hi,
            department=dept,
            conditions=[c for c in conditions if c],
            location=((it.get("address") or {}).get("metro") or {}).get("station_name") and
                     "Москва, м. " + it["address"]["metro"]["station_name"] or "Москва",
            kind=classify.guess_kind(title),
            sector=classify.guess_sector(title, known),
            description=excerpt(text.split("\n", 1)[1] if "\n" in text else ""),
        )
        v.score = classify.score(v)
        out.append(v)
    log.info("hh.ru: вакансий %d, подходящих %d", len(items), len(out))
    return out
