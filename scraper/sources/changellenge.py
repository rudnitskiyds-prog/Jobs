"""Changellenge >> — каталог вакансий и стажировок (changellenge.com/vacancy/)."""
from __future__ import annotations

import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import classify, extract
from ..common import Vacancy, excerpt, fetch, log, make_id, parse_conditions, parse_salary

BASE = "https://changellenge.com"
LISTINGS = [
    "/vacancy/filter/stazhirovki-v-moskve/",
    "/vacancy/filter/city-is-" + quote("москва") + "/work_experience-is-" + quote("нет опыта") + "/apply/",
]
MAX_PAGES = 8
MAX_DETAILS = 150


def _listing_links(session) -> list[str]:
    seen: list[str] = []
    for path in LISTINGS:
        for page in range(1, MAX_PAGES + 1):
            url = BASE + path + (f"?PAGEN_1={page}" if page > 1 else "")
            r = fetch(session, url)
            if not r:
                break
            links = re.findall(r'href="(/vacancy/[a-z0-9-]+/)"', r.text)
            new = [l for l in dict.fromkeys(links) if l not in seen]
            if not new:
                break
            seen.extend(new)
            time.sleep(0.7)
    return seen


def _detail(session, path: str) -> Vacancy | None:
    url = BASE + path
    r = fetch(session, url)
    if not r:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one('[itemprop="title"]')
    if not title_el:
        return None
    title = title_el.get_text(" ", strip=True)
    org = soup.select_one('[itemprop="hiringOrganization"] meta[itemprop="name"]')
    employer = org["content"].strip() if org and org.get("content") else None
    posted = soup.select_one('meta[itemprop="datePosted"]')
    meta = {}
    for li in soup.select("ul.meta li"):
        lab = li.select_one(".meta__label")
        val = li.select_one(".meta__value")
        if lab and val:
            meta[lab.get_text(strip=True)] = val.get_text(" ", strip=True)
    sal_el = soup.select_one(".salary")
    salary_text = sal_el.get_text(" ", strip=True) if sal_el else ""
    desc_el = soup.select_one('[itemprop="description"]')
    desc = desc_el.get_text("\n", strip=True) if desc_el else ""

    city = meta.get("Город", "")
    if city and "москв" not in city.lower() and "удал" not in city.lower():
        return None
    if classify.is_excluded_title(title) or classify.is_senior_title(title):
        return None
    exp = meta.get("Опыт", "").lower()
    if exp and "нет" not in exp and not classify.is_junior(title):
        return None
    if not classify.is_finance_vacancy(title, desc, employer):
        return None

    salary, lo, hi = parse_salary(salary_text)
    if not salary and salary_text:
        salary = re.sub(r"^З/П\s*", "", salary_text).strip().capitalize() or None
    conditions = []
    for key in ("Формат", "Занятость"):
        if meta.get(key):
            conditions.append(meta[key])
    if meta.get("Опыт"):
        conditions.append("Опыт: " + meta["Опыт"].lower())
    for c in parse_conditions(desc):
        if c not in conditions:
            conditions.append(c)
    kind = meta.get("Тип вакансии", "").capitalize() or classify.guess_kind(title)
    dept = extract.pick_department(title + "\n" + desc)
    parts = re.split(r"\s+[-–—]\s+|,\s+(?=(?:департамент|групп|отдел|управлени|практик))", title, maxsplit=1, flags=re.I)
    if len(parts) == 2 and len(parts[0]) >= 4:
        title, dept = parts[0], parts[1]
    v = Vacancy(
        id=make_id("changellenge", url),
        title=title[0].upper() + title[1:],
        employer=employer,
        url=url,
        source="Changellenge >>",
        source_type="changellenge",
        published=posted["content"] if posted else None,
        salary=salary,
        salary_from=lo,
        salary_to=hi,
        department=dept[0].upper() + dept[1:] if dept else None,
        conditions=conditions,
        location=city or "Москва",
        kind="Стажировка" if "стаж" in kind.lower() else ("Вакансия" if kind else classify.guess_kind(title)),
        sector=classify.guess_sector(title, employer),
        description=excerpt(desc),
    )
    v.score = classify.score(v)
    return v


def collect(session):
    links = _listing_links(session)
    log.info("changellenge: найдено ссылок %d", len(links))
    out = []
    for path in links[:MAX_DETAILS]:
        v = _detail(session, path)
        if v:
            out.append(v)
        time.sleep(0.7)
    log.info("changellenge: подходящих %d", len(out))
    return out
