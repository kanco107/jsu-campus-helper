# -*- coding: utf-8 -*-
"""生成校园网助手 LOGO：蓝色渐变圆角方块 + 白色盾牌 + WiFi 信号。
输出 assets/logo.ico（多尺寸，供 EXE/安装程序）和 ui/logo.png（界面标题栏）。
"""
import math
import os
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))
S = 4                      # 4 倍超采样抗锯齿
N = 256
W = N * S


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main():
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ---------- 背景：圆角方块 + 对角渐变 ----------
    radius = 56 * S
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=radius, fill=255)

    top_left = (13, 70, 160)      # #0D469E 深蓝
    bottom_right = (47, 161, 242) # #2FA1F2 亮蓝
    grad = Image.new("RGBA", (W, W))
    gd = ImageDraw.Draw(grad)
    for y in range(W):
        for x in range(0, W, 4):
            t = (x / W * 0.6 + y / W * 0.4)
            color = lerp(top_left, bottom_right, t)
            gd.line([(x, y), (x + 3, y)], fill=color + (255,))
    grad.putalpha(mask)
    img.alpha_composite(grad)

    # ---------- 白色盾牌 ----------
    # 256 坐标系下程序化生成盾牌轮廓：顶部圆角 + 底部贝塞尔尖底
    R = 18            # 顶部圆角半径
    x_l, x_r, y_t = 72, 184, 66
    y_r = 138         # 右侧边结束点
    y_b = 196         # 底部尖端 y
    cx = (x_l + x_r) / 2

    def bezier(p0, p1, p2, p3, n=24):
        pts = []
        for i in range(n + 1):
            t = i / n
            x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
            y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
            pts.append((x, y))
        return pts

    outline = []
    # 顶边（左圆角终点到右圆角起点）
    outline.append((x_l + R, y_t))
    outline.append((x_r - R, y_t))
    # 右上圆角：圆心 (x_r-R, y_t+R)，角度 -90 -> 0
    c = (x_r - R, y_t + R)
    for a in range(-90, 1, 10):
        rad = math.radians(a)
        outline.append((c[0] + R * math.cos(rad), c[1] + R * math.sin(rad)))
    # 右侧边
    outline.append((x_r, y_r))
    # 右下贝塞尔到底尖
    outline += bezier((x_r, y_r), (x_r, 170), (152, 190), (cx, y_b))[1:]
    # 底尖到左下
    outline += bezier((cx, y_b), (104, 190), (x_l, 170), (x_l, y_r))[1:]
    # 左侧边
    outline.append((x_l, y_t + R))
    # 左上圆角：圆心 (x_l+R, y_t+R)，角度 180 -> 270
    c = (x_l + R, y_t + R)
    for a in range(180, 271, 10):
        rad = math.radians(a)
        outline.append((c[0] + R * math.cos(rad), c[1] + R * math.sin(rad)))

    shield = [(x * S, y * S) for x, y in outline]
    draw.polygon(shield, fill=(255, 255, 255, 255))

    # ---------- 盾牌内蓝色 WiFi 信号 ----------
    blue = (13, 70, 160, 255)   # 与深蓝背景呼应，在白盾上对比清晰
    wx, wy = 128 * S, 148 * S   # 信号圆心（略偏下，弧线向上展开）
    width = 10 * S              # 弧线粗细

    def arc(r, start=205, end=335):
        bbox = [wx - r * S, wy - r * S, wx + r * S, wy + r * S]
        draw.arc(bbox, start, end, fill=blue, width=width)

    arc(24)   # 内弧
    arc(37)
    arc(50)   # 外弧
    # 底部圆点
    dot_r = 7 * S
    draw.ellipse([wx - dot_r, wy - dot_r, wx + dot_r, wy + dot_r], fill=blue)

    # 缩回 256，抗锯齿
    final = img.resize((N, N), Image.LANCZOS)

    ico_path = os.path.join(BASE, "assets", "logo.ico")
    os.makedirs(os.path.join(BASE, "assets"), exist_ok=True)
    icon_sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                  (48, 48), (64, 64), (128, 128), (256, 256)]
    final.save(ico_path, format="ICO", sizes=icon_sizes)
    print("已生成", ico_path)

    png_path = os.path.join(BASE, "ui", "logo.png")
    final.save(png_path, format="PNG")
    print("已生成", png_path)


if __name__ == "__main__":
    main()
