#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фирменные карточки-картинки к постам «Тихих денег».

Каждый пост уходит в канал с картинкой сверху: тёмное поле, знак-монета,
рубрика акцентом, заголовок крупно. Стиль из библии канала (§5) — спокойный,
без блеска и золота: картинка должна обещать то же, что текст.

Рендер SVG→PNG тем, что найдётся: rsvg-convert (в CI ставится apt'ом) →
cairosvg → qlmanage (macOS, для локального предпросмотра) → Chrome.
Только stdlib + системная утилита рендера.
"""
import html
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CARD_W, CARD_H = 1080, 1350
MARGIN = 96

BG_DARK = "#0E1210"
BG_LITE = "#17201B"
ACCENT = "#3FA37A"
TEXT = "#EDF2ED"
MUTED = "#7E8C85"

FONTS = "'Helvetica Neue','DejaVu Sans','Liberation Sans',Helvetica,Arial,sans-serif"

# Рубрика → как подписать её на карточке.
LABELS = {
    "Механика": "МЕХАНИКА",
    "Антимиф": "АНТИМИФ",
    "Расчёт": "РАСЧЁТ",
    "Привычка": "ПРИВЫЧКА",
}


def wrap(text, font_px, max_w=CARD_W - 2 * MARGIN, cw=0.54):
    """Перенос по словам. cw — эмпирическая доля ширины символа от кегля."""
    max_chars = max(6, int(max_w / (font_px * cw)))
    lines, cur = [], ""
    for word in str(text).split():
        trial = (cur + " " + word).strip()
        if len(trial) <= max_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def mark_svg(cx, cy, r):
    """Знак канала — монета с тремя восходящими столбцами (см. brand/)."""
    ring = r * 0.72
    bw = ring * 0.235
    gap = ring * 0.145
    base = cy + ring * 0.46
    heights = (ring * 0.46, ring * 0.75, ring * 1.05)
    x0 = cx - (3 * bw + 2 * gap) / 2
    bars = []
    for i, hgt in enumerate(heights):
        x = x0 + i * (bw + gap)
        color = TEXT if i == 2 else ACCENT
        op = "1" if i == 2 else ("0.9" if i == 1 else "0.62")
        bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" '
                    'fill="%s" opacity="%s"/>' % (x, base - hgt, bw, hgt, bw * 0.42, color, op))
    return ('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="%.1f"/>'
            % (cx, cy, ring, ACCENT, r * 0.115)) + "".join(bars)


def build_svg(label, title, handle="@tihie_dengi"):
    """Карточка: знак + рубрика + заголовок + хендл. Больше ничего — воздух важнее."""
    title_px = 92 if len(str(title)) <= 46 else (78 if len(str(title)) <= 70 else 66)
    lines = wrap(title, title_px)
    while len(lines) > 6 and title_px > 48:          # не выпускаем текст за поля
        title_px -= 8
        lines = wrap(title, title_px)

    block_h = len(lines) * title_px * 1.22
    y0 = (CARD_H - block_h) / 2 + title_px * 0.9

    tspans = "".join(
        '<tspan x="%d" y="%.0f">%s</tspan>' % (MARGIN, y0 + i * title_px * 1.22, html.escape(ln))
        for i, ln in enumerate(lines)
    )

    return """<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{lite}"/>
      <stop offset="1" stop-color="{dark}"/>
    </linearGradient>
    <radialGradient id="halo" cx="0.5" cy="0.42" r="0.62">
      <stop offset="0" stop-color="{acc}" stop-opacity="0.10"/>
      <stop offset="1" stop-color="{acc}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" fill="url(#halo)"/>
  {mark}
  <text x="{m}" y="{label_y}" font-family="{fam}" font-size="34" font-weight="600"
        letter-spacing="7" fill="{acc}">{label}</text>
  <text font-family="{fam}" font-size="{tpx}" font-weight="600" fill="{txt}">{tspans}</text>
  <rect x="{m}" y="{rule_y}" width="120" height="7" rx="3.5" fill="{acc}"/>
  <text x="{m}" y="{handle_y}" font-family="{fam}" font-size="36"
        letter-spacing="2" fill="{muted}">{handle}</text>
</svg>""".format(
        w=CARD_W, h=CARD_H, m=MARGIN, lite=BG_LITE, dark=BG_DARK, acc=ACCENT,
        txt=TEXT, muted=MUTED, fam=FONTS,
        mark=mark_svg(MARGIN + 52, MARGIN + 42, 62),
        label=html.escape(str(label)), label_y=MARGIN + 200,
        tpx=title_px, tspans=tspans,
        rule_y=CARD_H - MARGIN - 132, handle_y=CARD_H - MARGIN - 40,
        handle=html.escape(handle),
    )


def rasterize(svg_text, out_path):
    """SVG → PNG тем, что есть в системе. None, если рендерить нечем."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8")
    tmp.write(svg_text)
    tmp.close()
    try:
        if shutil.which("rsvg-convert"):            # быстрее всего, стоит в CI
            r = subprocess.run(["rsvg-convert", "-w", str(CARD_W), "-h", str(CARD_H),
                                "-o", out_path, tmp.name], capture_output=True)
            if r.returncode == 0 and os.path.exists(out_path):
                return out_path
        try:
            import cairosvg
            cairosvg.svg2png(url=tmp.name, write_to=out_path,
                             output_width=CARD_W, output_height=CARD_H)
            return out_path
        except Exception:
            pass
        if shutil.which("qlmanage"):                # macOS: локальный предпросмотр
            # qlmanage умеет только квадратный вывод и растягивает картинку по
            # большей стороне. Поэтому кладём карточку по центру квадратного
            # холста, а потом вырезаем её обратно через sips — иначе поля
            # обрезаются и предпросмотр врёт про вёрстку.
            square = ('<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
                      'viewBox="0 0 {s} {s}"><rect width="{s}" height="{s}" fill="{bg}"/>'
                      '<g transform="translate({dx},0)">{inner}</g></svg>').format(
                s=CARD_H, bg=BG_DARK, dx=(CARD_H - CARD_W) / 2, inner=svg_text)
            sq = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8")
            sq.write(square)
            sq.close()
            outdir = os.path.dirname(os.path.abspath(out_path)) or "."
            r = subprocess.run(["qlmanage", "-t", "-s", str(CARD_H), "-o", outdir, sq.name],
                               capture_output=True)
            produced = os.path.join(outdir, os.path.basename(sq.name) + ".png")
            os.unlink(sq.name)
            if r.returncode == 0 and os.path.exists(produced):
                os.replace(produced, out_path)
                subprocess.run(["sips", "-c", str(CARD_H), str(CARD_W), out_path],
                               capture_output=True)
                return out_path
        return None
    finally:
        os.unlink(tmp.name)


def make_card(post, out_path=None):
    """Карточка к посту. Возвращает путь к PNG или None, если рендерить нечем."""
    label = LABELS.get(str(post.get("cat", "")), str(post.get("cat", "")).upper())
    out_path = out_path or os.path.join(tempfile.gettempdir(),
                                        "tdg_card_%s.png" % post.get("id", "x"))
    return rasterize(build_svg(label, post.get("title", "")), out_path)


def make_promo_card(name, title, out_path=None):
    """Карточка к воскресной кросс-рекламе."""
    out_path = out_path or os.path.join(tempfile.gettempdir(), "tdg_promo.png")
    return rasterize(build_svg("РЕКОМЕНДУЕМ", title), out_path)


if __name__ == "__main__":
    import json
    posts = json.load(open(os.path.join(HERE, "posts.json"), encoding="utf-8"))
    for p in posts[:3]:
        path = make_card(p, os.path.join(HERE, "preview_%s.png" % p["id"]))
        print(path or "рендерить нечем: поставь rsvg-convert или cairosvg")
