#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪙 НАПОЛНЕНИЕ БАНКА канала «Тихие деньги»: CONTENT_QUEUE.md → posts.json.

Разбирает человекочитаемую очередь эпизодов (launch/CONTENT_QUEUE.md) в машинный
банк постов. Эпизоды, где остались метки 🔴 (не заполнено руками), помечаются
draft:true — постер их не публикует.

Только стандартная библиотека. Сети не касается.

Запуск:
    python3 fill_bank.py                    # разобрать ../launch/CONTENT_QUEUE.md
    python3 fill_bank.py --queue ПУТЬ.md    # другой файл
    python3 fill_bank.py --include-drafts   # занести и незаполненные (как draft)
    python3 fill_bank.py --dry-run          # показать, что получится, и не писать
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(HERE, "posts.json")
DEFAULT_QUEUE = os.path.abspath(os.path.join(HERE, "..", "launch", "CONTENT_QUEUE.md"))
RED = "\U0001F534"

HEAD_RE = re.compile(r"^##\s+EP(\d+)\s*[·•]\s*`([^`]+)`\s*[·•]\s*(.+?)\s*(?:`\[.\]`)?\s*$")


def field(block, label):
    """Достать значение поля **МЕТКА:** — либо на той же строке, либо ниже до пустой."""
    lines = block.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("**" + label + ":**"):
            continue
        inline = line.split("**" + label + ":**", 1)[1].strip()
        if inline:
            return inline
        chunk = []
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                if chunk:
                    break
                continue
            if nxt.startswith("**") or nxt.startswith("---"):
                break
            chunk.append(nxt.strip())
        return " ".join(chunk).strip()
    return ""


def strip_quotes(text):
    return text.strip().strip("«»").strip('"').strip()


def parse_queue(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()

    blocks, current = [], None
    for line in raw.split("\n"):
        m = HEAD_RE.match(line)
        if m:
            if current:
                blocks.append(current)
            current = {"num": int(m.group(1)), "id": m.group(2).strip(),
                       "cat": m.group(3).strip(), "body": []}
        elif current is not None:
            current["body"].append(line)
    if current:
        blocks.append(current)

    out = []
    for b in blocks:
        body = "\n".join(b["body"])
        title = strip_quotes(field(body, "ХУК"))          # ХУК
        text = strip_quotes(field(body, "ЗАКАДР"))  # ЗАКАДР
        cta = strip_quotes(field(body, "CTA"))
        cat = re.sub(r"^[^\w]+", "", b["cat"]).strip()
        item = {
            "id": b["id"],
            "cat": cat or "Тихие деньги",
            "title": title,
            "text": text,
            "wow": "",
            "cta": cta,
            "source": "queue",
        }
        if RED in (title + text + cta) or not text:
            item["draft"] = True
        out.append(item)
    return out


def merge(existing, new, include_drafts):
    by_id = {p.get("id"): p for p in existing}
    added, updated, skipped = 0, 0, 0
    for item in new:
        if item.get("draft") and not include_drafts:
            skipped += 1
            continue
        pid = item["id"]
        if pid in by_id:
            # не трогаем то, что уже опубликовано/отредактировано вручную
            if by_id[pid].get("locked"):
                continue
            by_id[pid].update(item)
            updated += 1
        else:
            existing.append(item)
            by_id[pid] = item
            added += 1
    return added, updated, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description="CONTENT_QUEUE.md → posts.json")
    ap.add_argument("--queue", default=DEFAULT_QUEUE, help="путь к CONTENT_QUEUE.md")
    ap.add_argument("--include-drafts", action="store_true",
                    help="заносить и незаполненные эпизоды (помечены draft)")
    ap.add_argument("--dry-run", action="store_true", help="показать и не писать")
    args = ap.parse_args(argv)

    if not os.path.exists(args.queue):
        print("нет файла: " + args.queue)
        return 1

    parsed = parse_queue(args.queue)
    print("[fill] в очереди эпизодов: " + str(len(parsed)) +
          " | заполнено: " + str(len([p for p in parsed if not p.get("draft")])))

    existing = []
    if os.path.exists(POSTS_PATH):
        with open(POSTS_PATH, encoding="utf-8") as fh:
            existing = json.load(fh)
    if isinstance(existing, dict):
        existing = existing.get("posts", [])

    added, updated, skipped = merge(existing, parsed, args.include_drafts)
    print("[fill] добавлено " + str(added) + ", обновлено " + str(updated) +
          ", пропущено (не заполнено) " + str(skipped) +
          " | в банке станет: " + str(len(existing)))

    if args.dry_run:
        print("[fill] --dry-run: файл не записан.")
        return 0

    with open(POSTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=1)
    print("[fill] записано: " + POSTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
