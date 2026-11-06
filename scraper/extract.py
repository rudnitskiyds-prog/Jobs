"""Извлечение полей вакансии из свободного текста постов (Telegram, VK)."""
from __future__ import annotations

import re

from . import classify, config
from .common import Vacancy, clean_line, excerpt, make_id, parse_conditions, parse_salary

ROLE_WORDS = re.compile(
    r"стаж[её]р|стажиров|intern|trainee|практикант|аналитик|analyst|экономист|менеджер|manager|"
    r"специалист|specialist|ассистент|assistant|консультант|consultant|аудитор|auditor|"
    r"associate|финансист|казначе|риск|андеррайтер|актуарий|трейдер|брокер|юниор|junior|младш|"
    r"помощник|эксперт|operations|операционист|кредитн",
    re.I,
)

DEPT_RE = re.compile(
    r"(?:подразделени\w*|департамент|управлени[ея]|отдел|дирекци[яи]|блок|направлени[ея]|команд[уаеы]|"
    r"практик[ауи]|department|team|desk)\s*[:\-–—]?\s*"
    r"([«\"]?[A-ZА-ЯЁ0-9][^\n.;!?]{2,80})",
)
EMPLOYER_RE = re.compile(
    r"(?i:компани[яи]|работодатель|employer|организаци[яи])\s*[:\-–—]\s*([«\"A-ZА-ЯЁ][^\n;|]{1,60})"
)
EMPLOYER_LINE_RE = re.compile(r"^\s*(?:в|во)\s+([«\"]?[A-ZА-ЯЁ][^—\n,(]{1,40}?)\s*(?:—|–|,|\(|$)", re.M)
EMPLOYER_IN_RE = re.compile(
    r"(?:стаж[её]р\w*|стажировк\w+|ваканси\w+|аналитик\w*|позици\w+|ищ\w+|приглаша\w+)\s+"
    r"(?:в|во)\s+(?:компани\w+\s+)?([«\"]?[A-ZА-ЯЁ][\w&.\-]+(?:[ \-][A-ZА-ЯЁ][\w&.\-]+){0,2}[»\"]?)"
)
DEADLINE_RE = re.compile(
    r"(?:дедлайн|deadline|при[её]м заявок до|заявки принимаются до|регистраци\w+ до|подать заявку до|"
    r"откликнуться до|до)\s*[:\-–—]?\s*(\d{1,2}(?:\.\d{1,2}(?:\.\d{2,4})?|\s+(?:января|февраля|марта|"
    r"апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)))",
    re.I,
)


TITLE_ROLE = re.compile(
    r"стаж[её]р|стажиров|intern|trainee|практикант|аналитик|analyst|экономист|менеджер|manager|"
    r"специалист|specialist|ассистент|assistant|консультант|consultant|аудитор|auditor|"
    r"associate|финансист|казначе|риск|андеррайтер|актуари|трейдер|брокер|junior|джуниор|младш|"
    r"помощник|операционист|кредитн\w+ эксперт|программ\w+ (?:стажиров|для студент|для выпускник|развития)|"
    r"graduate|оценщик|контролер|контролёр|экономическ",
    re.I,
)
SALARY_IN_TITLE = re.compile(r"\s*[(\[]?(?:от\s*)?\d[\d\s]*(?:000|к|k|тыс\.?)\s*(?:₽|руб\.?)?[)\]]?\s*$", re.I)


def tidy_title(t: str) -> str:
    t = clean_line(t)
    t = SALARY_IN_TITLE.sub("", t).strip(" ,;:-–—")
    t = re.sub(r"\s*//.*$", "", t)  # "Должность // ЗП ..." -> "Должность"
    return (t[0].upper() + t[1:]) if t else t


def split_title_employer(title: str) -> tuple[str, str | None]:
    """«Стажер отдела финансов / P&G» -> («Стажер отдела финансов», «P&G»)."""
    m = re.match(r"^(.{4,}?)\s+/\s+(.{2,60})$", title)
    if m and not TITLE_ROLE.search(m.group(2)):
        emp = m.group(2).strip(" «»\"")
        emp = re.sub(r"^(?:ГК|АО|ПАО|ООО|ЗАО)\s+", "", emp).strip("«»\" ")
        return m.group(1).strip(), emp
    return title, None


def pick_title(lines: list[str]) -> str:
    cand = [tidy_title(l) for l in lines if tidy_title(l)]
    for l in cand[:8]:
        if len(l) <= 140 and TITLE_ROLE.search(l):
            return l
    return cand[0][:140] if cand else "Вакансия"


def is_event_title(title: str) -> bool:
    low = title.lower()
    return any(re.search(p, low) for p in config.EVENT_TITLE_PATTERNS)


def pick_department(text: str) -> str | None:
    m = DEPT_RE.search(text)
    if not m:
        return None
    val = clean_line(m.group(0))
    return val[:110] if len(val) > 6 else None


def pick_employer(text: str, title: str, default: str | None) -> str | None:
    emp, _ = classify.find_employer(title)
    if emp:
        return emp
    m = EMPLOYER_RE.search(text)
    if m:
        val = clean_line(m.group(1))
        known, _ = classify.find_employer(val)
        return known or val
    emp, _ = classify.find_employer(text[:400])
    if emp:
        return emp
    if default:
        return default
    m = EMPLOYER_LINE_RE.search(text[:300])
    if m:
        return m.group(1).strip("«»\" ")
    m = EMPLOYER_IN_RE.search(text[:400])
    if m:
        return m.group(1).strip("«»\"")
    emp, _ = classify.find_employer(text)
    return emp


def pick_deadline(text: str) -> str | None:
    m = DEADLINE_RE.search(text)
    if m and re.search(r"дедлайн|deadline|заяв|регистрац|отклик", text[max(0, m.start() - 40):m.end()], re.I):
        return m.group(1)
    return None


STRONG_SIGNALS = re.compile(
    r"откликн|отклик|резюме|обязанност|требовани|мы предлагаем|что предлагаем|услови[яй] работы|"
    r"зарплат|з/п|оклад|₽|руб\.|заявк|apply|набор на|присоединяйся|ищем|ищет|приглашаем|"
    r"требуется|открыт\w* (?:набор|ваканси|позици)|подробнее", re.I)


def relevant(text: str, title: str, employer: str | None, *, item: bool = False) -> bool:
    """item=True — элемент подборки (короткий текст, строгая проверка заголовка)."""
    if not TITLE_ROLE.search(title) or len(title) > 110 or len(title.split()) > 14:
        return False
    if is_event_title(title) or title.endswith("!"):
        return False
    if classify.is_excluded_title(title, employer) or classify.is_senior_title(title):
        return False
    if not item and not STRONG_SIGNALS.search(text):
        return False
    junior_scope = title if item else text
    if not classify.is_junior(junior_scope):
        return False
    if not item and classify.requires_experience(text) and not classify.is_junior(title):
        return False
    if item:
        if not (classify.is_finance(text[:300]) or classify.is_finance_vacancy(title, "", employer)):
            return False
    elif not (classify.is_finance(title) or classify.is_finance_vacancy(title, text, employer)
              or classify.is_finance_desc(text[:600], 2)):
        return False
    if not classify.location_ok(text):
        return False
    return True


def build(text: str, *, url: str, source: str, source_type: str, published: str | None,
          default_employer: str | None, lines: list[str] | None = None,
          item: bool = False) -> Vacancy | None:
    lines = lines if lines is not None else text.split("\n")
    title = pick_title(lines)
    title, emp_from_title = split_title_employer(title)
    employer = emp_from_title or pick_employer(text, title, default_employer)
    if emp_from_title:
        known, _ = classify.find_employer(emp_from_title)
        employer = known or emp_from_title
    if not relevant(text, title, employer, item=item):
        return None
    salary, lo, hi = parse_salary(text)
    v = Vacancy(
        id=make_id(source_type, url, title),
        title=title,
        employer=employer,
        url=url,
        source=source,
        source_type=source_type,
        published=published,
        salary=salary,
        salary_from=lo,
        salary_to=hi,
        department=pick_department(text),
        conditions=parse_conditions(text),
        kind=classify.guess_kind(title + "\n" + text[:300]),
        sector=classify.guess_sector(title + "\n" + text[:300], employer),
        description=excerpt(text),
        deadline=pick_deadline(text),
    )
    v.score = classify.score(v)
    return v
