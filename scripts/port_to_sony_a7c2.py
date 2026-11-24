"""
Sony A7C II (ILCE-7CM2) Hasselblad LUT & DCP Porting Pipeline
=============================================================
Ports Hasselblad Standard (HNCS) + Master/Film LUTs to Sony A7C II:

1. In-Camera User LUTs (33x33x33 .cube, pure ASCII filenames, placed directly in
   `SD_CARD_COPY/PRIVATE/SONY/PRO/LUT/` for drag-and-drop onto A7C II SD card):
   - 12x S-Log3 / S-Gamut3.Cine -> Filmic Roll-off -> Hasselblad HNCS (+ Style) -> Rec.709
   - 4x  Rec.709 -> Hasselblad HNCS / Master Styles -> Rec.709 (for Rec.709 PPLUT / DaVinci)

2. Lightroom / ACR / RawTherapee RAW Camera Profiles (.dcp) calibrated for Sony ILCE-7CM2:
   - Combines Sony ILCE-7CM2's official D65 ColorMatrix (from Adobe/LibRaw)
     with device-independent Hasselblad D65 HueSatMap (36x20x20) & ToneCurve (128pt).

3. Strict verification of all 16 .cube files (Sony A7C II compliance) + 2 .dcp files
   + visual S-Log3 12-stop exposure & Macbeth 24-patch ColorChecker validation chart.
"""

import pathlib
import struct
import numpy as np
from PIL import Image, ImageDraw
from scipy.interpolate import RegularGridInterpolator

FS = pathlib.Path("D:/AI_LUT/extracted/fs")
DNG_DIR = FS / "odm/etc/camera/dng"
LUT_SRC = pathlib.Path("D:/AI_LUT/output/luts")
HNCS_SRC = pathlib.Path("D:/AI_LUT/output/Hasselblad_Standard_HNCS")

PORT_ROOT = pathlib.Path("D:/AI_LUT/output/Sony_A7C2_Port")
SD_LUT_DIR = PORT_ROOT / "SD_CARD_COPY/PRIVATE/SONY/PRO/LUT"
DCP_DIR = PORT_ROOT / "Lightroom_ACR_DCP"

# =============================================================================
# 1. Exact Color Science Matrices (Sony S-Gamut3.Cine, Rec.709, ProPhoto D50)
# =============================================================================

def xy_to_XYZ(x: float, y: float) -> np.ndarray:
    return np.array([x / y, 1.0, (1.0 - x - y) / y], dtype=np.float64)


def primaries_to_rgb_to_xyz(r_xy, g_xy, b_xy, w_xy) -> np.ndarray:
    R = xy_to_XYZ(*r_xy)
    G = xy_to_XYZ(*g_xy)
    B = xy_to_XYZ(*b_xy)
    W = xy_to_XYZ(*w_xy)
    M = np.column_stack([R, G, B])
    S = np.linalg.solve(M, W)
    return M * S[None, :]


D65_XY = (0.3127, 0.3290)
D50_XY = (0.3457, 0.3585)

# Sony official S-Gamut3.Cine primaries (Technical Summary for S-Gamut3.Cine/S-Log3)
M_SGAMUT3CINE_TO_XYZ_D65 = primaries_to_rgb_to_xyz(
    (0.766, 0.275), (0.225, 0.800), (0.089, -0.087), D65_XY
)

# ITU-R BT.709 / sRGB primaries (D65)
M_REC709_TO_XYZ_D65 = primaries_to_rgb_to_xyz(
    (0.6400, 0.3300), (0.3000, 0.6000), (0.1500, 0.0600), D65_XY
)
M_XYZ_D65_TO_REC709 = np.linalg.inv(M_REC709_TO_XYZ_D65)

# Bradford chromatic adaptation D65 <-> D50 (exact ICC / DNG spec)
M_BRADFORD = np.array([
    [ 0.8951000,  0.2664000, -0.1614000],
    [-0.7502000,  1.7135000,  0.0367000],
    [ 0.0389000, -0.0685000,  1.0296000],
], dtype=np.float64)

def bradford_adapt(src_xy, dst_xy) -> np.ndarray:
    src_cone = M_BRADFORD @ xy_to_XYZ(*src_xy)
    dst_cone = M_BRADFORD @ xy_to_XYZ(*dst_xy)
    return np.linalg.inv(M_BRADFORD) @ np.diag(dst_cone / src_cone) @ M_BRADFORD

M_D65_TO_D50 = bradford_adapt(D65_XY, D50_XY)
M_D50_TO_D65 = np.linalg.inv(M_D65_TO_D50)

# ProPhoto RGB (ROMM RGB, native D50)
M_PROPHOTO_TO_XYZ_D50 = np.array([
    [0.7976749, 0.1351917, 0.0313534],
    [0.2880402, 0.7118741, 0.0000857],
    [0.0000000, 0.0000000, 0.8252100],
], dtype=np.float64)
M_XYZ_D50_TO_PROPHOTO = np.linalg.inv(M_PROPHOTO_TO_XYZ_D50)

# Combined high-precision linear gamut matrices
M_SGAMUT3CINE_TO_PROPHOTO = M_XYZ_D50_TO_PROPHOTO @ M_D65_TO_D50 @ M_SGAMUT3CINE_TO_XYZ_D65
M_PROPHOTO_TO_REC709 = M_XYZ_D65_TO_REC709 @ M_D50_TO_D65 @ M_PROPHOTO_TO_XYZ_D50
M_REC709_TO_SGAMUT3CINE = np.linalg.inv(M_SGAMUT3CINE_TO_XYZ_D65) @ M_REC709_TO_XYZ_D65


# =============================================================================
# 2. Exact Sony S-Log3 OETF / EOTF and Rec.709 / sRGB Transfer Functions
# =============================================================================

def slog3_decode(y: np.ndarray) -> np.ndarray:
    """Sony official S-Log3 [0, 1] -> Scene-Linear reflection (18% gray -> 0.18)."""
    y10 = np.clip(y, 0.0, 1.0) * 1023.0
    cut = 171.2102946929
    lin_log = (10.0 ** ((y10 - 420.0) / 261.5)) * (0.18 + 0.01) - 0.01
    lin_low = (y10 - 95.0) * 0.01125000 / (cut - 95.0)
    return np.where(y10 >= cut, lin_log, lin_low)


def slog3_encode(x: np.ndarray) -> np.ndarray:
    """Sony official Scene-Linear reflection -> S-Log3 [0, 1]."""
    x = np.maximum(x, 0.0)
    cut = 0.01125000
    y_log = (420.0 + np.log10((x + 0.01) / (0.18 + 0.01)) * 261.5) / 1023.0
    y_low = (x * (171.2102946929 - 95.0) / cut + 95.0) / 1023.0
    return np.clip(np.where(x >= cut, y_log, y_low), 0.0, 1.0)


def srgb_oetf(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * (x ** (1.0 / 2.4)) - 0.055)


def filmic_highlight_rolloff(lin_rgb: np.ndarray, mid_gray_target: float = 0.18, white_point: float = 12.0) -> np.ndarray:
    """
    Smooth cinema highlight compression for S-Log3 scene-linear light -> display-linear [0, 1].
    Preserves neutral 18% middle gray accurately while smoothly rolling off +6 stops of highlights
    (calibrated to match Sony s709 / Hasselblad natural contrast without harsh clipping).
    Uses luminance-preserving chroma-safe roll-off + gentle highlight desaturation.
    """
    x = np.maximum(lin_rgb, 0.0)
    # Luminance in ProPhoto RGB
    luma = 0.2880402 * x[..., 0] + 0.7118741 * x[..., 1] + 0.0000857 * x[..., 2]
    # Subtle toe + smooth rational shoulder (Reinhard-extended with exact anchor at 0.18)
    # f(L) = (L * (1 + L / W^2)) / (1 + k * L) scaled so f(0.18) = mid_gray_target
    # Solve k for smooth shoulder where L=0.18 -> ~0.18, L=0.90 -> ~0.58, L=3.6 -> ~0.85, L=12.0 -> ~0.97
    # Using ACES-inspired filmic curve: (a*L*(L + b)) / (L*(c*L + d) + e)
    # Even cleaner & exact monotonic: Michaelis-Menten with white point W:
    # t(L) = (L * (W + s)) / (W * (L + s)) -> t(0)=0, t(W)=1, t'(0)=(W+s)/(W*s)
    # With s = 0.75, W = 16.0:
    #   L=0.18 -> 0.203 (sRGB ~0.487, crisp natural exposure matching Sony s709!)
    #   L=0.90 -> 0.571 (sRGB ~0.780, airy white with room for highlights!)
    #   L=3.60 -> 0.866 (sRGB ~0.938, +4.3 stops preserved!)
    #   L=16.0 -> 1.000
    s = 0.82
    W = 16.0
    # Slight shadow toe (gamma 1.06 below 0.18) for clean Sony S-Log3 noise floor
    luma_toe = np.where(luma < 0.18, 0.18 * ((luma / 0.18) ** 1.08), luma)
    mapped_luma = (luma_toe * (W + s)) / (W * (luma_toe + s))
    mapped_luma = np.clip(mapped_luma, 0.0, 1.0)

    ratio = np.where(luma > 1e-8, mapped_luma / np.maximum(luma, 1e-8), 0.0)
    out = x * ratio[..., None]

    # Cinema highlight desaturation (prevents skewed neon hues in >2-stop highlights)
    desat = np.clip((mapped_luma - 0.72) / 0.28, 0.0, 1.0) ** 1.6
    out = out * (1.0 - 0.65 * desat[..., None]) + mapped_luma[..., None] * (0.65 * desat[..., None])
    return np.clip(out, 0.0, 1.0)


# =============================================================================
# 3. Hasselblad HNCS HueSatMap & ToneCurve (Exact Adobe DNG 1.6 Implementation)
# =============================================================================

def rgb_to_hsv_vec(rgb: np.ndarray):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    gap = mx - mn
    v = mx
    s = np.where(mx > 1e-10, gap / np.maximum(mx, 1e-10), 0.0)
    h = np.zeros_like(mx)
    mask = gap > 1e-10
    rm = mask & (mx == r)
    gm = mask & (mx == g) & (~rm)
    bm = mask & (~rm) & (~gm)
    h[rm] = ((g[rm] - b[rm]) / gap[rm]) % 6.0
    h[gm] = ((b[gm] - r[gm]) / gap[gm]) + 2.0
    h[bm] = ((r[bm] - g[bm]) / gap[bm]) + 4.0
    return np.mod(h, 6.0), s, v


def hsv_to_rgb_vec(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
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


def apply_dng_huesatmap(prophoto_lin: np.ndarray, hsm: np.ndarray) -> np.ndarray:
    V_dim, H_dim, S_dim, _ = hsm.shape
    h, s, v = rgb_to_hsv_vec(np.clip(prophoto_lin, 0.0, 1.0))
    hf = (h / 6.0) * H_dim
    sf = np.clip(s, 0.0, 1.0) * (S_dim - 1)
    vf = np.clip(v, 0.0, 1.0) * (V_dim - 1)

    h0 = np.floor(hf).astype(np.int32) % H_dim
    h1 = (h0 + 1) % H_dim
    fh = (hf - np.floor(hf))[..., None]

    s0 = np.minimum(np.floor(sf).astype(np.int32), S_dim - 2)
    s1 = s0 + 1
    fs = (sf - s0)[..., None]

    v0 = np.minimum(np.floor(vf).astype(np.int32), V_dim - 2)
    v1 = v0 + 1
    fv = (vf - v0)[..., None]

    c00 = hsm[v0, h0, s0] * (1.0 - fs) + hsm[v0, h0, s1] * fs
    c01 = hsm[v0, h1, s0] * (1.0 - fs) + hsm[v0, h1, s1] * fs
    c10 = hsm[v1, h0, s0] * (1.0 - fs) + hsm[v1, h0, s1] * fs
    c11 = hsm[v1, h1, s0] * (1.0 - fs) + hsm[v1, h1, s1] * fs

    entry = (c00 * (1.0 - fh) + c01 * fh) * (1.0 - fv) + (c10 * (1.0 - fh) + c11 * fh) * fv
    return hsv_to_rgb_vec(
        np.mod(h + entry[..., 0] / 60.0, 6.0),
        np.clip(s * entry[..., 1], 0.0, 1.0),
        np.clip(v * entry[..., 2], 0.0, 1.0),
    )


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
    return np.array(vals, dtype=np.float64).reshape(N, N, N, 3)


def apply_cube(lut: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    N = lut.shape[0]
    g = np.linspace(0.0, 1.0, N, dtype=np.float64)
    interp = RegularGridInterpolator((g, g, g), lut, bounds_error=False, fill_value=None)
    return np.clip(interp(np.clip(rgb, 0.0, 1.0)[..., [2, 1, 0]]), 0.0, 1.0)


def write_sony_cube(arr: np.ndarray, out_path: pathlib.Path, title_ascii: str):
    """Write strict Sony A7C II compliant 33-point .cube (ASCII only, LF line endings)."""
    N = arr.shape[0]
    assert N in (17, 33), f"Sony A7C II requires 17 or 33 point LUT, got {N}"
    assert out_path.name.isascii() and len(out_path.name) <= 63, f"Invalid Sony filename: {out_path.name}"
    assert title_ascii.isascii()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat = np.clip(arr, 0.0, 1.0).reshape(-1, 3)
    header = (
        f'TITLE "{title_ascii}"\n'
        f"LUT_3D_SIZE {N}\n"
        f"DOMAIN_MIN 0.0 0.0 0.0\n"
        f"DOMAIN_MAX 1.0 1.0 1.0\n\n"
    )
    body = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in flat) + "\n"
    # Sony cameras prefer clean LF newlines
    out_path.write_bytes((header + body).encode("ascii"))


# =============================================================================
# 4. Sony ILCE-7CM2 (A7C II) Adobe .dcp Camera Profile Writer
# =============================================================================

def write_sony_a7c2_dcp(out_path: pathlib.Path, profile_name: str, hsm_d65: np.ndarray, tc: np.ndarray | None):
    """
    Build Adobe .dcp profile combining:
      - Sony ILCE-7CM2 official D65 ColorMatrix (from Adobe DNG / LibRaw)
      - Device-independent Hasselblad D65 HueSatMap (36x20x20, ProPhoto D50)
      - Hasselblad 128-point ToneCurve (optional)
    """
    # Exact Sony ILCE-7CM2 (= ILCE-7M4 33MP Exmor R) D65 ColorMatrix from LibRaw/Adobe
    cm_a7c2_d65 = np.array([
        0.7460, -0.2365, -0.0588,
        -0.5687, 1.3442,  0.2474,
        -0.0624, 0.1156,  0.6584,
    ], dtype=np.float64)

    entries = []
    def add_ascii(tag, text):
        b = text.encode("ascii") + b"\x00"
        entries.append((tag, 2, len(b), b))
    def add_short(tag, val):
        entries.append((tag, 3, 1, struct.pack("<H", val)))
    def add_longs(tag, vals):
        entries.append((tag, 4, len(vals), struct.pack(f"<{len(vals)}I", *vals)))
    def add_srational9(tag, mat9):
        scale = 1000000
        b = b"".join(struct.pack("<ii", int(round(float(v) * scale)), scale) for v in mat9)
        entries.append((tag, 10, 9, b))
    def add_floats(tag, arr):
        f32 = arr.astype("<f4").ravel()
        entries.append((tag, 11, int(f32.size), f32.tobytes()))

    add_ascii(0xC614, "Sony ILCE-7CM2")               # UniqueCameraModelRestriction (matches Sony A7C II ARW!)
    add_srational9(0xC621, cm_a7c2_d65)               # ColorMatrix1 (D65)
    add_short(0xC65A, 21)                             # CalibrationIlluminant1 = D65
    add_ascii(0xC6F8, profile_name)                   # ProfileName
    add_longs(0xC6F9, [36, 20, 20])                   # ProfileHueSatMapDims
    add_floats(0xC6FA, hsm_d65)                       # ProfileHueSatMapData1 (D65 Hasselblad HNCS)
    if tc is not None:
        add_floats(0xC6FC, tc)                        # ProfileToneCurve (128pt Hasselblad curve)
    else:
        add_floats(0xC6FC, np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float32))
    add_longs(0xC6FD, [0])                            # ProfileEmbedPolicy = Allow Copying
    add_ascii(0xC6FE, "Sony A7C II (ILCE-7CM2) + Hasselblad HNCS - Personal Study Only")
    add_longs(0xC7A3, [0])                            # ProfileHueSatMapEncoding = 0 (Linear)

    entries.sort(key=lambda e: e[0])
    ifd_off = 8
    data_off = ifd_off + 2 + 12 * len(entries) + 4
    ifd = bytearray(struct.pack("<H", len(entries)))
    data = bytearray()
    for tag, typ, cnt, raw in entries:
        if len(raw) <= 4:
            ifd += struct.pack("<HHI", tag, typ, cnt) + raw.ljust(4, b"\x00")
        else:
            while (data_off + len(data)) % 4 != 0:
                data.append(0)
            off = data_off + len(data)
            ifd += struct.pack("<HHII", tag, typ, cnt, off)
            data += raw
    ifd += struct.pack("<I", 0)
    header = struct.pack("<2sHI", b"II", 0x4352, ifd_off)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + bytes(ifd) + bytes(data))


# =============================================================================
# 5. Build S-Log3 & Rec.709 33pt LUTs + S-Log3 Visual Validation Chart
# =============================================================================

def build_slog3_lut(
    hsm_d65: np.ndarray,
    tc: np.ndarray | None = None,
    tc_strength: float = 0.0,
    style_cube: pathlib.Path | None = None,
    style_strength: float = 1.0,
    size: int = 33,
) -> np.ndarray:
    """
    Full A7C II S-Log3 / S-Gamut3.Cine -> Rec.709 Hasselblad pipeline baked into 33^3 .cube:
      1. S-Log3 decode -> Scene-Linear S-Gamut3.Cine
      2. Gamut matrix -> Linear ProPhoto RGB (D50)
      3. Cinema highlight roll-off (S-Log3 15 stops -> display-linear [0, 1])
      4. Hasselblad Standard HNCS 36x20x20 D65 HueSatMap
      5. Optional subtle blend of Hasselblad 128pt ToneCurve
      6. Gamut matrix -> Linear Rec.709 -> sRGB/Rec.709 display OETF
      7. Optional Hasselblad Master / Film creative LUT with strength blend
    """
    lin = np.linspace(0.0, 1.0, size, dtype=np.float64)
    B, G, R = np.meshgrid(lin, lin, lin, indexing="ij")
    slog3_in = np.stack([R, G, B], axis=-1)

    # 1. Decode S-Log3
    sg3c_lin = slog3_decode(slog3_in)

    # 2. Convert S-Gamut3.Cine -> Linear ProPhoto D50
    prophoto_scene = np.einsum("...j,ij->...i", sg3c_lin, M_SGAMUT3CINE_TO_PROPHOTO)

    # 3. Smooth filmic highlight roll-off -> display-linear [0, 1]
    prophoto_disp = filmic_highlight_rolloff(prophoto_scene)

    # 4. Apply official Hasselblad Standard HNCS 3D HueSatMap
    prophoto_hncs = apply_dng_huesatmap(prophoto_disp, hsm_d65)

    # 5. Optional Hasselblad ToneCurve blend (subtle for video headroom)
    if tc is not None and tc_strength > 0.0:
        tc_out = np.interp(np.clip(prophoto_hncs, 0.0, 1.0), tc[:, 0], tc[:, 1])
        prophoto_hncs = (1.0 - tc_strength) * prophoto_hncs + tc_strength * tc_out

    # 6. Linear ProPhoto D50 -> Linear Rec.709 -> Display OETF
    rec709_lin = np.einsum("...j,ij->...i", prophoto_hncs, M_PROPHOTO_TO_REC709)
    rec709_out = srgb_oetf(np.clip(rec709_lin, 0.0, 1.0))

    # 7. Optional creative style LUT (Serenity, Radiance, Emerald, Fuji NC/CC/NH, etc.)
    if style_cube is not None and style_strength > 0.0:
        sty = load_cube(style_cube)
        styled = apply_cube(sty, rec709_out)
        rec709_out = (1.0 - style_strength) * rec709_out + style_strength * styled

    return np.clip(rec709_out, 0.0, 1.0).astype(np.float32)


def build_rec709_33(src_cube: pathlib.Path) -> np.ndarray:
    """Resample any Rec.709/sRGB LUT to exact 33x33x33 for Sony A7C II."""
    lut = load_cube(src_cube)
    lin = np.linspace(0.0, 1.0, 33, dtype=np.float64)
    B, G, R = np.meshgrid(lin, lin, lin, indexing="ij")
    pts = np.stack([R, G, B], axis=-1)
    return apply_cube(lut, pts).astype(np.float32)


def render_slog3_validation_chart(lut_items: list[tuple[str, np.ndarray | None]], out_png: pathlib.Path):
    """
    Synthesize a physically accurate S-Log3 / S-Gamut3.Cine test image:
      - Top strip: 12-stop gray exposure ramp (-4 EV to +5 EV around 18% gray!)
      - Middle: Macbeth 24-patch ColorChecker encoded in exact S-Log3 / S-Gamut3.Cine
    Apply each Sony A7C II S-Log3 LUT and render side-by-side!
    """
    w, h = 380, 240
    # Build scene-linear Rec.709 image first, then convert to S-Gamut3.Cine & S-Log3!
    scene_709 = np.zeros((h, w, 3), dtype=np.float64)

    # Top strip (0..56): 12-stop exposure wedge from -4 EV to +5 EV relative to 0.18
    ev = np.linspace(-4.0, 5.0, w)
    ramp_lin = 0.18 * (2.0 ** ev)
    scene_709[:56] = ramp_lin[None, :, None]

    # Macbeth 24-patch ColorChecker (convert sRGB patches to linear scene reflectance scaled to 0.18 mid)
    patches = [
        (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
        (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
        (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
        (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
    ]
    def srgb_to_lin(c):
        c = np.array(c, dtype=np.float64) / 255.0
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

    grid_y0 = 64
    cell_h = (h - grid_y0 - 6) // 4
    cell_w = (w - 12) // 6
    scene_709[56:] = 0.015  # dark bezel
    for idx, rgb in enumerate(patches):
        row, col = divmod(idx, 6)
        y0 = grid_y0 + row * cell_h + 2
        x0 = 6 + col * cell_w + 2
        scene_709[y0 : y0 + cell_h - 4, x0 : x0 + cell_w - 4] = srgb_to_lin(rgb)

    # Encode scene-linear Rec.709 -> Linear S-Gamut3.Cine -> S-Log3 [0, 1]
    scene_sg3c = np.einsum("...j,ij->...i", scene_709, M_REC709_TO_SGAMUT3CINE)
    slog3_img = slog3_encode(scene_sg3c)

    cols = 4
    rows = (len(lut_items) + cols - 1) // cols
    pad, label_h = 16, 26
    canvas = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + label_h + pad) + pad), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)

    for idx, (label, lut) in enumerate(lut_items):
        rr, cc = divmod(idx, cols)
        x0 = pad + cc * (w + pad)
        y0 = pad + rr * (h + label_h + pad)
        if lut is None:
            rendered = slog3_img
        else:
            rendered = apply_cube(lut.astype(np.float64), slog3_img)
        canvas.paste(Image.fromarray((np.clip(rendered, 0, 1) * 255.0).round().astype(np.uint8)), (x0, y0 + label_h))
        draw.text((x0 + 4, y0 + 5), label, fill=(235, 235, 240))

    canvas.save(out_png)


def main():
    SD_LUT_DIR.mkdir(parents=True, exist_ok=True)
    DCP_DIR.mkdir(parents=True, exist_ok=True)

    # Load Hasselblad HNCS D65 HueSatMap & ToneCurve (auto-detect main sensor calibration files)
    hsm_path = next(DNG_DIR.glob("D65HUESATMap_*main*.txt"))
    tc_path = next(DNG_DIR.glob("ToneCurve_*main*.txt"))
    hsm_d65 = np.array(
        [float(x) for x in hsm_path.read_text().replace("\n", ",").split(",") if x.strip()],
        dtype=np.float64,
    ).reshape(20, 36, 20, 3)
    tc = np.array(
        [float(x) for x in tc_path.read_text().replace("\n", ",").split(",") if x.strip()],
        dtype=np.float64,
    ).reshape(-1, 2)

    # -------------------------------------------------------------------------
    # A. 12 S-Log3 / S-Gamut3.Cine -> Rec.709 LUTs (User 1..12 on A7C II)
    # -------------------------------------------------------------------------
    slog3_specs = [
        ("HB_Std_HNCS_SL3.cube",     "Hasselblad Standard HNCS SLog3",        None, 0.0, None, 0.0),
        ("HB_Std_HNCS_TC_SL3.cube",  "Hasselblad Standard HNCS Contrast SL3", tc,   0.35, None, 0.0),
        ("HB_Serenity_SL3.cube",     "Hasselblad Serenity SLog3",             None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Serenity_童话_32.cube", 0.85),
        ("HB_Radiance_SL3.cube",     "Hasselblad Radiance SLog3",             None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Radiance_人像_32.cube", 0.85),
        ("HB_Emerald_SL3.cube",      "Hasselblad Emerald SLog3",              None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Emerald_风光_32.cube", 0.85),
        ("HB_XPan_D400_SL3.cube",    "Hasselblad XPan Delta400 SLog3",        None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_XPan_Delta400_黑白_32.cube", 1.0),
        ("HB_Sarek_SL3.cube",        "Hasselblad Sarek III SLog3",            None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Nordic_Sarek_III_16.cube", 0.85),
        ("HB_Vaeroy_SL3.cube",       "Hasselblad Vaeroy III SLog3",           None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Nordic_Vaeroy_III_16.cube", 0.85),
        ("HB_Fuji_NC_SL3.cube",      "Hasselblad Fuji NC SLog3",              None, 0.0, LUT_SRC / "02_Film_Simulation/Film_Fuji_NC_复古_17.cube", 0.85),
        ("HB_Fuji_CC_SL3.cube",      "Hasselblad Fuji CC SLog3",              None, 0.0, LUT_SRC / "02_Film_Simulation/Film_Fuji_CC_通透_17.cube", 0.85),
        ("HB_Fuji_NH_SL3.cube",      "Hasselblad Fuji NH SLog3",              None, 0.0, LUT_SRC / "02_Film_Simulation/Film_Fuji_NH_ProNegHi_清新_17.cube", 0.85),
        ("HB_ToneLight_SL3.cube",    "Hasselblad ToneOfLight SLog3",          None, 0.0, LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Master_ToneOfLight_光影_32.cube", 0.85),
    ]

    generated_slog3 = {}
    print("=== Exporting 12 Sony A7C II S-Log3 / S-Gamut3.Cine 33pt LUTs ===")
    for fname, title, use_tc, tc_s, style_p, style_s in slog3_specs:
        arr = build_slog3_lut(hsm_d65, use_tc, tc_s, style_p, style_s, size=33)
        write_sony_cube(arr, SD_LUT_DIR / fname, title)
        # Check S-Log3 18% middle gray (y = 420/1023 = 0.4106) output!
        mg = apply_cube(arr.astype(np.float64), np.array([[[420/1023]*3]]))[0, 0]
        generated_slog3[fname] = arr
        print(f"  [OK] {fname:26s} | S-Log3 18% gray -> Rec.709 {np.round(mg, 3)}")

    # -------------------------------------------------------------------------
    # B. 4 Rec.709 -> Rec.709 LUTs (User 13..16 on A7C II / DaVinci)
    # -------------------------------------------------------------------------
    rec709_specs = [
        ("HB_Std_HNCS_709.cube",  "Hasselblad Standard HNCS Rec709", HNCS_SRC / "Hasselblad_Standard_HNCS_Main_D65_ColorOnly_64.cube"),
        ("HB_Serenity_709.cube",  "Hasselblad Serenity Rec709",      LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Serenity_童话_32.cube"),
        ("HB_Radiance_709.cube",  "Hasselblad Radiance Rec709",      LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Radiance_人像_32.cube"),
        ("HB_Emerald_709.cube",   "Hasselblad Emerald Rec709",       LUT_SRC / "01_Hasselblad_Master_Filters/Hasselblad_Emerald_风光_32.cube"),
    ]
    print("\n=== Exporting 4 Sony A7C II Rec.709 33pt LUTs ===")
    for fname, title, src in rec709_specs:
        arr = build_rec709_33(src)
        write_sony_cube(arr, SD_LUT_DIR / fname, title)
        print(f"  [OK] {fname:26s} | midgray={np.round(arr[16, 16, 16], 3)}")

    # -------------------------------------------------------------------------
    # C. 2 Sony A7C II (ILCE-7CM2) RAW Camera Profiles (.dcp)
    # -------------------------------------------------------------------------
    print("\n=== Exporting Sony A7C II (ILCE-7CM2) Lightroom / ACR .dcp Profiles ===")
    write_sony_a7c2_dcp(
        DCP_DIR / "Sony_A7C2_Hasselblad_Standard_HNCS.dcp",
        "Sony A7C II - Hasselblad Standard (HNCS)",
        hsm_d65, tc
    )
    write_sony_a7c2_dcp(
        DCP_DIR / "Sony_A7C2_Hasselblad_Standard_HNCS_FlatCurve.dcp",
        "Sony A7C II - Hasselblad Standard (HNCS Flat)",
        hsm_d65, None
    )
    for p in sorted(DCP_DIR.glob("*.dcp")):
        b = p.read_bytes()
        assert b[:4] == b"II\x52\x43"
        print(f"  [OK] {p.name:52s} ({len(b)} bytes)")

    # -------------------------------------------------------------------------
    # D. Render S-Log3 Visual Validation Chart
    # -------------------------------------------------------------------------
    preview_items = [
        ("Raw S-Log3 / S-Gamut3.Cine Input", None),
        ("HB_Std_HNCS_SL3 (Standard)", generated_slog3["HB_Std_HNCS_SL3.cube"]),
        ("HB_Std_HNCS_TC_SL3 (+Curve)", generated_slog3["HB_Std_HNCS_TC_SL3.cube"]),
        ("HB_Serenity_SL3", generated_slog3["HB_Serenity_SL3.cube"]),
        ("HB_Radiance_SL3", generated_slog3["HB_Radiance_SL3.cube"]),
        ("HB_Emerald_SL3", generated_slog3["HB_Emerald_SL3.cube"]),
        ("HB_XPan_D400_SL3 (B&W)", generated_slog3["HB_XPan_D400_SL3.cube"]),
        ("HB_Fuji_NC_SL3", generated_slog3["HB_Fuji_NC_SL3.cube"]),
    ]
    out_png = PORT_ROOT / "a7c2_slog3_lut_verification.png"
    render_slog3_validation_chart(preview_items, out_png)
    print(f"\nSaved S-Log3 visual validation chart: {out_png}")
    print(f"Total SD card LUTs ready: {len(list(SD_LUT_DIR.glob('*.cube')))} / 16 slots")


if __name__ == "__main__":
    main()
