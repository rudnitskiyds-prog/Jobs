"""«Работа России» (trudvsem.ru) — открытое API вакансий, регион Москва."""
from __future__ import annotations

import re
import time

from .. import classify, config
from ..common import Vacancy, clean_company, excerpt, fetch, html_to_text, log, make_id, parse_conditions

API = "http://opendata.trudvsem.ru/api/v1/vacancies/region/{region}"
QUERIES = config.TRUDVSEM_QUERIES + [
    "экономист", "финансист", "финансовый аналитик", "аудитор", "бухгалтер", "кредитный специалист",
    "специалист банка", "аналитик", "казначей", "риск",
]


def collect(session):
    seen: dict[str, dict] = {}
    for q in QUERIES:
        r = fetch(session, API.format(region=config.TRUDVSEM_REGION_MOSCOW),
                  params={"text": q, "limit": 100, "offset": 0})
        if not r:
            continue
        try:
            items = r.json().get("results", {}).get("vacancies", []) or []
        except ValueError:
            continue
        for it in items:
            v = it.get("vacancy", {})
            if v.get("id"):
                seen[v["id"]] = v
        time.sleep(0.5)

    out = []
    for v in seen.values():
        title = (v.get("job-name") or "").strip()
        req = v.get("requirement") or {}
        exp = req.get("experience")
        duty = html_to_text(v.get("duty") or "")
        reqs = html_to_text(v.get("requirements") or "")
        text = f"{title}\n{duty}\n{reqs}\n{(v.get('category') or {}).get('specialisation', '')}"
        if classify.is_excluded_title(title) or classify.is_senior_title(title):
            continue
        try:
            exp_years = int(exp) if exp is not None else 0
        except (TypeError, ValueError):
            exp_years = 0
        if exp_years >= 2 or (exp_years == 1 and not classify.is_junior(title)):
            continue
        spec = (v.get("category") or {}).get("specialisation", "")
        company = clean_company((v.get("company") or {}).get("name"))
        emp_known, _ = classify.find_employer(company or "")
        fin_spec = re.search(r"банк|финанс|бухгалт|страхов|консалтинг|инвест", spec, re.I)
        if not (classify.is_finance(title) or (fin_spec and classify.is_finance_desc(text, 1))
                or classify.is_finance_vacancy(title, "", emp_known)):
            continue
        lo, hi = v.get("salary_min") or None, v.get("salary_max") or None
        lo = lo if lo and lo >= 1000 else None
        hi = hi if hi and hi >= 1000 else None
        if lo and hi and lo == hi and str(v.get("salary", "")).startswith("от"):
            hi = None
        fmt = lambda x: f"{int(x):,}".replace(",", " ")
        salary = (f"{fmt(lo)} – {fmt(hi)} ₽" if lo and hi and hi != lo else
                  f"от {fmt(lo)} ₽" if lo else f"до {fmt(hi)} ₽" if hi else None)
        conditions = [c for c in [v.get("schedule"), v.get("employment")] if c]
        conditions.append("Без опыта" if exp in (0, "0") else (f"Опыт от {exp} г." if exp else "Опыт не указан"))
        for c in parse_conditions(duty + "\n" + reqs):
            if c not in conditions:
                conditions.append(c)
        addr = ((v.get("addresses") or {}).get("address") or [{}])[0].get("location")
        item = Vacancy(
            id=make_id("trudvsem", v["id"]),
            title=title,
            employer=emp_known or company,
            url=v.get("vac_url") or "https://trudvsem.ru",
            source="Работа России",
            source_type="trudvsem",
            published=v.get("creation-date"),
            salary=salary,
            salary_from=int(lo) if lo else None,
            salary_to=int(hi) if hi else None,
            department=("Сфера: " + spec) if spec else None,
            conditions=conditions,
            location=addr or "Москва",
            kind=classify.guess_kind(title),
            sector=classify.guess_sector(title, emp_known),
            description=excerpt(("Обязанности: " + duty + "\n" if duty else "") + ("Требования: " + reqs if reqs else "")),
        )
        item.score = classify.score(item)
        out.append(item)
    log.info("trudvsem: вакансий %d, подходящих %d", len(seen), len(out))
    return out
