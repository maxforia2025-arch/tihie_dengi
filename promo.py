#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Воскресная реклама соседних каналов Maxforia Group в «Тихих деньгах».

Правило Президента: один канал = одно воскресенье, по кругу. Креатив внутри
канала меняется на следующем круге, чтобы реклама не приедалась.

Перед отправкой список сверяется с реальностью: каждый кандидат проверяется
через getChat, мёртвые и несуществующие пропускаются — иначе реклама уводила бы
подписчиков в пустоту. Счётчик круга двигается только на реально показанном
канале, поэтому пропуск не съедает очередь.

Запуск:
    python3 promo.py                 # dry-run: показать, что ушло бы сегодня
    BOT_TOKEN=... python3 promo.py --send
    python3 promo.py --status        # очередь и на ком стоит счётчик
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import post  # переиспользуем отправку, конфиг и нормализацию токена

HERE = os.path.dirname(os.path.abspath(__file__))
PROMO_PATH = os.path.join(HERE, "promo.json")
PROMO_STATE_PATH = os.path.join(HERE, "promo_state.json")


def load_promo():
    with open(PROMO_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def excluded_handles(cfg_promo):
    return {h.lower() for h in cfg_promo.get("_исключены_навсегда", [])}


def channel_is_live(handle, token):
    """Существует ли канал. Без токена (dry-run) не проверяем — считаем живым."""
    if not token:
        return True
    url = ("https://api.telegram.org/bot" + token + "/getChat?chat_id=" +
           urllib.parse.quote(handle))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": post.UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")).get("ok", False)
    except Exception:
        return False


def candidates(promo, cfg):
    """Каналы сети без площадки и без вечно исключённых."""
    self_handle = str(cfg.get("channel_handle", "")).lower()
    banned = excluded_handles(promo)
    out = []
    for ch in promo.get("channels", []):
        h = str(ch.get("handle", "")).strip()
        if not h or h.lower() == self_handle or h.lower() in banned:
            continue
        if "ПЛЕЙСХОЛДЕР" in h or "🔴" in h:
            continue
        out.append(ch)
    return out


def read_counter():
    data = post.load_json(PROMO_STATE_PATH, {"n": 0})
    try:
        return int(data.get("n", 0))
    except (TypeError, ValueError):
        return 0


def write_counter(n):
    post.save_json(PROMO_STATE_PATH, {"n": n})


def pick(chans, n, token):
    """Канал недели + креатив круга. Мёртвые пропускаем, счётчик не тратим."""
    for step in range(len(chans)):
        ch = chans[(n + step) % len(chans)]
        if not channel_is_live(ch["handle"], token):
            post.log("пропускаю " + ch["handle"] + " — канал недоступен.")
            continue
        variants = ch.get("variants") or []
        if not variants:
            continue
        lap = (n + step) // len(chans)
        return ch, variants[lap % len(variants)], (n + step)
    return None, None, n


def format_promo(ch, v, cfg):
    name = post.html.escape(str(ch.get("name", "")))
    emoji = str(ch.get("emoji", "📣"))
    handle = str(ch.get("handle", ""))
    return (
        emoji + " <b>" + post.html.escape(str(v.get("title", ""))) + "</b>\n\n" +
        post.html.escape(str(v.get("text", ""))) + "\n\n" +
        post.html.escape(str(v.get("pitch", ""))) + "\n\n" +
        "➖➖➖➖➖\n" +
        "👉 <b>" + name + "</b> — " + post.html.escape(str(v.get("cta", "Подписаться"))) +
        ": " + handle + "\n" +
        "<i>Раз в неделю рекомендуем один канал нашей сети. Реклама не продаётся — "
        "это соседи по делу.</i>"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="воскресная кросс-реклама «Тихих денег»")
    ap.add_argument("--send", action="store_true", help="реально отправить")
    ap.add_argument("--status", action="store_true", help="показать очередь и выйти")
    args = ap.parse_args(argv)

    post.load_env()
    cfg = post.load_json(post.CONFIG_PATH, {})
    promo = load_promo()
    chans = candidates(promo, cfg)
    n = read_counter()

    if not chans:
        post.log("в сети нет каналов для рекламы — promo.json пуст или всё исключено.")
        return 0

    if args.status:
        post.log("очередь ротации (счётчик n=" + str(n) + "):")
        for i, ch in enumerate(chans):
            mark = "→" if i == n % len(chans) else " "
            post.log("  " + mark + " " + str(ch.get("handle")) + " — " +
                     str(ch.get("name")) + ", креативов: " + str(len(ch.get("variants", []))))
        return 0

    token = post.normalize_token(os.environ.get("BOT_TOKEN", "").strip(), cfg)
    channel_id = (os.environ.get("CHANNEL_ID", "").strip() or
                  str(cfg.get("channel_handle", "")).strip())

    ch, v, used = pick(chans, n, token if args.send else "")
    if ch is None:
        post.log("ни один канал сети сейчас недоступен — реклама пропущена.")
        return 0

    text = format_promo(ch, v, cfg)

    if not args.send:
        print("\n" + "=" * 56)
        print(text)
        print("=" * 56)
        post.log("DRY-RUN: рекламировали бы " + ch["handle"] +
                 " (круг " + str(used // len(chans) + 1) + ").")
        return 0

    if not token:
        post.log("ОШИБКА: --send требует BOT_TOKEN.")
        return 2
    post.send_telegram(token, channel_id, text)
    write_counter(used + 1)
    post.log("опубликована реклама " + ch["handle"] + "; следующий на очереди — " +
             chans[(used + 1) % len(chans)]["handle"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
