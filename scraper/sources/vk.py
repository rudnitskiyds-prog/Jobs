"""Паблики ВКонтакте через API wall.get (нужен VK_TOKEN — сервисный ключ приложения).

Как получить: https://dev.vk.com → «Мои приложения» → создать приложение →
«Настройки» → «Сервисный ключ доступа».
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

from .. import config, extract
from ..common import fetch, log

API = "https://api.vk.com/method/wall.get"
VK_LINK = re.compile(r"\[(https?://[^|\]]+|[a-z0-9_]+)\|([^\]]+)\]", re.I)


def _clean(text: str) -> str:
    # VK-разметка [club123|Название] -> Название
    return VK_LINK.sub(lambda m: m.group(2), text)


def collect(session, groups: dict | None = None):
    token = os.environ.get("VK_TOKEN")
    if not token:
        log.info("vk: VK_TOKEN не задан — источник пропущен")
        return []
    groups = groups or config.VK_GROUPS
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MAX_POST_AGE_DAYS)
    out = []
    for domain, default_emp in groups.items():
        r = fetch(session, API, params={"domain": domain, "count": config.VK_POSTS_PER_GROUP,
                                        "access_token": token, "v": "5.199"})
        if not r:
            continue
        data = r.json()
        if "error" in data:
            log.warning("vk %s: %s", domain, data["error"].get("error_msg"))
            continue
        n = 0
        for post in data.get("response", {}).get("items", []):
            dt = datetime.fromtimestamp(post.get("date", 0), timezone.utc)
            if dt < cutoff:
                continue
            text = _clean(post.get("text") or "")
            for att in post.get("copy_history") or []:
                text += "\n" + _clean(att.get("text") or "")
            if not text.strip():
                continue
            url = f"https://vk.com/wall{post['owner_id']}_{post['id']}"
            v = extract.build(text, url=url, source=f"VK · {domain}", source_type="vk",
                              published=dt.isoformat(), default_employer=default_emp)
            if v:
                links = [a["link"]["url"] for a in post.get("attachments", []) if a.get("type") == "link"]
                links += re.findall(r"https?://\S+", text)
                if links:
                    v.apply_url = links[0].rstrip(").,")
                out.append(v)
                n += 1
        log.info("vk %s: подходящих %d", domain, n)
        time.sleep(0.4)
    return out
