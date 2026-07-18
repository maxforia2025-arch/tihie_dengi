#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪙 ПОСТЕР канала «Тихие деньги» — берёт следующий пост из банка и шлёт в Telegram.

Только стандартная библиотека Python. Работает в GitHub Actions при выключенном Mac.

Идемпотентность: каждый опубликованный id пишется в state.json СРАЗУ после отправки.
Повторный запуск возьмёт следующий пост, а не тот же самый.

Запуск:
    python3 post.py                 # DRY-RUN (по умолчанию): показать пост, ничего не слать
    python3 post.py --send          # реальная отправка (нужны BOT_TOKEN и CHANNEL_ID)
    python3 post.py --simulate      # без сети, но отметить пост отправленным (тест анти-дубля)
    python3 post.py --count 3       # сколько постов за запуск
    python3 post.py --status        # что в банке: всего / готово / не показано

Секреты — ТОЛЬКО через переменные окружения (или файл .env рядом со скриптом,
который лежит в .gitignore). В коде секретов нет и быть не должно.
    BOT_TOKEN=123:ABC   CHANNEL_ID=@tihie_dengi_daily   [FUNNEL_BOT_USERNAME=...]
"""

import argparse
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(HERE, "posts.json")
STATE_PATH = os.path.join(HERE, "state.json")
CONFIG_PATH = os.path.join(HERE, "config.json")
ENV_PATH = os.path.join(HERE, ".env")
UA = "Mozilla/5.0 (tihie_dengi-bot)"

# Детерминированный псевдослучай без random — ротация формулировок по времени.
_seed = int(time.time())


def _rand(n):
    global _seed
    _seed = (_seed * 1103515245 + 12345) & 0x7FFFFFFF
    return _seed % n if n else 0


def _pick(seq):
    return seq[_rand(len(seq))] if seq else ""


def log(msg):
    print("[tihie_dengi] " + str(msg), flush=True)


# ── файлы ────────────────────────────────────────────────────────────────────

def load_env():
    """Локально подхватить .env. В облаке секреты приходят из GitHub Secrets."""
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
    except Exception as exc:
        log("не прочитан " + os.path.basename(path) + " (" + str(exc) + "), беру дефолт")
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_state():
    st = load_json(STATE_PATH, {})
    if isinstance(st, list):          # совместимость со старым форматом
        st = {"posted": st}
    if not isinstance(st, dict):
        st = {}
    st.setdefault("posted", [])
    return st


# ── выбор поста ──────────────────────────────────────────────────────────────

def ready_posts(posts):
    """Готовые к публикации: без флага draft и без незаполненных мест (🔴)."""
    out = []
    for p in posts:
        if p.get("draft"):
            continue
        blob = " ".join(str(p.get(k, "")) for k in ("title", "text", "wow", "cta"))
        if "\U0001F534" in blob:      # 🔴 — маркер «заполнить руками»
            continue
        out.append(p)
    return out


def choose(posts, state):
    """Следующий пост: сначала непоказанные, потом самый давний. Без повторов."""
    pool = ready_posts(posts)
    if not pool:
        return None
    posted = state.get("posted", [])
    seen = set(posted)
    unseen = [p for p in pool if p.get("id") not in seen]
    if unseen:
        return _pick(unseen)
    order = {pid: i for i, pid in enumerate(posted)}   # больше индекс = свежее
    return sorted(pool, key=lambda p: order.get(p.get("id"), -1))[0]


# ── сборка текста ────────────────────────────────────────────────────────────

HOOK_EMOJI = ["🪙", "▸", "✦", "•"]
WOW_LEAD = ["\U0001F449", "→", "▸"]


def format_post(post, cfg):
    title = html.escape(str(post.get("title", "")).strip())
    body = html.escape(str(post.get("text", "")).strip())
    wow = html.escape(str(post.get("wow", "")).strip())

    parts = []
    if title:
        parts.append(_pick(HOOK_EMOJI) + " <b>" + title + "</b>")
        parts.append("")
    parts.append(body)
    if wow:
        parts.append("")
        parts.append(_pick(WOW_LEAD) + " <b>" + wow + "</b>")

    name = html.escape(str(cfg.get("channel_name", "Тихие деньги")))
    handle = html.escape(str(cfg.get("channel_handle", "@tihie_dengi_daily")))
    cta = _pick(cfg.get("cta_variants") or []).replace("{name}", name)
    share = _pick(cfg.get("share_variants") or [])

    parts.append("")
    parts.append("➖➖➖➖➖")
    if cta:
        parts.append(cta + " " + handle)
    if share:
        parts.append(share)

    # Фаза роста (Президент, 2026-07-18): набираем аудиторию, не продаём.
    # growth_mode=true → зовём только в бесплатный лид-магнит, платный оффер молчит.
    # Включить продажи = "growth_mode": false в config.json. Партнёрских ссылок нет вообще.
    growth = bool(cfg.get("growth_mode", True))
    funnel = os.environ.get("FUNNEL_BOT_USERNAME", "").strip().lstrip("@")
    own_cta = str(post.get("cta", "")).strip()
    lead_cta = str(cfg.get("lead_magnet_cta", "Забрать бесплатно")).strip()
    if funnel:
        link = "https://t.me/" + funnel + "?start=" + str(cfg.get("src", "tdg")) + "_tg"
        label = lead_cta if growth else (own_cta or lead_cta)
        parts.append("\U0001F381 <a href=\"" + link + "\">" + html.escape(str(label)) + "</a>")
    elif own_cta and not growth:
        parts.append(html.escape(own_cta))

    return "\n".join(parts)


# ── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(token, channel_id, text):
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(data)
    return data


# ── проход ───────────────────────────────────────────────────────────────────

def run_once(posts, state, cfg, mode, token, channel_id):
    post = choose(posts, state)
    if post is None:
        log("банк пуст: нет ни одного готового поста. Заполни CONTENT_QUEUE.md "
            "и прогони fill_bank.py, либо запусти generate_posts.py --send.")
        return False

    text = format_post(post, cfg)

    if mode == "send":
        send_telegram(token, channel_id, text)
        log("опубликовано: " + str(post.get("id")) + " [" + str(post.get("cat", "-")) + "]")
    else:
        print("\n" + "=" * 56)
        print(text)
        print("=" * 56)
        log(("СИМУЛЯЦИЯ (без сети, состояние записано): " if mode == "simulate"
             else "DRY-RUN (ничего не отправлено): ") + str(post.get("id")))

    if mode in ("send", "simulate"):
        state.setdefault("posted", []).append(post.get("id"))
        state["posted"] = state["posted"][-2000:]
        state["last_post_id"] = post.get("id")
        state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_json(STATE_PATH, state)      # пишем СРАЗУ — анти-дубль при падении
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Постер канала «Тихие деньги»")
    ap.add_argument("--send", action="store_true",
                    help="реально отправить в Telegram (по умолчанию — dry-run)")
    ap.add_argument("--simulate", action="store_true",
                    help="без сети, но записать состояние (проверка анти-дубля)")
    ap.add_argument("--count", type=int, default=None, help="сколько постов за запуск")
    ap.add_argument("--status", action="store_true", help="показать состояние банка и выйти")
    args = ap.parse_args(argv)

    load_env()
    cfg = load_json(CONFIG_PATH, {})
    posts = load_json(POSTS_PATH, [])
    if isinstance(posts, dict):
        posts = posts.get("posts", [])
    state = load_state()

    pool = ready_posts(posts)
    unseen = len([p for p in pool if p.get("id") not in set(state.get("posted", []))])
    log("банк: всего " + str(len(posts)) + " | готово " + str(len(pool)) +
        " | не показано " + str(unseen) + " | опубликовано ранее " +
        str(len(state.get("posted", []))))

    if args.status:
        for p in posts[:200]:
            flag = "draft" if p.get("draft") else ("sent " if p.get("id") in set(state.get("posted", [])) else "  -  ")
            print("  [" + flag + "] " + str(p.get("id")) + " — " + str(p.get("title", ""))[:60])
        return 0

    token = os.environ.get("BOT_TOKEN", "").strip()
    # CHANNEL_ID — не секрет: хендл публичный. Env перебивает, но по умолчанию
    # берём из config.json, чтобы для запуска хватало одного секрета BOT_TOKEN.
    channel_id = os.environ.get("CHANNEL_ID", "").strip() or str(cfg.get("channel_handle", "")).strip()

    mode = "dry"
    if args.simulate:
        mode = "simulate"
    elif args.send:
        if not token or not channel_id:
            log("ОШИБКА: --send требует BOT_TOKEN и CHANNEL_ID в окружении. Ничего не отправлено.")
            return 2
        mode = "send"

    count = args.count or int(os.environ.get("N", "1") or "1")
    for i in range(max(1, count)):
        if not run_once(posts, state, cfg, mode, token, channel_id):
            return 1
        if mode == "send" and i < count - 1:
            time.sleep(3)
    log("готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
