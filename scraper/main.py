"""Точка входа: собрать вакансии из всех источников, объединить с историей,
записать site/data/vacancies.json и RSS-ленту site/feed.xml.

    python -m scraper.main                  # все источники
    python -m scraper.main --only telegram  # только выбранные
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from . import config, notify
from .common import log, make_session, now_iso
from .sources import changellenge, futru, hh, telegram, trudvsem, vk

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data" / "vacancies.json"
FEED = ROOT / "site" / "feed.xml"
SITE_URL = os.environ.get("SITE_URL", "https://rudnitskiyds-prog.github.io/Jobs/")

SOURCES = {
    "changellenge": changellenge.collect,
    "hh": hh.collect,
    "trudvsem": trudvsem.collect,
    "futru": futru.collect,
    "telegram": telegram.collect,
    "vk": vk.collect,
}
# при дублях оставляем запись из более структурированного источника
SOURCE_RANK = {"hh": 0, "changellenge": 1, "trudvsem": 2, "futru": 3, "vk": 4, "telegram": 5}


def _norm(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", s).strip()


def dedupe(items):
    by_key = {}
    for v in sorted(items, key=lambda v: SOURCE_RANK.get(v.source_type, 9)):
        key = (_norm(v.employer), _norm(v.title)[:60])
        if v.id in {x.id for x in by_key.values()}:
            continue
        if key in by_key and key[0]:
            keep = by_key[key]
            # запоминаем дополнительные источники
            extra = f"Также: {v.source}"
            if v.source != keep.source and extra not in keep.tags:
                keep.tags.append(extra)
            continue
        by_key[key if key[0] else (v.id,)] = v
    return list(by_key.values())


def load_existing() -> dict[str, dict]:
    if DATA.exists():
        try:
            return {v["id"]: v for v in json.loads(DATA.read_text("utf-8")).get("vacancies", [])}
        except (ValueError, KeyError):
            return {}
    return {}


def merge(fresh, existing: dict[str, dict], run_ts: str, ran_sources: set[str]):
    now = datetime.fromisoformat(run_ts)
    out: dict[str, dict] = {}
    new_ids = []
    for v in fresh:
        d = v.to_dict()
        old = existing.get(v.id)
        d["first_seen"] = old.get("first_seen") if old else run_ts
        d["last_seen"] = run_ts
        if not old:
            new_ids.append(v.id)
        out[v.id] = d
    keep_after = now - timedelta(days=config.KEEP_DAYS)
    for vid, d in existing.items():
        if vid in out:
            continue
        try:
            last = datetime.fromisoformat(d.get("last_seen") or d.get("first_seen"))
        except (TypeError, ValueError):
            continue
        # каталоги (не ленты постов) — если источник отработал и вакансии нет, значит её сняли
        if d.get("source_type") in ("changellenge", "futru", "hh", "trudvsem") and d["source_type"] in ran_sources:
            continue
        if last >= keep_after:
            out[vid] = d
    return list(out.values()), new_ids


def sort_key(d: dict):
    date = d.get("published") or d.get("first_seen") or ""
    return (date[:10], d.get("score", 0), date)


def write_feed(items: list[dict]):
    rows = sorted(items, key=lambda d: d.get("first_seen") or "", reverse=True)[:150]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        "<title>Стажировки и junior-вакансии в финансах · Москва</title>",
        f"<link>{escape(SITE_URL)}</link>",
        "<description>Ежедневная подборка стажировок и вакансий без опыта в банках, инвестициях и финансах</description>",
        "<language>ru</language>",
    ]
    for d in rows:
        title = f"{d['title']} — {d.get('employer') or 'работодатель не указан'}"
        desc = " · ".join(filter(None, [d.get("salary"), ", ".join(d.get("conditions") or []),
                                        d.get("department"), d.get("source")]))
        try:
            pub = datetime.fromisoformat(d["first_seen"]).strftime("%a, %d %b %Y %H:%M:%S +0000")
        except (KeyError, TypeError, ValueError):
            pub = ""
        parts.append(
            f"<item><title>{escape(title)}</title><link>{escape(d['url'])}</link>"
            f"<guid isPermaLink=\"false\">{d['id']}</guid><pubDate>{pub}</pubDate>"
            f"<category>{escape(d.get('sector') or '')}</category>"
            f"<description>{escape(desc)}</description></item>"
        )
    parts.append("</channel></rss>")
    FEED.write_text("\n".join(parts), "utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=list(SOURCES), help="запустить только эти источники")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    session = make_session()
    run_ts = now_iso()
    fresh, stats, ran = [], {}, set()
    for name, fn in SOURCES.items():
        if args.only and name not in args.only:
            continue
        try:
            found = fn(session)
            stats[name] = len(found)
            if found:  # источник считаем отработавшим, только если он что-то вернул
                ran.add(name)
            fresh.extend(found)
        except Exception as e:  # один упавший источник не должен ломать остальные
            log.exception("источник %s упал: %s", name, e)
            stats[name] = f"ошибка: {e.__class__.__name__}"

    fresh = dedupe(fresh)
    existing = load_existing()
    items, new_ids = merge(fresh, existing, run_ts, ran)
    items.sort(key=sort_key, reverse=True)

    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps({
        "updated_at": run_ts,
        "stats": stats,
        "total": len(items),
        "new_in_last_run": len(new_ids),
        "vacancies": items,
    }, ensure_ascii=False, indent=1), "utf-8")
    write_feed(items)
    log.info("готово: всего %d, новых %d, по источникам %s", len(items), len(new_ids), stats)

    if not args.no_notify:
        notify.send_new([d for d in items if d["id"] in set(new_ids)], SITE_URL)


if __name__ == "__main__":
    main()
