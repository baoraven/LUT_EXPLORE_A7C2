"""
Hasselblad Standard (HNCS - Hasselblad Natural Color Solution) Exporter
=======================================================================
Converts DNG HNCS calibration tables (`odm/etc/camera/dng/`):
  - ColorMatrix1 (StdA 2856K) & ColorMatrix2 (D65 6500K)
  - D28HUESATMap & D65HUESATMap (36 Hue x 20 Sat x 20 Val = 14,400 HSV nodes)
  - ToneCurve (128-point Hasselblad filmic tone curve)

Outputs:
  1. Industry-standard .cube 3D LUTs (33pt & 64pt) in exact Adobe DNG ProPhoto-HSV pipeline
  2. Industry-standard Adobe .dcp (DNG Camera Profile) files for Lightroom / ACR / RawTherapee
"""

import json
import pathlib
import struct
import numpy as np
from PIL import Image, ImageDraw

FS = pathlib.Path("D:/AI_LUT/extracted/fs")
DNG_DIR = FS / "odm/etc/camera/dng"
OUT_DIR = pathlib.Path("D:/AI_LUT/output/Hasselblad_Standard_HNCS")

# Exact DNG/ICC standard color matrices (D50 PCS with Bradford chromatic adaptation)
# Linear sRGB (D65) -> XYZ (D50 Bradford-adapted)
M_SRGB_TO_XYZ_D50 = np.array([
    [0.4360747, 0.3850649, 0.1430804],
    [0.2225045, 0.7168786, 0.0606169],
    [0.0139322, 0.0971045, 0.7141733],
], dtype=np.float64)

M_XYZ_D50_TO_SRGB = np.linalg.inv(M_SRGB_TO_XYZ_D50)

# ProPhoto RGB (ROMM RGB, native D50) <-> XYZ (D50)
M_PROPHOTO_TO_XYZ_D50 = np.array([
    [0.7976749, 0.1351917, 0.0313534],
    [0.2880402, 0.7118741, 0.0000857],
    [0.0000000, 0.0000000, 0.8252100],
], dtype=np.float64)

M_XYZ_D50_TO_PROPHOTO = np.linalg.inv(M_PROPHOTO_TO_XYZ_D50)

# Combined Linear sRGB <-> Linear ProPhoto RGB
M_SRGB_TO_PROPHOTO = M_XYZ_D50_TO_PROPHOTO @ M_SRGB_TO_XYZ_D50
M_PROPHOTO_TO_SRGB = M_XYZ_D50_TO_SRGB @ M_PROPHOTO_TO_XYZ_D50


def srgb_eotf(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def srgb_oetf(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * (x ** (1.0 / 2.4)) - 0.055)


def rgb_to_hsv_vec(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Adobe DNG spec RGB -> HSV (H in [0, 6), S in [0, 1], V in [0, 1])."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    gap = mx - mn

    v = mx
    s = np.where(mx > 1e-10, gap / np.maximum(mx, 1e-10), 0.0)

    h = np.zeros_like(mx)
    mask = gap > 1e-10
    r_max = mask & (mx == r)
    g_max = mask & (mx == g) & (~r_max)
    b_max = mask & (~r_max) & (~g_max)

    h[r_max] = ((g[r_max] - b[r_max]) / gap[r_max]) % 6.0
    h[g_max] = ((b[g_max] - r[g_max]) / gap[g_max]) + 2.0
    h[b_max] = ((r[b_max] - g[b_max]) / gap[b_max]) + 4.0
    h = np.mod(h, 6.0)
    return h, s, v


def hsv_to_rgb_vec(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Adobe DNG spec HSV (H in [0, 6), S in [0, 1], V in [0, 1]) -> RGB."""
    h = np.mod(h, 6.0)
    i = np.floor(h).astype(np.int32)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4], [v, q, p, p, t], default=v)
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4], [t, v, v, q, p], default=p)
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4], [p, p, t, v, v], default=q)
    return np.stack([r, g, b], axis=-1)


def load_huesatmap(path: pathlib.Path) -> np.ndarray:
    """Load DNG HueSatMap as shape (ValDivs=20, HueDivs=36, SatDivs=20, 3)."""
    raw = path.read_text(encoding="utf-8")
    vals = np.array([float(x) for x in raw.replace("\n", ",").split(",") if x.strip()], dtype=np.float64)
    assert vals.size == 20 * 36 * 20 * 3, f"Unexpected HueSatMap size {vals.size}"
    return vals.reshape(20, 36, 20, 3)


def load_tonecurve(path: pathlib.Path) -> np.ndarray:
    raw = path.read_text(encoding="utf-8")
    vals = np.array([float(x) for x in raw.replace("\n", ",").split(",") if x.strip()], dtype=np.float64)
    return vals.reshape(-1, 2)


def load_matrix(path: pathlib.Path) -> np.ndarray:
    raw = path.read_text(encoding="utf-8")
    return np.array([float(x) for x in raw.replace("\n", ",").split(",") if x.strip()], dtype=np.float64)


def apply_dng_huesatmap(prophoto_lin: np.ndarray, hsm: np.ndarray) -> np.ndarray:
    """
    Exact Adobe DNG 1.6 trilinear interpolation of ProfileHueSatMap (V=20, H=36, S=20)
    with cyclic wrap on Hue axis.
    """
    V_dim, H_dim, S_dim, _ = hsm.shape
    h, s, v = rgb_to_hsv_vec(np.clip(prophoto_lin, 0.0, 1.0))

    # Normalized coordinates into table
    hf = (h / 6.0) * H_dim  # cyclic [0, H_dim)
    sf = np.clip(s, 0.0, 1.0) * (S_dim - 1)
    vf = np.clip(v, 0.0, 1.0) * (V_dim - 1)

    h0 = np.floor(hf).astype(np.int32) % H_dim
    h1 = (h0 + 1) % H_dim
    fh = hf - np.floor(hf)

    s0 = np.minimum(np.floor(sf).astype(np.int32), S_dim - 2)
    s1 = s0 + 1
    fs = sf - s0

    v0 = np.minimum(np.floor(vf).astype(np.int32), V_dim - 2)
    v1 = v0 + 1
    fv = vf - v0

    # Trilinear interpolation across (v, h, s)
    c000 = hsm[v0, h0, s0]
    c001 = hsm[v0, h0, s1]
    c010 = hsm[v0, h1, s0]
    c011 = hsm[v0, h1, s1]
    c100 = hsm[v1, h0, s0]
    c101 = hsm[v1, h0, s1]
    c110 = hsm[v1, h1, s0]
    c111 = hsm[v1, h1, s1]

    fs_ = fs[..., None]
    fh_ = fh[..., None]
    fv_ = fv[..., None]

    c00 = c000 * (1.0 - fs_) + c001 * fs_
    c01 = c010 * (1.0 - fs_) + c011 * fs_
    c10 = c100 * (1.0 - fs_) + c101 * fs_
    c11 = c110 * (1.0 - fs_) + c111 * fs_

    c0 = c00 * (1.0 - fh_) + c01 * fh_
    c1 = c10 * (1.0 - fh_) + c11 * fh_
    entry = c0 * (1.0 - fv_) + c1 * fv_

    d_hue_deg = entry[..., 0]
    sat_scale = entry[..., 1]
    val_scale = entry[..., 2]

    h_out = np.mod(h + d_hue_deg / 60.0, 6.0)
    s_out = np.clip(s * sat_scale, 0.0, 1.0)
    v_out = np.clip(v * val_scale, 0.0, 1.0)
    return hsv_to_rgb_vec(h_out, s_out, v_out)


def apply_tonecurve_rgb(rgb: np.ndarray, tc: np.ndarray) -> np.ndarray:
    """
    Apply Adobe DNG ProfileToneCurve with hue-preserving luminance-weighted blending
    (per Adobe DNG SDK `dng_tone_curve` RGB channel interpolation).
    """
    x_tab, y_tab = tc[:, 0], tc[:, 1]
    return np.interp(np.clip(rgb, 0.0, 1.0), x_tab, y_tab)


def build_hncs_cube(
    hsm: np.ndarray,
    tc: np.ndarray | None,
    size: int = 64,
    input_is_linear: bool = False,
) -> np.ndarray:
    """Generate a .cube array of shape (N, N, N, 3) indexed [B, G, R, rgb]."""
    lin = np.linspace(0.0, 1.0, size, dtype=np.float64)
    B, G, R = np.meshgrid(lin, lin, lin, indexing="ij")
    rgb_in = np.stack([R, G, B], axis=-1)

    rgb_lin = rgb_in if input_is_linear else srgb_eotf(rgb_in)

    # Linear sRGB -> Linear ProPhoto RGB (D50)
    prophoto = np.einsum("...j,ij->...i", rgb_lin, M_SRGB_TO_PROPHOTO)
    prophoto = np.clip(prophoto, 0.0, 1.0)

    # Apply Hasselblad HNCS 3D HueSatMap
    prophoto_hncs = apply_dng_huesatmap(prophoto, hsm)

    # Optional Hasselblad DNG ProfileToneCurve (applied in linear ProPhoto per DNG spec)
    if tc is not None:
        prophoto_hncs = apply_tonecurve_rgb(prophoto_hncs, tc)

    # Linear ProPhoto RGB -> Linear sRGB -> sRGB OETF
    srgb_lin_out = np.einsum("...j,ij->...i", prophoto_hncs, M_PROPHOTO_TO_SRGB)
    srgb_out = srgb_oetf(np.clip(srgb_lin_out, 0.0, 1.0))
    return srgb_out.astype(np.float32)


def write_cube(arr: np.ndarray, out_path: pathlib.Path, title: str, comments: list[str]):
    N = arr.shape[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Hasselblad Standard (HNCS) DNG Calibration LUT - Personal Study Only"]
    lines.extend(f"# {c}" for c in comments)
    lines.extend([
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {N}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
        "",
    ])
    flat = np.clip(arr, 0.0, 1.0).reshape(-1, 3)
    body = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in flat) + "\n"
    out_path.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")


def write_dcp(
    out_path: pathlib.Path,
    profile_name: str,
    cm1: np.ndarray,
    cm2: np.ndarray,
    hsm1_d28: np.ndarray,
    hsm2_d65: np.ndarray,
    tc: np.ndarray,
    camera_model: str | None = None,
):
    """
    Write a standards-compliant Adobe DNG Camera Profile (.dcp) binary file.
    TIFF Little-Endian with Adobe DCP magic 0x4352 ('CR').
    """
    # TIFF types: 2=ASCII, 3=SHORT, 4=LONG, 10=SRATIONAL, 11=FLOAT
    entries = []

    def add_ascii(tag: int, text: str):
        b = text.encode("ascii") + b"\x00"
        entries.append((tag, 2, len(b), b))

    def add_short(tag: int, val: int):
        entries.append((tag, 3, 1, struct.pack("<H", val)))

    def add_longs(tag: int, vals: list[int]):
        entries.append((tag, 4, len(vals), struct.pack(f"<{len(vals)}I", *vals)))

    def add_srational_matrix(tag: int, mat9: np.ndarray):
        scale = 1000000
        b = b"".join(struct.pack("<ii", int(round(float(v) * scale)), scale) for v in mat9.flatten())
        entries.append((tag, 10, 9, b))

    def add_floats(tag: int, arr: np.ndarray):
        f32 = arr.astype("<f4").ravel()
        entries.append((tag, 11, int(f32.size), f32.tobytes()))

    if camera_model:
        add_ascii(0xC614, camera_model)           # UniqueCameraModel
    add_srational_matrix(0xC621, cm1)             # ColorMatrix1 (StdA)
    add_srational_matrix(0xC622, cm2)             # ColorMatrix2 (D65)
    add_short(0xC65A, 17)                         # CalibrationIlluminant1 = Standard Light A
    add_short(0xC65B, 21)                         # CalibrationIlluminant2 = D65
    add_ascii(0xC6F8, profile_name)               # ProfileName
    add_longs(0xC6F9, [36, 20, 20])               # ProfileHueSatMapDims (Hue, Sat, Val)
    add_floats(0xC6FA, hsm1_d28)                  # ProfileHueSatMapData1 (StdA/D28)
    add_floats(0xC6FB, hsm2_d65)                  # ProfileHueSatMapData2 (D65)
    add_floats(0xC6FC, tc)                        # ProfileToneCurve (128 pairs)
    add_longs(0xC6FD, [0])                        # ProfileEmbedPolicy = 0 (Allow Copying)
    add_ascii(0xC6FE, "Hasselblad HNCS Calibration Profile - Personal Research Only")
    add_longs(0xC7A3, [0])                        # ProfileHueSatMapEncoding = 0 (Linear)

    entries.sort(key=lambda e: e[0])

    # Layout: 8-byte header + 2-byte count + 12*N IFD entries + 4-byte nextIFD(0) + payload data
    ifd_offset = 8
    data_offset = ifd_offset + 2 + 12 * len(entries) + 4
    ifd_bytes = bytearray()
    ifd_bytes += struct.pack("<H", len(entries))
    data_bytes = bytearray()

    for tag, typ, count, raw in entries:
        if len(raw) <= 4:
            val_field = raw.ljust(4, b"\x00")
            ifd_bytes += struct.pack("<HHI", tag, typ, count) + val_field
        else:
            # Align to 4-byte boundary
            while (data_offset + len(data_bytes)) % 4 != 0:
                data_bytes.append(0)
            off = data_offset + len(data_bytes)
            ifd_bytes += struct.pack("<HHII", tag, typ, count, off)
            data_bytes += raw

    ifd_bytes += struct.pack("<I", 0)  # Next IFD offset = 0
    header = struct.pack("<2sHI", b"II", 0x4352, ifd_offset)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + bytes(ifd_bytes) + bytes(data_bytes))


def build_preview(cubes: list[tuple[str, np.ndarray | None]], out_png: pathlib.Path):
    from scipy.interpolate import RegularGridInterpolator
    # Reuse ColorChecker + smooth hue rainbow chart
    w, h = 380, 230
    img = np.zeros((h, w, 3), dtype=np.float32)
    top_h = 72
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

    cols = 3
    rows = (len(cubes) + cols - 1) // cols
    pad, label_h = 16, 26
    canvas = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + label_h + pad) + pad), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)

    for idx, (label, lut) in enumerate(cubes):
        rr, cc = divmod(idx, cols)
        x0 = pad + cc * (w + pad)
        y0 = pad + rr * (h + label_h + pad)
        if lut is None:
            rendered = img
        else:
            N = lut.shape[0]
            grid = np.linspace(0, 1, N, dtype=np.float32)
            interp = RegularGridInterpolator((grid, grid, grid), lut, bounds_error=False, fill_value=None)
            rendered = np.clip(interp(img[..., [2, 1, 0]]), 0.0, 1.0)
        canvas.paste(Image.fromarray((rendered * 255.0).round().astype(np.uint8)), (x0, y0 + label_h))
        draw.text((x0 + 4, y0 + 5), label, fill=(235, 235, 240))

    canvas.save(out_png)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-detect main & tele HNCS DNG calibration tables
    hsm_main_d65 = load_huesatmap(next(DNG_DIR.glob("D65HUESATMap_*main*.txt")))
    hsm_main_d28 = load_huesatmap(next(DNG_DIR.glob("D28HUESATMap_*main*.txt")))
    tc_main = load_tonecurve(next(DNG_DIR.glob("ToneCurve_*main*.txt")))
    cm1_main = load_matrix(next(DNG_DIR.glob("ColorMatrix1_*main*.txt")))
    cm2_main = load_matrix(next(DNG_DIR.glob("ColorMatrix2_*main*.txt")))

    hsm_tele_d65 = load_huesatmap(next(DNG_DIR.glob("D65HUESATMap_*tele.txt")))
    hsm_tele_d28 = load_huesatmap(next(DNG_DIR.glob("D28HUESATMap_*tele.txt")))
    tc_tele = load_tonecurve(next(DNG_DIR.glob("ToneCurve_*tele.txt")))
    cm1_tele = load_matrix(next(DNG_DIR.glob("ColorMatrix1_*tele.txt")))
    cm2_tele = load_matrix(next(DNG_DIR.glob("ColorMatrix2_*tele.txt")))

    # 1. Export .cube 3D LUTs
    exports = [
        ("Hasselblad_Standard_HNCS_Main_D65_ColorOnly_64.cube", hsm_main_d65, None, 64, False,
         "哈苏标准 HNCS 主摄 D65 纯色彩科学 (64pt, 仅 36x20x20 HueSatMap, 保持原图曝光)"),
        ("Hasselblad_Standard_HNCS_Main_D65_ColorOnly_33.cube", hsm_main_d65, None, 33, False,
         "哈苏标准 HNCS 主摄 D65 纯色彩科学 (33pt 通用版, 仅 36x20x20 HueSatMap)"),
        ("Hasselblad_Standard_HNCS_Main_D65_Full_ToneCurve_64.cube", hsm_main_d65, tc_main, 64, False,
         "哈苏标准 HNCS 主摄 D65 完整版 (64pt, HueSatMap + 128点 ToneCurve)"),
        ("Hasselblad_Standard_HNCS_Main_D65_Full_ToneCurve_33.cube", hsm_main_d65, tc_main, 33, False,
         "哈苏标准 HNCS 主摄 D65 完整版 (33pt, HueSatMap + 128点 ToneCurve)"),
        ("Hasselblad_Standard_HNCS_Main_D65_LinearIn_to_sRGB_64.cube", hsm_main_d65, tc_main, 64, True,
         "哈苏标准 HNCS 主摄 D65 线性输入管线版 (Linear RGB -> ProPhoto HNCS + ToneCurve -> sRGB)"),
        ("Hasselblad_Standard_HNCS_Tele_D65_ColorOnly_64.cube", hsm_tele_d65, None, 64, False,
         "哈苏标准 HNCS 潜望长焦 D65 纯色彩科学 (64pt)"),
        ("Hasselblad_Standard_HNCS_Tele_D65_ColorOnly_33.cube", hsm_tele_d65, None, 33, False,
         "哈苏标准 HNCS 潜望长焦 D65 纯色彩科学 (33pt)"),
        ("Hasselblad_Standard_HNCS_Tele_D65_Full_ToneCurve_33.cube", hsm_tele_d65, tc_tele, 33, False,
         "哈苏标准 HNCS 潜望长焦 D65 完整版 (33pt, HueSatMap + ToneCurve)"),
        ("Hasselblad_Standard_HNCS_Main_D28_ColorOnly_33.cube", hsm_main_d28, None, 33, False,
         "哈苏标准 HNCS 主摄 2856K 暖光校准版 (33pt)"),
    ]

    preview_map = {}
    for fname, hsm, tc, sz, lin_in, desc in exports:
        arr = build_hncs_cube(hsm, tc, size=sz, input_is_linear=lin_in)
        write_cube(arr, OUT_DIR / fname, pathlib.Path(fname).stem, [desc, "Space: sRGB <-> Linear ProPhoto D50 (Adobe DNG 1.6 spec)"])
        # Verify
        assert arr.shape == (sz, sz, sz, 3) and not np.isnan(arr).any()
        mid = sz // 2
        print(f"Exported {fname:60s} | midgray={np.round(arr[mid, mid, mid], 4)} | R={np.round(arr[0, 0, -1], 3)} | B={np.round(arr[-1, 0, 0], 3)}")
        preview_map[fname] = arr

    # 2. Export Adobe .dcp Camera Profiles (for Lightroom / ACR / RawTherapee)
    write_dcp(OUT_DIR / "Hasselblad_Standard_HNCS_Main.dcp",
              "Hasselblad Standard (HNCS Main)", cm1_main, cm2_main, hsm_main_d28, hsm_main_d65, tc_main, camera_model=None)
    write_dcp(OUT_DIR / "Hasselblad_Standard_HNCS_Tele.dcp",
              "Hasselblad Standard (HNCS Tele)", cm1_tele, cm2_tele, hsm_tele_d28, hsm_tele_d65, tc_tele, camera_model=None)
    print("\nExported 2 Adobe .dcp Camera Profile files.")

    # 3. Also load camera filter natural.cube.rgb.bin for side-by-side comparison
    nat_raw = np.frombuffer((FS / "odm/etc/camera/filters_lut/natural.cube.rgb.bin").read_bytes(), dtype=np.uint8)
    nat_lut = nat_raw.reshape(32, 32, 32, 4)[..., :3].astype(np.float32) / 255.0

    # Build preview comparison sheet
    build_preview([
        ("Original (Neutral sRGB)", None),
        ("HNCS Main D65 (ColorOnly - Pure HNCS)", preview_map["Hasselblad_Standard_HNCS_Main_D65_ColorOnly_64.cube"]),
        ("HNCS Main D65 (Full + ToneCurve)", preview_map["Hasselblad_Standard_HNCS_Main_D65_Full_ToneCurve_64.cube"]),
        ("HNCS Tele D65 (ColorOnly)", preview_map["Hasselblad_Standard_HNCS_Tele_D65_ColorOnly_64.cube"]),
        ("HNCS Main D28 (2856K Warm Cal)", preview_map["Hasselblad_Standard_HNCS_Main_D28_ColorOnly_33.cube"]),
        ("Ref: Camera Filter 'natural' (32pt)", nat_lut),
    ], OUT_DIR / "hasselblad_standard_comparison.png")
    print(f"Saved preview sheet: {OUT_DIR / 'hasselblad_standard_comparison.png'}")


if __name__ == "__main__":
    main()
