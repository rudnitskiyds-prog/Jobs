"""Публичные Telegram-каналы через веб-превью t.me/s/<channel> (без авторизации)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from .. import config, extract
from ..common import fetch, html_to_text, log

DIGEST_HINT = re.compile(r"подборк|дайджест|ваканси[ий] недели|стажировк[иа] недели|свежие ваканси|"
                         r"вакансии и стажировки|актуальные ваканси|открытые позиции", re.I)
SPLIT_BR = re.compile(r"(?:<br\s*/?>\s*){2,}", re.I)


def _links(fragment: str) -> list[str]:
    out = []
    for href in re.findall(r'href="([^"]+)"', fragment):
        href = href.replace("&amp;", "&")
        if href.startswith("http") and "t.me/" not in href and "?q=%23" not in href:
            out.append(href)
    return out


def _split_digest(msg_html: str) -> list[tuple[str, str | None]]:
    """Разбивает пост-подборку на элементы (текст, ссылка)."""
    items = []
    for block in SPLIT_BR.split(msg_html):
        lines_html = re.split(r"<br\s*/?>", block, flags=re.I)
        linked = [l for l in lines_html if _links(l) and extract.ROLE_WORDS.search(html_to_text(l))]
        if len(linked) >= 2:  # каждая строка блока — отдельная вакансия со ссылкой
            for l in linked:
                items.append((html_to_text(l), _links(l)[0]))
            continue
        text = html_to_text(block)
        n_lines = len([x for x in text.split("\n") if x.strip()])
        if 1 <= n_lines <= 6 and extract.ROLE_WORDS.search(text):
            links = _links(block)
            items.append((text, links[0] if links else None))
    return items


def _parse_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        post = msg["data-post"]
        text_div = msg.select_one("div.tgme_widget_message_text")
        t = msg.select_one("a.tgme_widget_message_date time")
        if not text_div:
            continue
        yield post, text_div.decode_contents(), (t["datetime"] if t else None)


def collect(session, channels: dict | None = None):
    channels = channels or config.TELEGRAM_CHANNELS
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MAX_POST_AGE_DAYS)
    out = []
    for channel, default_emp in channels.items():
        before = None
        posts = []
        for _ in range(config.TELEGRAM_PAGES_PER_CHANNEL):
            url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
            r = fetch(session, url)
            if not r:
                break
            page = list(_parse_page(r.text))
            if not page:
                break
            posts.extend(page)
            ids = [int(p.split("/")[-1]) for p, _, _ in page if p.split("/")[-1].isdigit()]
            if not ids:
                break
            before = min(ids)
        title = channel
        n = 0
        for post, msg_html, dt in posts:
            if dt:
                try:
                    if datetime.fromisoformat(dt) < cutoff:
                        continue
                except ValueError:
                    pass
            text = html_to_text(msg_html)
            post_url = f"https://t.me/{post}"
            src = f"Telegram · @{channel}"
            items = _split_digest(msg_html)
            if len(items) >= 3 or (len(items) >= 2 and DIGEST_HINT.search(text)):
                header = text.split("\n", 1)[0][:200]
                for item_text, link in items:
                    if item_text.split("\n", 1)[0] == header:
                        continue
                    ctx = item_text + "\n" + header
                    v = extract.build(ctx, url=link or post_url, source=src, source_type="telegram",
                                      published=dt, default_employer=default_emp,
                                      lines=item_text.split("\n"), item=True)
                    if v:
                        v.id = extract.make_id("telegram", post_url, v.title)
                        v.description = item_text + f"\n\nИз подборки: {post_url}"
                        out.append(v)
                        n += 1
                continue
            v = extract.build(text, url=post_url, source=src, source_type="telegram",
                              published=dt, default_employer=default_emp)
            if v:
                links = _links(msg_html)
                if links:
                    v.apply_url = links[0]
                out.append(v)
                n += 1
        log.info("telegram @%s: постов %d, подходящих %d", title, len(posts), n)
    return out
