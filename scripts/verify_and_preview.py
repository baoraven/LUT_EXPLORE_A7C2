"""
Verify all exported .cube LUTs and generate a visual comparison contact sheet
using a synthetic 24-patch ColorChecker + gradient/skin/sky/foliage test image.
"""

import json
import pathlib
import numpy as np
from PIL import Image, ImageDraw
from scipy.interpolate import RegularGridInterpolator

OUT_ROOT = pathlib.Path("D:/AI_LUT/output")
LUT_ROOT = OUT_ROOT / "luts"
PREVIEW_DIR = OUT_ROOT / "previews"


def parse_cube(path: pathlib.Path) -> tuple[int, np.ndarray]:
    N = None
    vals = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(("TITLE", "DOMAIN_")):
            continue
        if s.startswith("LUT_3D_SIZE"):
            N = int(s.split()[1])
        else:
            parts = s.split()
            if len(parts) >= 3:
                vals.append((float(parts[0]), float(parts[1]), float(parts[2])))
    assert N is not None, f"Missing LUT_3D_SIZE in {path}"
    assert len(vals) == N ** 3, f"Expected {N**3} entries, got {len(vals)} in {path}"
    arr = np.array(vals, dtype=np.float32).reshape(N, N, N, 3)
    assert not np.isnan(arr).any() and not np.isinf(arr).any(), f"NaN/Inf in {path}"
    assert arr.min() >= -1e-4 and arr.max() <= 1.0001, f"Out-of-range [{arr.min()}, {arr.max()}] in {path}"
    return N, arr


def build_test_chart(w=360, h=240) -> np.ndarray:
    """Create a rich sRGB test image: Macbeth ColorChecker 24 patches + smooth hue/luma ramp."""
    img = np.zeros((h, w, 3), dtype=np.float32)

    # Top 1/3: Smooth hue rainbow + luminance gradient (great for detecting axis swaps or banding)
    top_h = 72
    x = np.linspace(0, 1, w, dtype=np.float32)
    y = np.linspace(0, 1, top_h, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    # HSV to RGB
    h6 = xx * 6.0
    c = np.where(yy < 0.5, yy * 2.0, 1.0)
    v = np.where(yy < 0.5, 0.2 + 0.8 * (yy * 2.0), 1.0 - 0.5 * ((yy - 0.5) * 2.0))
    # Simpler clean HSV: S=0.85, V varies top-to-bottom 0.25..1.0
    sat = 0.85
    val = 0.25 + 0.75 * (1.0 - yy)
    c = val * sat
    x_hsv = c * (1.0 - np.abs((h6 % 2.0) - 1.0))
    m = val - c
    r = np.select([h6 < 1, h6 < 2, h6 < 3, h6 < 4, h6 < 5], [c, x_hsv, 0, 0, x_hsv], default=c) + m
    g = np.select([h6 < 1, h6 < 2, h6 < 3, h6 < 4, h6 < 5], [x_hsv, c, c, x_hsv, 0], default=0) + m
    b = np.select([h6 < 1, h6 < 2, h6 < 3, h6 < 4, h6 < 5], [0, 0, x_hsv, c, c], default=x_hsv) + m
    img[:top_h] = np.stack([r, g, b], axis=-1)

    # Bottom 2/3: Macbeth 24-patch ColorChecker (sRGB approximate reference values)
    patches = [
        # Row 1: natural tones (dark skin, light skin, blue sky, foliage, blue flower, bluish green)
        (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
        # Row 2: chromatic
        (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
        # Row 3: primaries & secondaries
        (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
        # Row 4: grayscale ramp
        (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
    ]
    grid_y0 = top_h + 6
    cell_h = (h - grid_y0 - 6) // 4
    cell_w = (w - 12) // 6
    img[top_h:] = 0.12  # dark neutral bezel
    for idx, rgb in enumerate(patches):
        row, col = divmod(idx, 6)
        y0 = grid_y0 + row * cell_h + 2
        x0 = 6 + col * cell_w + 2
        img[y0 : y0 + cell_h - 4, x0 : x0 + cell_w - 4] = np.array(rgb, dtype=np.float32) / 255.0

    return img


def apply_cube_to_image(img_rgb: np.ndarray, lut_bgr_rgb: np.ndarray) -> np.ndarray:
    N = lut_bgr_rgb.shape[0]
    g = np.linspace(0.0, 1.0, N, dtype=np.float32)
    interp = RegularGridInterpolator((g, g, g), lut_bgr_rgb, method="linear", bounds_error=False, fill_value=None)
    pts_bgr = np.clip(img_rgb, 0.0, 1.0)[..., [2, 1, 0]]
    return np.clip(interp(pts_bgr), 0.0, 1.0)


def main():
    all_cubes = sorted(LUT_ROOT.rglob("*.cube"))
    print(f"Verifying {len(all_cubes)} exported .cube files...")

    errors = []
    stats = []
    for p in all_cubes:
        try:
            N, arr = parse_cube(p)
            mid = N // 2
            # Basic sanity metrics
            blk = arr[0, 0, 0].tolist()
            wht = arr[-1, -1, -1].tolist()
            gray = arr[mid, mid, mid].tolist()
            # Check R/G/B axis sanity (skip monochrome/B&W LUTs)
            r_corner = arr[0, 0, -1]
            b_corner = arr[-1, 0, 0]
            stats.append({
                "file": str(p.relative_to(LUT_ROOT)).replace("\\", "/"),
                "size": N,
                "black": [round(x, 3) for x in blk],
                "midgray": [round(x, 3) for x in gray],
                "white": [round(x, 3) for x in wht],
                "r_corner": [round(float(x), 3) for x in r_corner],
                "b_corner": [round(float(x), 3) for x in b_corner],
            })
        except Exception as e:
            errors.append((str(p), str(e)))

    print(f"Verification complete: {len(all_cubes) - len(errors)}/{len(all_cubes)} passed, {len(errors)} errors.")
    for path_s, err in errors:
        print(f"  ERROR: {path_s}: {err}")

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "lut_verification_report.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build visual comparison contact sheet for flagship Hasselblad & Film LUTs
    showcase = [
        ("Original (Identity)", None),
        ("Hasselblad Serenity", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Serenity_童话_32.cube"),
        ("Hasselblad Radiance", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Radiance_人像_32.cube"),
        ("Hasselblad Emerald", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Emerald_风光_32.cube"),
        ("Hasselblad XPan Delta400", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_XPan_Delta400_黑白_32.cube"),
        ("Hasselblad Sarek III", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Nordic_Sarek_III_16.cube"),
        ("Hasselblad Vaeroy III", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Nordic_Vaeroy_III_16.cube"),
        ("Hasselblad Yllas", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Nordic_Yllas_16.cube"),
        ("Film Fuji NC", LUT_ROOT / "02_Film_Simulation/Film_Fuji_NC_复古_17.cube"),
        ("Film Fuji CC", LUT_ROOT / "02_Film_Simulation/Film_Fuji_CC_通透_17.cube"),
        ("Film Fuji NH (ProNegHi)", LUT_ROOT / "02_Film_Simulation/Film_Fuji_NH_ProNegHi_清新_17.cube"),
        ("Master Tone of Light", LUT_ROOT / "01_Hasselblad_Master_Filters/Hasselblad_Master_ToneOfLight_光影_32.cube"),
    ]

    chart = build_test_chart(360, 220)
    cols = 4
    rows = (len(showcase) + cols - 1) // cols
    pad = 16
    label_h = 26
    tw, th = 360, 220
    canvas = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)

    for idx, (label, lut_path) in enumerate(showcase):
        r, c = divmod(idx, cols)
        x0 = pad + c * (tw + pad)
        y0 = pad + r * (th + label_h + pad)
        if lut_path is None:
            rendered = chart
        else:
            _, arr = parse_cube(lut_path)
            rendered = apply_cube_to_image(chart, arr)
        tile = Image.fromarray((rendered * 255.0).round().astype(np.uint8))
        canvas.paste(tile, (x0, y0 + label_h))
        draw.text((x0 + 4, y0 + 5), label, fill=(235, 235, 240))

    sheet_path = PREVIEW_DIR / "hasselblad_lut_comparison.png"
    canvas.save(sheet_path)
    print(f"Saved visual comparison sheet: {sheet_path}")


if __name__ == "__main__":
    main()
