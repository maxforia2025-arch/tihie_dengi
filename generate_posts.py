#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪙 АВТОПОПОЛНЕНИЕ БАНКА канала «Тихие деньги» через Claude API.

Когда непоказанных постов остаётся меньше порога — просит у модели новую партию
в формате банка и дописывает в posts.json (без дублей по id и заголовку).

Только стандартная библиотека: HTTP через urllib, никаких пакетов ставить не нужно.
По умолчанию DRY-RUN: печатает промпт и выходит. Сеть — только с флагом --send.

Запуск:
    python3 generate_posts.py                      # dry-run: показать промпт
    python3 generate_posts.py --send               # сгенерировать и дописать
    python3 generate_posts.py --send --ensure 20   # только если непоказанных < порога
    python3 generate_posts.py --send --count 20    # ровно 20 новых

Ключ — только из окружения: ANTHROPIC_API_KEY (в облаке — GitHub Secret).
"""

import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(HERE, "posts.json")
STATE_PATH = os.path.join(HERE, "state.json")
CONFIG_PATH = os.path.join(HERE, "config.json")
ENV_PATH = os.path.join(HERE, ".env")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-8"

SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "cat": {"type": "string"},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "wow": {"type": "string"},
                },
                "required": ["id", "cat", "title", "text", "wow"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}


def load_env():
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return (s or "post")[:40]


def norm(title):
    return re.sub(r"\s+", " ", str(title).lower()).strip()


def build_prompt(cfg, existing, n):
    titles = "\n".join("- " + str(p.get("title", "")) for p in existing[-120:])
    pillars = cfg.get("pillars_hint", "Механика, Антимиф, Расчёт, Привычка")
    return (
        "Ты — редактор Telegram-канала «Тихие деньги».\n"
        "Ниша канала: Скучные механики денег, которые работают без риска и без инфо-цыганства\n"
        "Тон: спокойный, взрослый, антихайповый\n"
        "Рубрики (чередуй их): " + str(pillars) + "\n\n"
        "Сгенерируй " + str(n) + " НОВЫХ постов на русском языке. Требования:\n"
        "1. Каждый пост — ПРАВДА и проверяемый факт/мысль. Никаких выдумок и мифов.\n"
        "2. Пост должен цеплять за 5 секунд и вызывать желание переслать другу.\n"
        "3. Строго в нише канала, не уходи в общие темы.\n"
        "4. НЕ повторяй уже существующие темы (в том числе по смыслу):\n" + titles + "\n\n"
        "Формат каждого поста:\n"
        "- id: короткий уникальный слаг латиницей в нижнем регистре с подчёркиваниями\n"
        "- cat: одна рубрика из списка выше\n"
        "- title: заголовок-крючок 4–9 слов, обрывающий мысль\n"
        "- text: суть в 2–4 предложениях, простым языком, на «ты»\n"
        "- wow: короткая добивка одним предложением\n\n"
        "Без markdown и без эмодзи внутри полей."
    )


def call_claude(prompt, key, n):
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 8000,
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("stop_reason") == "refusal":
        print("[gen] модель отказалась отвечать — ничего не добавлено.")
        return []
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text = block.get("text", "")
            break
    if not text:
        return []
    return json.loads(text).get("posts", [])


def merge(existing, new):
    seen_ids = set(p.get("id") for p in existing)
    seen_titles = set(norm(p.get("title", "")) for p in existing)
    added = []
    for item in new:
        if not all(str(item.get(k, "")).strip() for k in ("cat", "title", "text")):
            continue
        if norm(item.get("title")) in seen_titles:
            continue
        pid = slugify(item.get("id") or item.get("title"))
        base, i = pid, 2
        while pid in seen_ids:
            pid = base + "_" + str(i)
            i += 1
        seen_ids.add(pid)
        seen_titles.add(norm(item.get("title")))
        added.append({
            "id": pid,
            "cat": str(item.get("cat", "")).strip(),
            "title": str(item.get("title", "")).strip(),
            "text": str(item.get("text", "")).strip(),
            "wow": str(item.get("wow", "")).strip(),
            "cta": "",
            "source": "claude",
        })
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description="Автопополнение банка «Тихие деньги»")
    ap.add_argument("--send", action="store_true",
                    help="реально обратиться к Claude API (по умолчанию dry-run)")
    ap.add_argument("--count", type=int, default=None, help="сколько постов запросить")
    ap.add_argument("--ensure", type=int, default=None,
                    help="генерировать, только если непоказанных меньше порога")
    args = ap.parse_args(argv)

    load_env()
    cfg = load_json(CONFIG_PATH, {})
    posts = load_json(POSTS_PATH, [])
    if isinstance(posts, dict):
        posts = posts.get("posts", [])
    state = load_json(STATE_PATH, {})
    posted = set(state.get("posted", []) if isinstance(state, dict) else state)

    live = [p for p in posts if not p.get("draft")]
    unseen = len([p for p in live if p.get("id") not in posted])
    print("[gen] в банке " + str(len(posts)) + " (готовых " + str(len(live)) +
          "), непоказанных " + str(unseen))

    if args.ensure is not None and unseen >= args.ensure:
        print("[gen] непоказанных (" + str(unseen) + ") >= порога (" +
              str(args.ensure) + ") — пополнение не нужно.")
        return 0

    n = args.count or int(os.environ.get("GEN_N", "15"))
    prompt = build_prompt(cfg, posts, n)

    if not args.send:
        print("[gen] DRY-RUN (сеть не тронута). Промпт, который был бы отправлен "
              "в " + MODEL + ":\n")
        print("-" * 56)
        print(prompt)
        print("-" * 56)
        print("[gen] для реального пополнения: python3 generate_posts.py --send")
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("[gen] НЕТ ANTHROPIC_API_KEY — пропускаю генерацию (не ошибка).")
        return 0

    print("[gen] запрашиваю " + str(n) + " постов у " + MODEL + "...")
    try:
        new = call_claude(prompt, key, n)
    except Exception as exc:
        print("[gen] ошибка запроса: " + str(exc))
        return 1

    added = merge(posts, new)
    if not added:
        print("[gen] новых постов нет (пусто или всё дубли).")
        return 0

    posts.extend(added)
    with open(POSTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(posts, fh, ensure_ascii=False, indent=1)
    print("[gen] добавлено " + str(len(added)) + ". Всего в банке: " + str(len(posts)))
    for a in added:
        print("   + [" + a["cat"] + "] " + a["title"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
