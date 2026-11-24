"""
Generate 6 Publication-Grade Technical Principle Diagrams (Anonymized for GitHub)
=================================================================================
All plots use real numerical data extracted from the color pipeline calibration tables
while keeping brand/device names anonymized as "某国产哈苏色彩科学".

Outputs in D:/AI_LUT/docs/figures/:
  01_color_pipeline_architecture.png
  02_lut_binary_formats_layout.png
  03_hncs_color_science_data.png
  04_master_mode_3x3_engine.png
  05_a7c2_gamut_and_slog3_rolloff.png
  06_a7c2_dcp_sensor_decoupling.png
"""

import json
import pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# Configure clean Chinese typography (Microsoft YaHei)
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

FS = pathlib.Path("D:/AI_LUT/extracted/fs")
DNG_DIR = FS / "odm/etc/camera/dng"
BT_LMT_DIR = FS / "odm/etc/camera/basictone/lmt"
VIG_JSON = pathlib.Path("D:/AI_LUT/output/08_DNG_HNCS_and_Vignette/vignette_tables_13x17.json")
FIG_DIR = pathlib.Path("D:/AI_LUT/docs/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

# Modern Dark GitHub-friendly Palette
BG = "#0F131A"
CARD = "#171D27"
BORDER = "#2B3548"
TXT = "#E8EEF7"
MUTED = "#9AA8BE"
BLUE = "#4DA3FF"
CYAN = "#38D9C0"
GREEN = "#57D182"
AMBER = "#F6B94E"
CORAL = "#FF7369"
PURPLE = "#B58CFF"


def draw_box(ax, x, y, w, h, title, body="", edge=BLUE, fill=CARD, title_color=None, title_size=11.5, body_size=9.2):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        linewidth=1.6, edgecolor=edge, facecolor=fill, zorder=2
    )
    ax.add_patch(box)
    tc = title_color or edge
    if body:
        ax.text(x + w / 2, y + h - 0.025, title, color=tc, fontsize=title_size, fontweight="bold",
                ha="center", va="top", zorder=3)
        ax.text(x + w / 2, y + h / 2 - 0.02, body, color=TXT, fontsize=body_size,
                ha="center", va="center", linespacing=1.45, zorder=3)
    else:
        ax.text(x + w / 2, y + h / 2, title, color=tc, fontsize=title_size, fontweight="bold",
                ha="center", va="center", zorder=3)


def draw_arrow(ax, p1, p2, color=MUTED, lw=1.8, rad=0.0):
    arr = FancyArrowPatch(
        p1, p2,
        arrowstyle="-|>,head_length=7,head_width=4.5",
        connectionstyle=f"arc3,rad={rad}",
        color=color, linewidth=lw, zorder=4
    )
    ax.add_patch(arr)


# =============================================================================
# FIGURE 1: 5-Stage Mobile Color Processing Pipeline Architecture
# =============================================================================
def fig01_pipeline():
    fig, ax = plt.subplots(figsize=(14, 7.8), dpi=180, facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.03, 0.945, "图 1｜某国产哈苏色彩科学：5 级端到端色彩处理管线架构（固件实证）",
            color=TXT, fontsize=16, fontweight="bold", va="top")
    ax.text(0.03, 0.902, "从传感器 RAW 线性光出发，历经 DNG HNCS 标定、计算摄影、类 ACES BasicTone 影调引擎到风格滤镜与显示管理",
            color=MUTED, fontsize=10.5, va="top")

    # Stage 1..3 top row
    draw_box(ax, 0.03, 0.63, 0.27, 0.21, "① 传感器原始光信号 (RAW)",
             "• 主摄 / 潜望长焦 / 超广角 CMOS\n• 12/14-bit 线性 Bayer 原始数据\n• 传感器固有光谱响应（设备相关）",
             edge=BLUE)
    draw_box(ax, 0.365, 0.63, 0.28, 0.21, "② 哈苏自然色彩校准层 (HNCS)",
             "• 双光源 ColorMatrix1/2 (2856K / D65)\n• 36×20×20 = 14,400 节点 3D HueSatMap\n• 128 点官方影调曲线 ToneCurve\n• 决定“哈苏标准”自然色彩基因",
             edge=GREEN)
    draw_box(ax, 0.71, 0.63, 0.26, 0.21, "③ 计算摄影与 RAW2YUV",
             "• 多帧融合 / HDR / 去马赛克\n• 硬件 ISP 3D LUT + 肤色保护\n• 输出 BT.2020 Limited YUV\n  或 Display P3 工作空间",
             edge=CYAN)

    draw_arrow(ax, (0.305, 0.735), (0.36, 0.735), color=BLUE)
    draw_arrow(ax, (0.65, 0.735), (0.705, 0.735), color=GREEN)

    # Stage 4: BasicTone big container
    bt_bg = FancyBboxPatch((0.03, 0.24), 0.94, 0.30, boxstyle="round,pad=0.012,rounding_size=0.018",
                           linewidth=1.8, edgecolor=AMBER, facecolor="#151A24", linestyle="--", zorder=1)
    ax.add_patch(bt_bg)
    ax.text(0.048, 0.525, "④ BasicTone 影调与大师模式引擎（GPU GLSL 着色器 + 实时 3D LUT 融合）",
            color=AMBER, fontsize=12, fontweight="bold", va="top")

    sub_w = 0.165
    gap = 0.022
    sx = 0.048
    subs = [
        ("BT.2020 矩阵转换", "Limited YUV\n→ RGB [0, 1]\n(确保3D查表在RGB)", BLUE),
        ("LMT 基础影调", "BaseLut / LMTLut\n64³ float32\n类 ACES 风格变换", CYAN),
        ("大师模式四滑块", "SC32 3×3 (饱和×对比)\nCWCM32 3×3 (冷暖×色调)\n实时双线性插值合成", AMBER),
        ("ODT 输出设备变换", "ODT_Photo / Dolby\n64³ float32\nPQ 10000nits 高光滚降", CORAL),
        ("光学暗角 + 抖动", "VigTab 17×13 增益表\n(四角衰减至 0.742)\n+ 8/10bit Dither 防断层", PURPLE),
    ]
    for i, (t, b, col) in enumerate(subs):
        cx = sx + i * (sub_w + gap)
        draw_box(ax, cx, 0.265, sub_w, 0.215, t, b, edge=col, fill="#1C2330", title_size=10.2, body_size=8.5)
        if i > 0:
            draw_arrow(ax, (cx - gap + 0.003, 0.372), (cx - 0.003, 0.372), color=AMBER, lw=1.6)

    # Arrow from Stage 3 down into Stage 4
    draw_arrow(ax, (0.84, 0.625), (0.84, 0.545), color=CYAN, lw=1.8)

    # Stage 5 bottom row
    draw_box(ax, 0.03, 0.04, 0.44, 0.14, "⑤ 风格滤镜层（相机 / 相册 3D LUT）",
             "• 哈苏大师滤镜（童话 / 人像 / 风光 / XPan 黑白 / 北欧三杰）  • 经典胶片模拟（NC / CC / NH）  • 城市旅拍",
             edge=PURPLE, title_size=11, body_size=8.8)
    draw_box(ax, 0.53, 0.04, 0.44, 0.14, "⑥ 成片编码与屏幕色彩管理",
             "• JPEG / HEIF / ProXDR / 杜比视界视频编码   • 屏幕级 3D LUT 校准（sRGB / Display P3 色域映射）",
             edge=GREEN, title_size=11, body_size=8.8)

    draw_arrow(ax, (0.25, 0.235), (0.25, 0.185), color=AMBER, lw=1.8)
    draw_arrow(ax, (0.475, 0.11), (0.525, 0.11), color=PURPLE, lw=1.8)

    plt.tight_layout(pad=0.3)
    fig.savefig(FIG_DIR / "01_color_pipeline_architecture.png", dpi=180, facecolor=BG)
    plt.close(fig)


# =============================================================================
# FIGURE 2: 4 Native Firmware Binary LUT Formats & Axis-Order Pitfall
# =============================================================================
def fig02_binary_formats():
    fig, ax = plt.subplots(figsize=(14, 8.2), dpi=180, facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.03, 0.962, "图 2｜固件内 4 种原生 3D LUT 二进制存储结构与逆向转换规范",
            color=TXT, fontsize=16, fontweight="bold", va="top")
    ax.text(0.03, 0.922, "所有格式均经跨目录逐像素比对验证（误差 MAE = 0.000），精准还原至行业标准 Adobe .cube 格式",
            color=MUTED, fontsize=10.5, va="top")

    rows = [
        (
            0.685, BLUE,
            "格式 A｜RGBA8 原始 3D LUT（filters_lut / 相册 luts）",
            [("Pixel[0]\nR G B A", 0.14, "#1E3350"), ("Pixel[1]\nR G B A", 0.14, "#1E3350"),
             ("...  共 N³ × 4 字节 (uint8)  ...", 0.34, "#192638"), ("Pixel[N³-1]\nR G B A", 0.14, "#1E3350")],
            "尺寸：16³×4 (16 KB) / 32³×4 (128 KB) / 33³×4 (140 KB)  ｜  轴序：[B, G, R]（R 轴变化最快，与 .cube 一致）\n"
            "转换规则：丢弃第 4 字节 Alpha，前 3 字节 ÷ 255.0 直接写出标准 .cube"
        ),
        (
            0.465, CORAL,
            "格式 B｜美摄 .MS-LUT 容器（meishe_lut：含胶片 NC / CC / NH）  ★ 关键坑点",
            [("Magic 8B\n'.MS-LUT '", 0.13, "#3D2228"), ("ver / N\n8B", 0.09, "#3D2228"),
             ("axis_flag\n@24B (0或1)", 0.15, "#6E232C"), ("1D 网格\nN×4B", 0.11, "#2A2438"),
             ("Payload: N³ × 3 字节 (uint8 RGB)", 0.28, "#1E2D38")],
            "★ 核心逆向发现：偏移 24 处的 axis_flag 决定输入轴顺序！\n"
            "  • axis_flag = 1 → [B, G, R] 直接导出    • axis_flag = 0（如胶片 NC/CC/NH）→ [R, G, B]，必须做 (2,1,0) 转置否则红蓝轴互换！"
        ),
        (
            0.245, AMBER,
            "格式 C｜BasicTone 平面 float32（basictone/{lmt, odt}：大师模式核心）",
            [("R 通道平面\nN³ × 4B (float32)", 0.24, "#3A2F1C"),
             ("G 通道平面\nN³ × 4B (float32)", 0.24, "#233628"),
             ("B 通道平面\nN³ × 4B (float32)", 0.24, "#1D2C44")],
            "尺寸：32³×3×4 (384 KB) / 64³×3×4 (3.0 MB)  ｜  布局：Planar 平面存储 [3, B, G, R]，原生 32-bit 浮点 [0.0, 1.0]\n"
            "转换规则：reshape(3, N, N, N) → transpose(1, 2, 3, 0) 无损保留浮点高精度写出 .cube"
        ),
        (
            0.025, GREEN,
            "格式 D｜512×512 PNG HaldCLUT（相册编辑器 64³ 高精度滤镜）",
            [("8 × 8 宫格图块 (Tile)\nb = tile_y × 8 + tile_x", 0.34, "#1D382B"),
             ("单图块 64 × 64 像素\nx 轴 = R (0..63), y 轴 = G (0..63)", 0.42, "#1C2E2B")],
            "标准 GPUImage 512×512 排布：reshape(8, 64, 8, 64, 3) → transpose(0, 2, 1, 3, 4) → reshape(64, 64, 64, 3) ÷ 255.0"
        ),
    ]

    for y0, col, title, blocks, note in rows:
        card = FancyBboxPatch((0.03, y0), 0.94, 0.188, boxstyle="round,pad=0.008,rounding_size=0.015",
                              linewidth=1.5, edgecolor=col, facecolor=CARD, zorder=1)
        ax.add_patch(card)
        ax.text(0.05, y0 + 0.175, title, color=col, fontsize=11.3, fontweight="bold", va="top")

        bx = 0.05
        for btxt, bw, bfill in blocks:
            bpatch = FancyBboxPatch((bx, y0 + 0.080), bw, 0.055, boxstyle="round,pad=0.004,rounding_size=0.008",
                                    linewidth=1.1, edgecolor=col, facecolor=bfill, zorder=2)
            ax.add_patch(bpatch)
            ax.text(bx + bw / 2, y0 + 0.1075, btxt, color=TXT, fontsize=8.6, ha="center", va="center", zorder=3)
            bx += bw + 0.012

        ax.text(0.05, y0 + 0.012, note, color=MUTED if col != CORAL else "#F7D2CF",
                fontsize=8.8, va="bottom", linespacing=1.40)

    plt.tight_layout(pad=0.3)
    fig.savefig(FIG_DIR / "02_lut_binary_formats_layout.png", dpi=180, facecolor=BG)
    plt.close(fig)


# =============================================================================
# FIGURE 3: Real Firmware Data Plot of Hasselblad Standard (HNCS)
# =============================================================================
def fig03_hncs_data():
    hsm_file = next(DNG_DIR.glob("D65HUESATMap_*main*.txt"))
    tc_file = next(DNG_DIR.glob("ToneCurve_*main*.txt"))
    raw_hsm = hsm_file.read_text()
    hsm = np.array([float(x) for x in raw_hsm.replace("\n", ",").split(",") if x.strip()], dtype=np.float64).reshape(20, 36, 20, 3)
    raw_tc = tc_file.read_text()
    tc = np.array([float(x) for x in raw_tc.replace("\n", ",").split(",") if x.strip()], dtype=np.float64).reshape(-1, 2)
    vig = np.array(json.loads(VIG_JSON.read_text(encoding="utf-8"))["VigTab_Main"]["table"], dtype=np.float64)

    fig = plt.figure(figsize=(14.5, 8.2), dpi=180, facecolor=BG)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.0], width_ratios=[1.25, 1.0], hspace=0.36, wspace=0.24,
                          left=0.06, right=0.96, top=0.86, bottom=0.08)

    fig.suptitle("图 3｜哈苏标准自然色彩（HNCS）数学本体实测可视化（直接绘制自固件标定表）",
                 color=TXT, fontsize=15.5, fontweight="bold", x=0.04, ha="left", y=0.96)
    fig.text(0.04, 0.915, "数据源：主摄 D65 36×20×20 HueSatMap（73.8% 非恒等）、128 点官方 ToneCurve、17×13 光学暗角增益表",
             color=MUTED, fontsize=10.2)

    hues = np.arange(36) * 10
    # Slice at V=10 (midtone), S=15 (high chroma) & S=10 (mid chroma)
    dh_hi = hsm[10, :, 15, 0]
    dh_md = hsm[10, :, 10, 0]
    sat_hi = hsm[10, :, 15, 1]
    val_hi = hsm[10, :, 15, 2]

    # Panel A: Delta Hue vs 360° Hue
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor(CARD)
    ax1.axhline(0, color=BORDER, lw=1.2, ls="--")
    ax1.plot(hues, dh_hi, color=AMBER, lw=2.4, marker="o", ms=3.5, label="高饱和区 (S=15/19)")
    ax1.plot(hues, dh_md, color=CYAN, lw=1.8, ls="--", label="中饱和区 (S=10/19)")
    ax1.fill_between(hues, 0, dh_hi, color=AMBER, alpha=0.14)
    ax1.set_title("A. 360° 色相偏移曲线 ΔHue（度）", color=TXT, fontsize=11.5, fontweight="bold", pad=8)
    ax1.set_ylabel("色相偏移 (°)", color=MUTED, fontsize=9.5)
    ax1.set_xticks([0, 60, 120, 180, 240, 300, 350])
    ax1.set_xticklabels(["0° 红", "60° 黄", "120° 绿", "180° 青", "240° 蓝", "300° 品", "350°"], color=MUTED, fontsize=8.8)
    ax1.tick_params(colors=MUTED)
    for sp in ax1.spines.values():
        sp.set_color(BORDER)
    ax1.grid(True, color=BORDER, alpha=0.35, lw=0.7)
    ax1.legend(facecolor=CARD, edgecolor=BORDER, labelcolor=TXT, fontsize=8.5, loc="upper right")
    ax1.annotate("黄色向暖金/橄榄微移 (+5.2°)\n消除数码刺眼黄", xy=(60, dh_hi[6]), xytext=(95, 4.0),
                 color=AMBER, fontsize=8.2, arrowprops=dict(arrowstyle="->", color=AMBER, lw=1.1))
    ax1.annotate("品紫回调 (-3.9°)", xy=(320, dh_hi[32]), xytext=(235, -3.7),
                 color=PURPLE, fontsize=8.2, arrowprops=dict(arrowstyle="->", color=PURPLE, lw=1.1))

    # Panel B: SatScale & ValScale vs 360° Hue
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.set_facecolor(CARD)
    ax2.axhline(1.0, color=BORDER, lw=1.2, ls="--")
    ax2.plot(hues, sat_hi, color=GREEN, lw=2.3, marker="o", ms=3.2, label="饱和度倍率 (SatScale)")
    ax2.plot(hues, val_hi, color=BLUE, lw=2.3, marker="s", ms=3.0, label="明度倍率 (ValScale)")
    ax2.set_title("B. 360° 饱和度与明度响应（中灰明度层 V=10/19）", color=TXT, fontsize=11.5, fontweight="bold", pad=8)
    ax2.set_ylabel("增益倍率 (1.0=不变)", color=MUTED, fontsize=9.5)
    ax2.set_xticks([0, 60, 120, 180, 240, 300, 350])
    ax2.set_xticklabels(["0° 红", "60° 黄", "120° 绿", "180° 青", "240° 蓝", "300° 品", "350°"], color=MUTED, fontsize=8.8)
    ax2.tick_params(colors=MUTED)
    for sp in ax2.spines.values():
        sp.set_color(BORDER)
    ax2.grid(True, color=BORDER, alpha=0.35, lw=0.7)
    ax2.legend(facecolor=CARD, edgecolor=BORDER, labelcolor=TXT, fontsize=8.5, loc="lower left")
    ax2.annotate("草绿提饱和 (1.09×)", xy=(100, sat_hi[10]), xytext=(125, 1.08),
                 color=GREEN, fontsize=8.2, arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.1))
    ax2.annotate("蓝天降明度 (0.88×)\n经典哈苏深邃蓝", xy=(240, val_hi[24]), xytext=(155, 0.89),
                 color=BLUE, fontsize=8.2, arrowprops=dict(arrowstyle="->", color=BLUE, lw=1.1))

    # Panel C: 128-pt ToneCurve
    ax3 = fig.add_subplot(gs[0, 1])
    ax3.set_facecolor(CARD)
    ax3.plot([0, 1], [0, 1], color=MUTED, ls="--", lw=1.2, label="线性基准 (y = x)")
    ax3.plot(tc[:, 0], tc[:, 1], color=CORAL, lw=2.5, label="官方 128 点 ToneCurve")
    ax3.fill_between(tc[:, 0], tc[:, 0], tc[:, 1], color=CORAL, alpha=0.14)
    ax3.set_title("C. 128 点官方哈苏影调曲线 (ToneCurve)", color=TXT, fontsize=11.5, fontweight="bold", pad=8)
    ax3.set_xlabel("输入线性亮度", color=MUTED, fontsize=9)
    ax3.set_ylabel("输出亮度", color=MUTED, fontsize=9)
    ax3.tick_params(colors=MUTED)
    for sp in ax3.spines.values():
        sp.set_color(BORDER)
    ax3.grid(True, color=BORDER, alpha=0.35, lw=0.7)
    ax3.legend(facecolor=CARD, edgecolor=BORDER, labelcolor=TXT, fontsize=8.5, loc="lower right")
    ax3.annotate("中间调通透提亮\n0.50 → 0.75", xy=(0.50, 0.748), xytext=(0.56, 0.48),
                 color=CORAL, fontsize=8.3, arrowprops=dict(arrowstyle="->", color=CORAL, lw=1.1))

    # Panel D: 17x13 Optical Vignette Heatmap
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor(CARD)
    im = ax4.imshow(vig, cmap="inferno", vmin=0.72, vmax=1.0, aspect="auto")
    ax4.set_title("D. 17×13 哈苏光学暗角增益表（独立于 3D LUT）", color=TXT, fontsize=11.5, fontweight="bold", pad=8)
    ax4.set_xlabel("画面水平网格 (17 列)", color=MUTED, fontsize=9)
    ax4.set_ylabel("画面垂直网格 (13 行)", color=MUTED, fontsize=9)
    ax4.tick_params(colors=MUTED)
    cbar = fig.colorbar(im, ax=ax4, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(colors=MUTED, labelsize=8)
    cbar.set_label("亮度增益", color=MUTED, fontsize=8.5)
    ax4.text(8, 6, "中心 1.000", color="#111111", fontsize=9.5, fontweight="bold", ha="center", va="center")
    ax4.text(0.3, 0.8, "四角\n0.742", color=TXT, fontsize=8.2, fontweight="bold", ha="left", va="top")

    fig.savefig(FIG_DIR / "03_hncs_color_science_data.png", dpi=180, facecolor=BG)
    plt.close(fig)


# =============================================================================
# FIGURE 4: BasicTone Master Mode Dual 3x3 Bilinear LUT Engine
# =============================================================================
def fig04_master_mode_engine():
    def load_planar(name):
        raw = np.frombuffer((BT_LMT_DIR / name).read_bytes(), dtype="<f4")
        return raw.reshape(3, 32, 32, 32).transpose(1, 2, 3, 0)

    # Sample color patch (skin, green, sky, midgray) through each 3x3 basis LUT!
    sample_rgb = np.array([
        [0.76, 0.59, 0.51],  # skin
        [0.34, 0.42, 0.26],  # foliage
        [0.38, 0.48, 0.62],  # sky
        [0.50, 0.50, 0.50],  # midgray
    ], dtype=np.float32)

    def eval_patch(lut):
        idx = np.clip((sample_rgb * 31).round().astype(int), 0, 31)
        return np.clip(lut[idx[:, 2], idx[:, 1], idx[:, 0]], 0, 1)

    fig, ax = plt.subplots(figsize=(14, 7.6), dpi=180, facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.03, 0.95, "图 4｜哈苏大师模式 BasicTone 引擎：双 3×3 基底 LUT 双线性合成原理",
            color=TXT, fontsize=15.5, fontweight="bold", va="top")
    ax.text(0.03, 0.905, "实时调节「饱和度/对比度/色温/色调」滑块时，底层并非简单数学公式，而是对 18 张 32³ 浮点基底 LUT 做双线性插值再串联采样",
            color=MUTED, fontsize=10.2, va="top")

    # Left grid: SC32Lut0..8
    ax.text(0.05, 0.835, "第一级：饱和度 (Sat) × 对比度 (Cont) 3×3 基底网", color=AMBER, fontsize=12, fontweight="bold")
    sat_lbls = ["Sat -100\n(黑白)", "Sat 0\n(标准)", "Sat +100\n(高饱和)"]
    cnt_lbls = ["Cont -100 (柔)", "Cont 0 (标准)", "Cont +100 (硬)"]
    gx0, gy0, cw, ch = 0.11, 0.34, 0.105, 0.125

    for c_i, cl in enumerate(cnt_lbls):
        ax.text(gx0 + c_i * (cw + 0.014) + cw / 2, gy0 + 3 * (ch + 0.018) + 0.012, cl,
                color=MUTED, fontsize=8.6, ha="center")
    for r_i, sl in enumerate(sat_lbls):
        ry = gy0 + (2 - r_i) * (ch + 0.018)
        ax.text(gx0 - 0.012, ry + ch / 2, sl, color=MUTED, fontsize=8.6, ha="right", va="center")
        for c_i in range(3):
            idx = r_i * 3 + c_i
            lut = load_planar(f"SC32Lut{idx}")
            cols = eval_patch(lut)
            cx = gx0 + c_i * (cw + 0.014)
            is_center = (idx == 4)
            box = FancyBboxPatch((cx, ry), cw, ch, boxstyle="round,pad=0.004,rounding_size=0.01",
                                 linewidth=2.0 if is_center else 1.1,
                                 edgecolor=GREEN if is_center else BORDER, facecolor=CARD, zorder=2)
            ax.add_patch(box)
            ax.text(cx + cw / 2, ry + ch - 0.012, f"SC32Lut{idx}" + (" (恒等)" if is_center else ""),
                    color=GREEN if is_center else TXT, fontsize=8.0, fontweight="bold", ha="center", va="top", zorder=3)
            # 4 color swatches
            sw = (cw - 0.016) / 4
            for k in range(4):
                rect = patches.Rectangle((cx + 0.008 + k * sw, ry + 0.014), sw - 0.003, ch * 0.56,
                                         facecolor=cols[k], edgecolor="none", zorder=3)
                ax.add_patch(rect)

    # Right grid: CWCM32Lut0..8
    ax.text(0.555, 0.835, "第二级：冷暖色温 (CoWa) × 青品色调 (CyMa) 3×3 基底网", color=CYAN, fontsize=12, fontweight="bold")
    cw_lbls = ["Cool -100\n(极冷)", "Temp 0\n(标准)", "Warm +100\n(极暖)"]
    cm_lbls = ["Cyan -100 (偏青)", "Tint 0 (标准)", "Magenta +100 (偏品)"]
    rx0 = 0.615
    for c_i, cl in enumerate(cm_lbls):
        ax.text(rx0 + c_i * (cw + 0.014) + cw / 2, gy0 + 3 * (ch + 0.018) + 0.012, cl,
                color=MUTED, fontsize=8.4, ha="center")
    for r_i, sl in enumerate(cw_lbls):
        ry = gy0 + (2 - r_i) * (ch + 0.018)
        ax.text(rx0 - 0.012, ry + ch / 2, sl, color=MUTED, fontsize=8.6, ha="right", va="center")
        for c_i in range(3):
            idx = r_i * 3 + c_i
            lut = load_planar(f"CWCM32Lut{idx}")
            cols = eval_patch(lut)
            cx = rx0 + c_i * (cw + 0.014)
            is_center = (idx == 4)
            box = FancyBboxPatch((cx, ry), cw, ch, boxstyle="round,pad=0.004,rounding_size=0.01",
                                 linewidth=2.0 if is_center else 1.1,
                                 edgecolor=GREEN if is_center else BORDER, facecolor=CARD, zorder=2)
            ax.add_patch(box)
            ax.text(cx + cw / 2, ry + ch - 0.012, f"CWCM{idx}" + (" (恒等)" if is_center else ""),
                    color=GREEN if is_center else TXT, fontsize=8.0, fontweight="bold", ha="center", va="top", zorder=3)
            sw = (cw - 0.016) / 4
            for k in range(4):
                rect = patches.Rectangle((cx + 0.008 + k * sw, ry + 0.014), sw - 0.003, ch * 0.56,
                                         facecolor=cols[k], edgecolor="none", zorder=3)
                ax.add_patch(rect)

    # Bottom synthesis pipeline bar
    draw_box(ax, 0.04, 0.06, 0.27, 0.17, "步骤 1：SC 双线性权重融合",
             "按 (Sat, Cont) 落入的象限\n对 4 张相邻 SC32Lut 加权融合\n→ 得到 LUT_SC(Sat, Cont)",
             edge=AMBER, title_size=10.5, body_size=8.8)
    draw_box(ax, 0.365, 0.06, 0.27, 0.17, "步骤 2：CWCM 串联三线性采样",
             "按 (Temp, Tint) 融合 4 张 CWCM\n串联采样：LUT_CWCM(LUT_SC(RGB))\n→ 等效单张 3D LUT（零二次量化）",
             edge=CYAN, title_size=10.5, body_size=8.8)
    draw_box(ax, 0.69, 0.06, 0.27, 0.17, "步骤 3：叠加风格滤镜导出",
             "按强度 α 混合大师/胶片滤镜\n输出单张 33³ 或 64³ 标准 .cube\n(scripts/master_mode_composer.py)",
             edge=GREEN, title_size=10.5, body_size=8.8)

    draw_arrow(ax, (0.28, 0.33), (0.20, 0.235), color=AMBER)
    draw_arrow(ax, (0.78, 0.33), (0.55, 0.235), color=CYAN)
    draw_arrow(ax, (0.315, 0.145), (0.36, 0.145), color=AMBER)
    draw_arrow(ax, (0.64, 0.145), (0.685, 0.145), color=CYAN)

    plt.tight_layout(pad=0.3)
    fig.savefig(FIG_DIR / "04_master_mode_3x3_engine.png", dpi=180, facecolor=BG)
    plt.close(fig)


# =============================================================================
# FIGURE 5: Sony A7C II Porting (1) - CIE 1931 Gamuts + S-Log3 Filmic Roll-off
# =============================================================================
def fig05_a7c2_slog3_gamut():
    fig = plt.figure(figsize=(14.5, 7.2), dpi=180, facecolor=BG)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.15], wspace=0.22, left=0.06, right=0.96, top=0.83, bottom=0.11)

    fig.suptitle("图 5｜索尼 A7C2 移植原理（一）：色域矩阵变换（CIE 1931）与 S-Log3 高光滚降曲线",
                 color=TXT, fontsize=15.5, fontweight="bold", x=0.04, ha="left", y=0.95)
    fig.text(0.04, 0.895, "解决直套手机 Rec.709 LUT 导致“发灰偏色、高光死白”的根本问题：精确对接 Sony 官方 S-Gamut3.Cine 与 S-Log3 数学规范",
             color=MUTED, fontsize=10.2)

    # Panel A: CIE 1931 xy Chromaticity Triangles
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor(CARD)

    # Approximate CIE 1931 spectral locus (380nm..700nm) for clean visual reference
    locus = np.array([
        [0.1741, 0.0050], [0.1738, 0.0049], [0.1714, 0.0051], [0.1669, 0.0061], [0.1566, 0.0177],
        [0.1440, 0.0297], [0.1241, 0.0578], [0.0913, 0.1327], [0.0454, 0.2950], [0.0082, 0.5384],
        [0.0139, 0.7502], [0.0743, 0.8338], [0.1547, 0.8059], [0.2296, 0.7543], [0.3016, 0.6923],
        [0.3731, 0.6245], [0.4441, 0.5547], [0.5125, 0.4866], [0.5752, 0.4242], [0.6270, 0.3725],
        [0.6658, 0.3340], [0.6915, 0.3083], [0.7079, 0.2920], [0.7216, 0.2784], [0.7347, 0.2653],
        [0.1741, 0.0050]
    ])
    ax1.plot(locus[:, 0], locus[:, 1], color=MUTED, lw=1.2, alpha=0.55, label="CIE 1931 人眼可见光谱边界")
    ax1.fill(locus[:, 0], locus[:, 1], color="#232C3C", alpha=0.35)

    def plot_tri(pts, color, label, ls="-", lw=2.2, alpha=0.10):
        arr = np.array(pts + [pts[0]])
        ax1.plot(arr[:, 0], arr[:, 1], color=color, ls=ls, lw=lw, label=label)
        ax1.fill(arr[:, 0], arr[:, 1], color=color, alpha=alpha)

    plot_tri([(0.7347, 0.2653), (0.1596, 0.8404), (0.0366, 0.0001)], PURPLE, "ProPhoto RGB (D50 · 哈苏 HNCS 工作空间)", ls="--", lw=1.8, alpha=0.07)
    plot_tri([(0.766, 0.275), (0.225, 0.800), (0.089, -0.087)], AMBER, "Sony S-Gamut3.Cine (D65 · A7C2 输入)", ls="-", lw=2.4, alpha=0.10)
    plot_tri([(0.640, 0.330), (0.300, 0.600), (0.150, 0.060)], CYAN, "Rec.709 / sRGB (D65 · 最终显示输出)", ls="-", lw=2.2, alpha=0.14)

    ax1.scatter([0.3127], [0.3290], color=CYAN, s=55, zorder=5)
    ax1.scatter([0.3457], [0.3585], color=PURPLE, s=55, zorder=5)
    ax1.text(0.28, 0.28, "D65 白点", color=CYAN, fontsize=8.5, fontweight="bold")
    ax1.text(0.36, 0.37, "D50 白点\n(Bradford 适应)", color=PURPLE, fontsize=8.2)

    ax1.set_xlim(-0.02, 0.82)
    ax1.set_ylim(-0.12, 0.90)
    ax1.set_xlabel("CIE x", color=MUTED, fontsize=9.5)
    ax1.set_ylabel("CIE y", color=MUTED, fontsize=9.5)
    ax1.set_title("A. 三大色域空间转换路径（色域无损衔接）", color=TXT, fontsize=11.5, fontweight="bold", pad=8)
    ax1.tick_params(colors=MUTED)
    for sp in ax1.spines.values():
        sp.set_color(BORDER)
    ax1.grid(True, color=BORDER, alpha=0.35, lw=0.7)
    ax1.legend(facecolor=CARD, edgecolor=BORDER, labelcolor=TXT, fontsize=8.3, loc="upper right")

    # Panel B: S-Log3 Transfer & Filmic Highlight Roll-off Curve
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor(CARD)

    ev = np.linspace(-5.0, 6.5, 400)
    lin_l = 0.18 * (2.0 ** ev)

    # S-Log3 encoded
    cut = 0.01125
    slog3 = np.where(lin_l >= cut, (420.0 + np.log10((lin_l + 0.01) / 0.19) * 261.5) / 1023.0,
                     (lin_l * (171.2102946929 - 95.0) / cut + 95.0) / 1023.0)

    # Naive linear clip -> sRGB OETF
    def srgb_oetf(x):
        x = np.clip(x, 0.0, 1.0)
        return np.where(x <= 0.0031308, x * 12.92, 1.055 * (x ** (1.0 / 2.4)) - 0.055)
    naive_rec709 = srgb_oetf(lin_l)

    # Our filmic highlight roll-off -> sRGB OETF (matching port_to_sony_a7c2.py)
    s, W = 0.82, 16.0
    l_toe = np.where(lin_l < 0.18, 0.18 * ((lin_l / 0.18) ** 1.08), lin_l)
    mapped = np.clip((l_toe * (W + s)) / (W * (l_toe + s)), 0.0, 1.0)
    ours_rec709 = srgb_oetf(mapped)

    ax2.axvline(0.0, color=BORDER, ls=":", lw=1.3)
    ax2.plot(ev, slog3, color=MUTED, ls="--", lw=2.0, label="A7C2 原始 S-Log3 灰片信号")
    ax2.plot(ev, naive_rec709, color=CORAL, ls=":", lw=2.0, label="直接线性截断 Rec.709（+2.5 档即死白）")
    ax2.plot(ev, ours_rec709, color=GREEN, lw=2.8, label="本方案电影级高光滚降 + 哈苏 HNCS 输出")

    # Key anchor annotations
    mg_idx = np.argmin(np.abs(ev - 0.0))
    ax2.scatter([0.0, 0.0], [slog3[mg_idx], ours_rec709[mg_idx]], color=[MUTED, GREEN], s=50, zorder=5)
    ax2.annotate("18% 中灰锚点\nS-Log3 41.1% → Rec.709 47.0%",
                 xy=(0.0, ours_rec709[mg_idx]), xytext=(-4.6, 0.62),
                 color=GREEN, fontsize=8.6, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.2))
    ax2.annotate("平滑压缩 +6 档高光\n保留天空与高光层次",
                 xy=(4.0, ours_rec709[np.argmin(np.abs(ev - 4.0))]), xytext=(2.8, 0.47),
                 color=AMBER, fontsize=8.5,
                 arrowprops=dict(arrowstyle="->", color=AMBER, lw=1.2))
    ax2.annotate("死白硬截断!", xy=(2.5, 1.0), xytext=(0.4, 0.90),
                 color=CORAL, fontsize=8.3, arrowprops=dict(arrowstyle="->", color=CORAL, lw=1.1))

    ax2.set_xlim(-5.0, 6.5)
    ax2.set_ylim(-0.02, 1.06)
    ax2.set_xlabel("相对 18% 中灰的曝光档位（EV Stops）", color=MUTED, fontsize=9.5)
    ax2.set_ylabel("归一化视频信号电平（0.0 ~ 1.0）", color=MUTED, fontsize=9.5)
    ax2.set_title("B. S-Log3 动态范围映射：平滑高光肩部 vs 暴力截断", color=TXT, fontsize=11.5, fontweight="bold", pad=8)
    ax2.tick_params(colors=MUTED)
    for sp in ax2.spines.values():
        sp.set_color(BORDER)
    ax2.grid(True, color=BORDER, alpha=0.35, lw=0.7)
    ax2.legend(facecolor=CARD, edgecolor=BORDER, labelcolor=TXT, fontsize=8.4, loc="lower right")

    fig.savefig(FIG_DIR / "05_a7c2_gamut_and_slog3_rolloff.png", dpi=180, facecolor=BG)
    plt.close(fig)


# =============================================================================
# FIGURE 6: Sony A7C II Porting (2) - RAW .dcp Sensor Decoupling & Dual Workflow
# =============================================================================
def fig06_a7c2_dcp_decoupling():
    fig, ax = plt.subplots(figsize=(14, 7.6), dpi=180, facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.03, 0.95, "图 6｜索尼 A7C2 移植原理（二）：RAW .dcp 传感器解耦与视频/照片双端落地",
            color=TXT, fontsize=15.5, fontweight="bold", va="top")
    ax.text(0.03, 0.905, "核心思想：把「传感器固有偏色」与「哈苏自然色彩科学」彻底解耦，实现跨品牌硬件的数学级精准移植",
            color=MUTED, fontsize=10.2, va="top")

    # Top: Why direct porting fails vs Decoupled Architecture
    # Wrong path
    draw_box(ax, 0.03, 0.72, 0.94, 0.14, "[× 错误做法] 直接把手机 DNG 的 ColorMatrix 套给索尼 A7C2 RAW",
             "手机传感器矩阵（主摄 CMOS） ≠ 索尼 A7C2 3300万像素 Exmor R 传感器光谱响应 → 画面严重偏色、白平衡失真",
             edge=CORAL, fill="#24161B", title_size=11, body_size=9.2)

    # Right decoupled path (RAW .dcp)
    dcp_bg = FancyBboxPatch((0.03, 0.34), 0.94, 0.33, boxstyle="round,pad=0.012,rounding_size=0.018",
                            linewidth=1.8, edgecolor=GREEN, facecolor="#131C1B", linestyle="--", zorder=1)
    ax.add_patch(dcp_bg)
    ax.text(0.048, 0.652, "[√ 正确做法] Adobe DNG 架构解耦 → 合成索尼 A7C2 专属 .dcp（Lightroom / ACR 无损解 14-bit .ARW）",
            color=GREEN, fontsize=11.8, fontweight="bold", va="top")

    draw_box(ax, 0.048, 0.375, 0.19, 0.22, "A7C2 RAW\n(.ARW 14-bit)",
             "索尼 ILCE-7CM2\n原始线性传感器数据\n完整保留 14-bit 宽容度",
             edge=BLUE, title_size=10.5, body_size=8.6)
    draw_box(ax, 0.28, 0.375, 0.22, 0.22, "设备相关层（已替换）\nILCE-7CM2 ColorMatrix",
             "采用 LibRaw / Adobe 标定\n索尼 A7C2 专属 D65 矩阵\n将传感器 RGB 精准归零至\n标准 CIE XYZ (D50)",
             edge=CYAN, title_size=10.2, body_size=8.4)
    draw_box(ax, 0.542, 0.375, 0.22, 0.22, "设备无关层（完整移植）\n哈苏标准 HNCS 核心",
             "在统一 ProPhoto D50 空间\n施加 36×20×20 HueSatMap\n+ 128 点官方 ToneCurve\n跨机型色彩表现高度一致",
             edge=AMBER, title_size=10.2, body_size=8.4)
    draw_box(ax, 0.802, 0.375, 0.15, 0.22, "Lightroom /\nACR 成片",
             "识别 ILCE-7CM2\n配置文件一键直选\n支持全自动白平衡",
             edge=GREEN, title_size=10.5, body_size=8.5)

    draw_arrow(ax, (0.242, 0.485), (0.275, 0.485), color=BLUE)
    draw_arrow(ax, (0.505, 0.485), (0.537, 0.485), color=CYAN)
    draw_arrow(ax, (0.767, 0.485), (0.797, 0.485), color=AMBER)

    # Bottom: 3 Delivery Channels on A7C2
    draw_box(ax, 0.03, 0.05, 0.295, 0.23, "交付通道 1｜视频机内直出/监看",
             "• 16 款 33³ ASCII .cube（4 MB）\n• 拷入 SD 卡 /PRIVATE/SONY/PRO/LUT/\n• 12 款 S-Log3/SGamut3.Cine 专用\n• 4 款 Rec.709 直套备用\n• 支持 Log 实时监看与 PPLUT 烘焙",
             edge=BLUE, title_size=11, body_size=8.8)
    draw_box(ax, 0.352, 0.05, 0.295, 0.23, "交付通道 2｜拍照 RAW 无损解片",
             "• Sony_A7C2_Hasselblad_Standard_HNCS.dcp\n• 另附平曲线版（自由控对比度）\n• 拷贝到 Adobe CameraProfiles 目录\n• Lightroom / PS 直接打开 .ARW 选用\n• 照片端色彩还原天花板方案",
             edge=GREEN, title_size=11, body_size=8.8)
    draw_box(ax, 0.675, 0.05, 0.295, 0.23, "交付通道 3｜JPEG 批量套色工具",
             "• apply_a7c2_photo_batch.py\n• 支持任意 .cube 滤镜 + 强度调节\n• 可选叠加 17×13 哈苏光学暗角表\n• 完整保留原图 EXIF 与 ICC 信息\n• 适合快速批量出片与对比测试",
             edge=PURPLE, title_size=11, body_size=8.8)

    plt.tight_layout(pad=0.3)
    fig.savefig(FIG_DIR / "06_a7c2_dcp_sensor_decoupling.png", dpi=180, facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    fig01_pipeline()
    fig02_binary_formats()
    fig03_hncs_data()
    fig04_master_mode_engine()
    fig05_a7c2_slog3_gamut()
    fig06_a7c2_dcp_decoupling()
    for p in sorted(FIG_DIR.glob("*.png")):
        print(f"Generated {p.name} ({p.stat().st_size // 1024} KB)")
