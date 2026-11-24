"""
Re-render Hasselblad Standard (HNCS) 6-way comparison chart with clear Chinese titles,
explanations, and a Macbeth 24-patch ColorChecker legend.
"""

import pathlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.interpolate import RegularGridInterpolator

FS = pathlib.Path("D:/AI_LUT/extracted/fs")
OUT_DIR = pathlib.Path("D:/AI_LUT/output/Hasselblad_Standard_HNCS")


def load_cube(path: pathlib.Path) -> np.ndarray:
    N = None
    vals = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(("TITLE", "DOMAIN_")):
            continue
        if s.startswith("LUT_3D_SIZE"):
            N = int(s.split()[1])
        else:
            vals.append([float(x) for x in s.split()[:3]])
    return np.array(vals, dtype=np.float32).reshape(N, N, N, 3)


def build_test_chart(w=460, h=260) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.float32)
    top_h = 78
    x = np.linspace(0, 1, w, dtype=np.float32)
    y = np.linspace(0, 1, top_h, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    h6 = xx * 6.0
    sat = 0.85
    val = 0.25 + 0.75 * (1.0 - yy)
    c = val * sat
    x_hsv = c * (1.0 - np.abs((h6 % 2.0) - 1.0))
    m = val - c
    r = np.select([h6 < 1, h6 < 2, h6 < 3, h6 < 4, h6 < 5], [c, x_hsv, 0, 0, x_hsv], default=c) + m
    g = np.select([h6 < 1, h6 < 2, h6 < 3, h6 < 4, h6 < 5], [x_hsv, c, c, x_hsv, 0], default=0) + m
    b = np.select([h6 < 1, h6 < 2, h6 < 3, h6 < 4, h6 < 5], [0, 0, x_hsv, c, c], default=x_hsv) + m
    img[:top_h] = np.stack([r, g, b], axis=-1)

    patches = [
        (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
        (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
        (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
        (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
    ]
    grid_y0 = top_h + 6
    cell_h = (h - grid_y0 - 6) // 4
    cell_w = (w - 12) // 6
    img[top_h:] = 0.12
    for idx, rgb in enumerate(patches):
        row, col = divmod(idx, 6)
        y0 = grid_y0 + row * cell_h + 2
        x0 = 6 + col * cell_w + 2
        img[y0 : y0 + cell_h - 4, x0 : x0 + cell_w - 4] = np.array(rgb, dtype=np.float32) / 255.0
    return img


def get_font(size: int, bold: bool = False):
    candidates = (
        ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc"]
        if bold
        else ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]
    )
    for fp in candidates:
        if pathlib.Path(fp).exists():
            return ImageFont.truetype(fp, size=size)
    return ImageFont.load_default()


def main():
    chart = build_test_chart(460, 260)

    nat_raw = np.frombuffer((FS / "odm/etc/camera/filters_lut/natural.cube.rgb.bin").read_bytes(), dtype=np.uint8)
    nat_lut = nat_raw.reshape(32, 32, 32, 4)[..., :3].astype(np.float32) / 255.0

    cards = [
        (
            "1. 原图基准（中性 sRGB）",
            "无任何 LUT 修饰的标准 24 色卡，用于对比色彩偏移与灰阶变化",
            None,
            (215, 220, 230),
        ),
        (
            "2. 主摄 D65 哈苏标准 HNCS（纯色彩版 · 推荐）",
            "仅含 36×20×20 HueSatMap：灰阶曝光不变，绿更翠、蓝更沉、肤色自然",
            load_cube(OUT_DIR / "Hasselblad_Standard_HNCS_Main_D65_ColorOnly_64.cube"),
            (130, 220, 170),
        ),
        (
            "3. 主摄 D65 哈苏标准 HNCS（含 128 点影调曲线）",
            "叠加官方 ToneCurve：中间调提亮通透、暗部扎实，适合灰片/平曲线素材",
            load_cube(OUT_DIR / "Hasselblad_Standard_HNCS_Main_D65_Full_ToneCurve_64.cube"),
            (250, 200, 115),
        ),
        (
            "4. 潜望长焦 D65 哈苏标准 HNCS（纯色彩版）",
            "潜望长焦专属 HNCS 校准表，整体风格与主摄统一，红蓝局部响应微调",
            load_cube(OUT_DIR / "Hasselblad_Standard_HNCS_Tele_D65_ColorOnly_64.cube"),
            (135, 195, 250),
        ),
        (
            "5. 主摄 D28（2856K）暖光校准版 HNCS",
            "面向室内钨丝灯/暖光环境的标定表，红绿饱和度补偿显著高于 D65 日光版",
            load_cube(OUT_DIR / "Hasselblad_Standard_HNCS_Main_D28_ColorOnly_33.cube"),
            (245, 165, 145),
        ),
        (
            "6. 对比参考：相机内置「自然 (natural)」滤镜",
            "filters_lut 普通创意滤镜（可见左下白块明显偏青冷），并非哈苏 HNCS",
            nat_lut,
            (190, 175, 235),
        ),
    ]

    font_header = get_font(22, bold=True)
    font_title = get_font(16, bold=True)
    font_desc = get_font(12, bold=False)
    font_legend = get_font(13, bold=False)

    w, h = 460, 260
    cols, rows = 3, 2
    pad_x, pad_y = 22, 20
    top_banner = 56
    card_text_h = 52
    bottom_legend = 52

    canvas_w = cols * w + (cols + 1) * pad_x
    canvas_h = top_banner + rows * (h + card_text_h + pad_y) + pad_y + bottom_legend
    canvas = Image.new("RGB", (canvas_w, canvas_h), (20, 22, 26))
    draw = ImageDraw.Draw(canvas)

    # Top title banner
    draw.text(
        (pad_x, 14),
        "某国产哈苏色彩科学（HNCS）6 组核心 LUT 对比验证图",
        fill=(245, 247, 250),
        font=font_header,
    )

    for idx, (title, desc, lut, accent) in enumerate(cards):
        rr, cc = divmod(idx, cols)
        x0 = pad_x + cc * (w + pad_x)
        y0 = top_banner + rr * (h + card_text_h + pad_y)

        # Subtle card background box
        draw.rounded_rectangle(
            [x0 - 6, y0 - 6, x0 + w + 6, y0 + card_text_h + h + 6],
            radius=8,
            fill=(30, 33, 39),
            outline=(52, 56, 66),
            width=1,
        )
        draw.text((x0 + 2, y0 + 2), title, fill=accent, font=font_title)
        draw.text((x0 + 2, y0 + 26), desc, fill=(195, 200, 210), font=font_desc)

        if lut is None:
            rendered = chart
        else:
            N = lut.shape[0]
            grid = np.linspace(0, 1, N, dtype=np.float32)
            interp = RegularGridInterpolator((grid, grid, grid), lut, bounds_error=False, fill_value=None)
            rendered = np.clip(interp(chart[..., [2, 1, 0]]), 0.0, 1.0)

        tile = Image.fromarray((rendered * 255.0).round().astype(np.uint8))
        canvas.paste(tile, (x0, y0 + card_text_h))

    # Bottom legend
    ly = canvas_h - bottom_legend + 8
    draw.line([(pad_x, ly - 6), (canvas_w - pad_x, ly - 6)], fill=(55, 60, 70), width=1)
    draw.text(
        (pad_x, ly + 2),
        "色卡读图指南：上方彩虹条 = 连续色相与明暗过渡（检验是否平滑/断层） ｜ 第 1 行 = 深浅肤色 / 蓝天 / 绿叶 / 蓝花 / 青绿",
        fill=(185, 192, 204),
        font=font_legend,
    )
    draw.text(
        (pad_x, ly + 22),
        "第 2 行 = 橙 / 紫蓝 / 中红 / 紫 / 黄绿 / 橙黄 ｜ 第 3 行 = RGB 三原色与黄品青 ｜ 第 4 行 = 白→黑 6 级中性灰阶（检验是否偏色或提亮）",
        fill=(160, 168, 180),
        font=font_legend,
    )

    out_png = pathlib.Path("D:/AI_LUT/docs/figures/07_hncs_6way_comparison.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png)
    print(f"Saved annotated Chinese comparison chart: {out_png} ({canvas.size})")


if __name__ == "__main__":
    main()
