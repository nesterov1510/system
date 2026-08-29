#!/usr/bin/env python3
"""Генератор PNG-иконок MSB для PWA (чистый Python, без зависимостей).

Создаёт:
  icon-192.png, icon-512.png            — обычные иконки (any)
  icon-maskable-192.png, icon-maskable-512.png — с безопасной зоной (maskable)
  apple-touch-icon.png (180x180)        — для iOS home screen
"""
import math
import struct
import zlib
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public")
OUT = os.path.abspath(OUT)

# ---------- цветовая палитра ----------
INDIGO_600 = (79, 70, 229)      # #4f46e5
INDIGO_900 = (49, 46, 129)      # #312e81
WHITE = (255, 255, 255, 255)
WHITE_SOFT = (199, 210, 254)    # #c7d2fe
TRANSPARENT = (0, 0, 0, 0)


# ---------- геометрия (расстояния) ----------
def seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    t = max(0.0, min(1.0, (vx * wx + vy * wy) / (vx * vx + vy * vy)))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return math.hypot(dx, dy)


def rounded_rect_dist(px, py, cx, cy, w, h, r):
    dx = abs(px - cx) - (w / 2 - r)
    dy = abs(py - cy) - (h / 2 - r)
    ox, oy = max(dx, 0.0), max(dy, 0.0)
    return math.hypot(ox, oy) + min(max(dx, dy), 0.0) - r


def circle_dist(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


# ---------- форма иконки ----------
def icon_shape(px, py, scale=1.0, maskable=False):
    """Возвращает цвет пикселя. scale — размер буквы относительно 512."""
    # Фон: градиент indigo (диагональный)
    t = (px + py) / 1024.0
    bg = tuple(int(INDIGO_600[i] + (INDIGO_900[i] - INDIGO_600[i]) * t) for i in range(3))
    bg_a = 0.0

    if maskable:
        # Для maskable фон залит полностью (края срежет ОС)
        bg_a = 1.0
    else:
        # Скруглённый квадрат
        d = rounded_rect_dist(px, py, 256, 256, 512, 512, 116)
        bg_a = 1.0 if d <= 0 else max(0.0, 1.0 - d)

    out = [bg[0], bg[1], bg[2], int(255 * bg_a)]

    # Дополнительные полупрозрачные круги-«звёзды» на фоне
    for (cx, cy, r, op) in ((150, 92, 130, 0.05), (386, 420, 150, 0.05), (420, 96, 70, 0.06)):
        cc = circle_dist(px, py, cx, cy, r)
        if cc <= 0 and bg_a > 0:
            a = int(out[3] * op)
            out[3] = max(out[3], a)

    # Буква M — размер зависит от режима (у maskable меньше — безопасная зона)
    k = 0.94 if not maskable else 0.66

    cx, cy = 256, 258
    sw = 44 * k          # толщина штриха
    cap = sw / 2
    w_stem = 88 * k      # ширина боковых штрихов
    w_half = w_stem / 2

    top = cy - 84 * k
    bot = cy + 86 * k
    xl, xr = cx - w_half, cx + w_half

    # Рисуем M как набор отрезков (с шапочками)
    strokes = [
        ((xl, top), (xl, bot)),                       # левый штрих
        ((xl, bot), (cx, top - 6 * k)),               # диагональ вверх
        ((cx, top - 6 * k), (xr, bot)),               # диагональ вниз
        ((xr, top), (xr, bot)),                       # правый штрих
    ]
    min_pix = 1e9
    for (a, b) in strokes:
        d = seg_dist(px, py, a[0], a[1], b[0], b[1]) - cap
        if d < min_pix:
            min_pix = d

    if min_pix <= 0 and bg_a > 0:
        out = [WHITE[0], WHITE[1], WHITE[2], 255]
    return tuple(out)


# ---------- PNG-запись ----------
def write_png(path, size, pixels, with_alpha=True):
    hdr = b"\x89PNG\r\n\x1a\n"

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    color_type = 6 if with_alpha else 2
    ihdr = struct.pack(">IIBBBBB", size, size, 8, color_type, 0, 0, 0)
    raw = bytearray()
    row_len = size * (4 if with_alpha else 3)
    for y in range(size):
        raw.append(0)  # filter none
        raw.extend(pixels[y * row_len: y * row_len + row_len])
    png = (
        hdr
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)
    print(f"  {os.path.relpath(path, os.path.dirname(os.path.dirname(path)))} ({size}x{size}, {os.path.getsize(path)} байт)")


def render(size, maskable=False, with_alpha=True):
    SS = 4  # суперсэмплинг
    big = size * SS
    buf = bytearray(big * big * 4)
    for y in range(big):
        for x in range(big):
            # центр пикселя в координатах 512
            px = (x + 0.5) / big * 512
            py = (y + 0.5) / big * 512
            r, g, b, a = icon_shape(px, py, maskable=maskable)
            i = (y * big + x) * 4
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = a

    # боксовый даунсэмпл
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            acc = [0, 0, 0, 0]
            for dy in range(SS):
                for dx in range(SS):
                    i = ((y * SS + dy) * big + x * SS + dx) * 4
                    a = buf[i + 3]
                    for c in range(4):
                        acc[c] += buf[i + c] * a  # premultiplied by alpha
            total_a = sum(buf[((y * SS + dy) * big + x * SS + dx) * 4 + 3] for dy in range(SS) for dx in range(SS))
            i = (y * size + x) * 4
            if total_a > 0:
                for c in range(3):
                    out[i + c] = acc[c] // total_a
                out[i + 3] = total_a // (SS * SS)
            else:
                out[i] = out[i + 1] = out[i + 2] = 0
                out[i + 3] = 0

    if not with_alpha:
        # убрать альфу: композит на белый
        flat = bytearray(size * size * 3)
        for i in range(size * size):
            a = out[i * 4 + 3] / 255.0
            for c in range(3):
                flat[i * 3 + c] = int(out[i * 4 + c] * a + 255 * (1 - a))
        return bytes(flat)
    return bytes(out)


def main():
    print("Генерация иконок PWA →", OUT)
    os.makedirs(OUT, exist_ok=True)

    # 512 обычная
    write_png(os.path.join(OUT, "icon-512.png"), 512, render(512, maskable=False))
    # 192 обычная
    write_png(os.path.join(OUT, "icon-192.png"), 192, render(192, maskable=False))
    # maskable 512/192 (полный фон + безопасная зона)
    write_png(os.path.join(OUT, "icon-maskable-512.png"), 512, render(512, maskable=True))
    write_png(os.path.join(OUT, "icon-maskable-192.png"), 192, render(192, maskable=True))
    # apple-touch-icon 180 (без альфы)
    write_png(os.path.join(OUT, "apple-touch-icon.png"), 180, render(180, maskable=False), with_alpha=False)
    print("Готово.")


if __name__ == "__main__":
    main()