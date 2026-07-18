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
import urllib.error
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

def normalize_token(token, cfg):
    """Достраивает токен, если скопирована только его вторая половина.

    Токен = «<id бота>:<секрет>». При выделении мышью в Telegram начало до
    двоеточия часто теряется — Telegram на такую строку отвечает 404, и человек
    копирует заново с тем же результатом. id бота публичный и лежит в config.json,
    поэтому недостающую часть подставляем сами: секрет от этого не страдает,
    а грабли исчезают. Лишние обёртки («bot», пробелы, кусок URL) тоже срезаем.
    """
    if not token:
        return token
    for junk in ("https://api.telegram.org/bot", "http://api.telegram.org/bot"):
        if token.startswith(junk):
            token = token[len(junk):]
    token = token.strip().strip('"').strip("'").rstrip("/")
    if token.startswith("bot") and ":" in token[3:]:
        token = token[3:]
    bot_id = str(cfg.get("bot_id", "") or "")
    if ":" not in token and bot_id and len(token) >= 30:
        log("BOT_TOKEN без префикса — подставляю id бота " + bot_id + " из config.json.")
        token = bot_id + ":" + token
    return token


def diagnose_token(token, cfg):
    """Проверяет ФОРМУ токена до обращения к сети и печатает разбор.

    Секрет не раскрывается: в лог идут только длина, числовой префикс (id бота —
    он публичный, есть в config.json) и факт совпадения с ожидаемым ботом.
    Нужно потому, что Telegram на любую кривую строку отвечает одинаковым 404,
    а причины разные: чужой бот, лишние символы, обрезанная копипаста.
    """
    if not token:
        return
    expected = str(cfg.get("bot_id", "") or "")
    head, sep, tail = token.partition(":")
    # В лог не попадает НИ ОДНОГО символа секретной части: только длины и
    # числовой id бота (он публичный). Логи Actions в открытом репозитории
    # читает кто угодно, а маскировка GitHub ловит лишь точное совпадение
    # со всем секретом — подстроку она не скроет.
    log("проверка BOT_TOKEN: длина " + str(len(token)) +
        ", id бота " + (head if head.isdigit() else "<не число>") +
        ", хвост " + str(len(tail)) + " симв.")
    if not sep:
        log("  ✗ в токене нет двоеточия. Похоже, скопирована не та строка — "
            "нужен вид 123456789:AA... целиком.")
    elif not head.isdigit():
        log("  ✗ до двоеточия должен быть только номер бота. Убери лишнее "
            "(«bot», кавычки, часть URL, пробелы).")
    elif expected and head != expected:
        log("  ✗ это токен ДРУГОГО бота: id " + head + ", а канал ждёт " + expected +
            " (@" + str(cfg.get("bot_username", "")).lstrip("@") + "). "
            "В @BotFather → /mybots выбери именно его.")
    elif len(tail) < 30:
        log("  ✗ хвост токена короче обычного — копипаста, похоже, обрезана.")
    else:
        log("  ✓ форма токена правильная и id совпадает с ботом канала.")


def check_token(token):
    """getMe: проверяет токен, ничего не публикуя.

    Нужен после смены токена — иначе единственный способ убедиться, что он живой,
    это выпустить в канал лишний пост.
    """
    if not token:
        log("ОШИБКА: BOT_TOKEN не задан.")
        return 2
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + token + "/getMe",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log("ОШИБКА " + str(e.code) + ": токен не принят Telegram. Возьми свежий "
            "в @BotFather → /mybots → бот → API Token и обнови секрет BOT_TOKEN.")
        return 1
    me = data.get("result", {})
    log("✓ токен рабочий: бот @" + str(me.get("username", "?")) +
        " (id " + str(me.get("id", "?")) + "). Публикация не выполнялась.")
    return 0


CAPTION_LIMIT = 1024      # жёсткий лимит Telegram на подпись к фото


def _api_call(token, method, payload, content_type=None):
    """Вызов Bot API с человекочитаемым разбором ошибок вместо трейсбека."""
    url = "https://api.telegram.org/bot" + token + "/" + method
    headers = {"User-Agent": UA}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Telegram отвечает осмысленными кодами — переводим их в понятную причину,
        # чтобы в логе Actions была строка «что чинить», а не сырой трейсбек.
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        why = {
            404: "токен BOT_TOKEN недействителен (бот по нему не найден). "
                 "Возьми свежий в @BotFather → /mybots → бот → API Token и обнови секрет.",
            401: "токен BOT_TOKEN отозван или неверен. Обнови секрет свежим токеном из @BotFather.",
            400: "Telegram отклонил запрос — обычно неверный CHANNEL_ID/хендл канала.",
            403: "бот не имеет права публиковать: добавь его админом канала с правом "
                 "«Публиковать сообщения».",
        }.get(e.code, "неожиданный ответ Telegram.")
        raise SystemExit("[tihie_dengi] ОШИБКА " + str(e.code) + ": " + why +
                         ("\n[tihie_dengi] ответ API: " + body if body else ""))
    if not data.get("ok"):
        raise SystemExit("[tihie_dengi] ОШИБКА: Telegram вернул ok=false — " + str(data))
    return data


def send_telegram(token, channel_id, text):
    return _api_call(token, "sendMessage", urllib.parse.urlencode({
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8"))


def _multipart(fields, file_field, file_path):
    """multipart/form-data вручную: заливка файла без внешних библиотек."""
    boundary = "----tdg" + str(int(time.time() * 1000))
    out = b""
    for key, val in fields.items():
        out += ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key +
                "\"\r\n\r\n" + str(val) + "\r\n").encode("utf-8")
    with open(file_path, "rb") as fh:
        blob = fh.read()
    out += ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + file_field +
            "\"; filename=\"card.png\"\r\nContent-Type: image/png\r\n\r\n").encode("utf-8")
    out += blob + ("\r\n--" + boundary + "--\r\n").encode("utf-8")
    return out, "multipart/form-data; boundary=" + boundary


def send_photo(token, channel_id, photo_path, caption):
    """Фото с подписью. Длинный текст Telegram в подпись не пустит (лимит 1024),
    поэтому такой пост уходит двумя сообщениями: картинка и следом текст."""
    if len(caption) <= CAPTION_LIMIT:
        body, ctype = _multipart({"chat_id": channel_id, "caption": caption,
                                  "parse_mode": "HTML"}, "photo", photo_path)
        return _api_call(token, "sendPhoto", body, ctype)
    log("подпись длиннее " + str(CAPTION_LIMIT) + " символов — шлю фото и текст отдельно.")
    body, ctype = _multipart({"chat_id": channel_id}, "photo", photo_path)
    _api_call(token, "sendPhoto", body, ctype)
    return send_telegram(token, channel_id, caption)


# ── проход ───────────────────────────────────────────────────────────────────

def run_once(posts, state, cfg, mode, token, channel_id):
    post = choose(posts, state)
    if post is None:
        log("банк пуст: нет ни одного готового поста. Заполни CONTENT_QUEUE.md "
            "и прогони fill_bank.py, либо запусти generate_posts.py --send.")
        return False

    text = format_post(post, cfg)

    if mode == "send":
        # Каждый пост идёт с карточкой сверху. Если рендерить нечем (нет
        # rsvg-convert/cairosvg), пост всё равно уходит — текстом, а не молчанием.
        card = None
        try:
            import cards
            card = cards.make_card(post)
        except Exception as e:
            log("карточку собрать не удалось (" + str(e) + ") — публикую текстом.")
        if card:
            send_photo(token, channel_id, card, text)
            try:
                os.unlink(card)
            except OSError:
                pass
        else:
            log("рендер картинок недоступен — публикую текстом.")
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
    ap.add_argument("--check", action="store_true",
                    help="проверить BOT_TOKEN через getMe и выйти (ничего не публикует)")
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

    token = normalize_token(os.environ.get("BOT_TOKEN", "").strip(), cfg)
    if args.send or args.check:
        diagnose_token(token, cfg)
    if args.check:
        return check_token(token)
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
