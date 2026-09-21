# -*- coding: utf-8 -*-
"""生成应用图标。只用 Pillow, 不引别的依赖。

产物:
  assets/logo.png   512x512, 说明文档/页面里用
  assets/icon.ico   16/24/32/48/64/128/256, 打包时作为 exe 图标

图案: 圆角蓝色卡片 + 白色量程环(已用量纯白、未用量淡白), 环上带一个指示点 ——
对应浮窗本职: 盯余额与今日流量。

每一档都按 8 倍超采样单独渲染再缩回去; 16/24/32 改用更粗的描边、去掉玻璃高光,
否则环与底槽缩到 16px 会糊成一团。

用法: python -X utf8 make_logo.py
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "assets")
SS = 8                              # 超采样倍数
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TILE_TOP = (0x4F, 0xB0, 0xFF)       # 左上角亮蓝
TILE_BOTTOM = (0x00, 0x53, 0xC4)    # 右下角深蓝
RADIUS_F = 0.225                    # 圆角半径 / 边长
ARC_A0, ARC_A1 = 140.0, 40.0        # PIL 角度以 3 点钟为 0 度、顺时针增大; 缺口正对下方
ARC_VALUE = 285.0                   # 已用量画到这个角度


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def tile(size):
    """圆角卡片 + 对角渐变。渐变在 192px 上算好再放大, 免得逐像素遍历大图。"""
    n = 192
    small = Image.new("RGB", (n, n))
    px = small.load()
    d = 2.0 * (n - 1)
    for y in range(n):
        for x in range(n):
            px[x, y] = lerp(TILE_TOP, TILE_BOTTOM, (x + y) / d)
    img = small.resize((size, size), Image.BICUBIC).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(RADIUS_F * size), fill=255)
    img.putalpha(mask)
    return img, mask


def glass_highlight(size, mask):
    """顶部一层很淡的白, 给大尺寸那几档一点玻璃感。"""
    fade = int(0.46 * size)
    hl = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(hl)
    for i in range(fade):
        d.line([(0, i), (size, i)], fill=int(34 * (1 - i / float(fade)) ** 2))
    hl = ImageChops.multiply(hl, mask)          # 别越过圆角画到卡片外面
    layer = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    layer.putalpha(hl)
    return layer


def at(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def gauge(size, compact):
    """量程环: 淡色底槽 + 白色已用量 + 末端指示点。PIL 的 arc 是方头, 两端自己补圆。"""
    ov = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    w = (0.148 if compact else 0.082) * size
    cx, cy, r = size / 2.0, 0.545 * size, 0.300 * size
    box = [cx - r, cy - r, cx + r, cy + r]
    track = 120 if compact else 90
    d.arc(box, ARC_A0, ARC_A1, fill=(255, 255, 255, track), width=int(w))
    d.arc(box, ARC_A0, ARC_VALUE, fill=(255, 255, 255, 255), width=int(w))
    for deg in (ARC_A0, ARC_A1):
        x, y = at(cx, cy, r, deg)
        d.ellipse([x - w / 2.0, y - w / 2.0, x + w / 2.0, y + w / 2.0],
                  fill=(255, 255, 255, track))
    x, y = at(cx, cy, r, ARC_VALUE)
    rad = w * (0.66 if compact else 0.78)
    d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(255, 255, 255, 255))
    return ov


def render(px):
    compact = px <= 32
    s = px * SS
    img, mask = tile(s)
    if not compact:
        img.alpha_composite(glass_highlight(s, mask))
    img.alpha_composite(gauge(s, compact))
    return img.resize((px, px), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    png = os.path.join(OUT_DIR, "logo.png")
    render(512).save(png)
    frames = [render(n) for n in ICO_SIZES]
    ico = os.path.join(OUT_DIR, "icon.ico")
    # 每档都用自己渲染好的那张(尺寸正好对上, Pillow 会直接取), 不走默认的整体缩略
    frames[-1].save(ico, sizes=[(n, n) for n in ICO_SIZES],
                    append_images=frames[:-1])
    print("写出 %s (512x512)" % png)
    print("写出 %s (%s)" % (ico, ", ".join("%dpx" % n for n in ICO_SIZES)))


if __name__ == "__main__":
    main()
