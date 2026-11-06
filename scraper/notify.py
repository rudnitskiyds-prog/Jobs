"""Уведомления о новых вакансиях в Telegram через бота (необязательно).

Нужны переменные окружения TELEGRAM_BOT_TOKEN (от @BotFather) и
TELEGRAM_CHAT_ID (ваш id — его покажет, например, @userinfobot).
"""
from __future__ import annotations

import html
import os

import requests

from .common import log

PRIORITY = ("Банки", "Инвестиции и рынки капитала")
LIMIT = 4000


def _line(d: dict) -> str:
    emp = html.escape(d.get("employer") or "работодатель не указан")
    title = html.escape(d["title"])
    sal = html.escape(d.get("salary") or "з/п не указана")
    star = "⭐ " if d.get("sector") in PRIORITY else ""
    return f'{star}<a href="{html.escape(d["url"])}">{title}</a>\n🏢 {emp} · 💰 {sal}'


def send_new(items: list[dict], site_url: str):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat or not items:
        return
    items = sorted(items, key=lambda d: (d.get("sector") not in PRIORITY, -(d.get("score") or 0)))
    header = f"🆕 Новых вакансий и стажировок: <b>{len(items)}</b>\n\n"
    chunks, cur = [], header
    for d in items:
        line = _line(d) + "\n\n"
        if len(cur) + len(line) > LIMIT:
            chunks.append(cur)
            cur = ""
        cur += line
    cur += f'Все вакансии: <a href="{html.escape(site_url)}">сайт агрегатора</a>'
    chunks.append(cur)
    for text in chunks[:5]:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, json={
                "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
            if r.status_code != 200:
                log.warning("telegram notify: HTTP %s %s", r.status_code, r.text[:200])
        except requests.RequestException as e:
            log.warning("telegram notify: %s", e)
