"""
Hasselblad Master Mode BasicTone 3D LUT Composer
================================================
Reproduces the real-time 3D LUT blending pipeline of `libCombineLut.so`
and `libBasicTonePhoto.so` (SimTool_Master.ini):

  Input RGB [0, 1]
    -> 1. SC32Lut (3x3 bilinear blend of Saturation [-100..100] x Contrast [-100..100])
    -> 2. CWCM32Lut (3x3 bilinear blend of Cool/Warm [-100..100] x Cyan/Magenta [-100..100])
    -> 3. Optional Style Filter LUT (e.g., Serenity / Radiance / Emerald / Fuji NC) with strength [0..1]
  Output: Merged industry-standard .cube 3D LUT (33pt or 64pt).
"""

import argparse
import pathlib
import numpy as np
from scipy.interpolate import RegularGridInterpolator

BT_LMT_DIR = pathlib.Path("D:/AI_LUT/extracted/fs/odm/etc/camera/basictone/lmt")


def load_planar_f32(path: pathlib.Path) -> np.ndarray:
    raw = np.frombuffer(path.read_bytes(), dtype="<f4")
    N = round((len(raw) / 3) ** (1 / 3))
    return raw.reshape(3, N, N, N).transpose(1, 2, 3, 0)  # [B, G, R, rgb]


def load_cube(path: pathlib.Path) -> np.ndarray:
    vals = []
    N = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("LUT_3D_SIZE"):
            N = int(s.split()[1])
        elif s[0].isdigit() or s[0] == "-":
            vals.append([float(x) for x in s.split()[:3]])
    return np.array(vals, dtype=np.float32).reshape(N, N, N, 3)


def blend_3x3_luts(prefix: str, axis0_val: float, axis1_val: float) -> np.ndarray:
    """
    Bilinearly blend a 3x3 grid of basis LUTs indexed as idx = i0 * 3 + i1,
    where axis0_val, axis1_val in [-100, 100].
    """
    v0 = float(np.clip(axis0_val, -100.0, 100.0))
    v1 = float(np.clip(axis1_val, -100.0, 100.0))

    def bracket(v):
        if v <= 0.0:
            return 0, 1, (v + 100.0) / 100.0
        return 1, 2, v / 100.0

    i0_a, i0_b, t0 = bracket(v0)
    i1_a, i1_b, t1 = bracket(v1)

    l_aa = load_planar_f32(BT_LMT_DIR / f"{prefix}{i0_a * 3 + i1_a}")
    l_ab = load_planar_f32(BT_LMT_DIR / f"{prefix}{i0_a * 3 + i1_b}")
    l_ba = load_planar_f32(BT_LMT_DIR / f"{prefix}{i0_b * 3 + i1_a}")
    l_bb = load_planar_f32(BT_LMT_DIR / f"{prefix}{i0_b * 3 + i1_b}")

    top = (1.0 - t1) * l_aa + t1 * l_ab
    bot = (1.0 - t1) * l_ba + t1 * l_bb
    return (1.0 - t0) * top + t0 * bot


def apply_lut_trilinear(lut_bgr_rgb: np.ndarray, rgb_pts: np.ndarray) -> np.ndarray:
    N = lut_bgr_rgb.shape[0]
    g = np.linspace(0.0, 1.0, N, dtype=np.float32)
    interp = RegularGridInterpolator((g, g, g), lut_bgr_rgb, method="linear", bounds_error=False, fill_value=None)
    pts_bgr = np.clip(rgb_pts, 0.0, 1.0)[..., [2, 1, 0]]
    return np.clip(interp(pts_bgr), 0.0, 1.0).astype(np.float32)


def compose_master_lut(
    sat: float = 0.0,
    cont: float = 0.0,
    temp: float = 0.0,
    tint: float = 0.0,
    filter_cube: pathlib.Path | None = None,
    strength: float = 1.0,
    out_size: int = 33,
) -> np.ndarray:
    # Build identity RGB grid in .cube order [B, G, R, (R, G, B)]
    lin = np.linspace(0.0, 1.0, out_size, dtype=np.float32)
    B, G, R = np.meshgrid(lin, lin, lin, indexing="ij")
    pts = np.stack([R, G, B], axis=-1)

    # Stage 1: SC (Saturation x Contrast)
    if sat != 0.0 or cont != 0.0:
        sc_lut = blend_3x3_luts("SC32Lut", sat, cont)
        pts = apply_lut_trilinear(sc_lut, pts)

    # Stage 2: CWCM (Cool/Warm x Cyan/Magenta)
    if temp != 0.0 or tint != 0.0:
        cwcm_lut = blend_3x3_luts("CWCM32Lut", temp, tint)
        pts = apply_lut_trilinear(cwcm_lut, pts)

    # Stage 3: Optional Filter LUT with strength blending
    if filter_cube is not None and strength > 0.0:
        flt = load_cube(filter_cube)
        filtered = apply_lut_trilinear(flt, pts)
        s = float(np.clip(strength, 0.0, 1.0))
        pts = (1.0 - s) * pts + s * filtered

    return np.clip(pts, 0.0, 1.0)


def save_cube(arr: np.ndarray, out_path: pathlib.Path, title: str, meta_comment: str):
    N = arr.shape[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat = arr.reshape(-1, 3)
    header = (
        f"# Composed via Hasselblad Master Mode BasicTone Engine\n"
        f"# {meta_comment}\n"
        f'TITLE "{title}"\n'
        f"LUT_3D_SIZE {N}\n"
        f"DOMAIN_MIN 0.0 0.0 0.0\n"
        f"DOMAIN_MAX 1.0 1.0 1.0\n\n"
    )
    body = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in flat) + "\n"
    out_path.write_text(header + body, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Hasselblad Master Mode BasicTone 3D LUT Composer")
    ap.add_argument("--sat", type=float, default=0.0, help="Saturation [-100..100]")
    ap.add_argument("--cont", type=float, default=0.0, help="Contrast [-100..100]")
    ap.add_argument("--temp", type=float, default=0.0, help="Color Temp Cool(-100)..Warm(+100)")
    ap.add_argument("--tint", type=float, default=0.0, help="Tint Cyan(-100)..Magenta(+100)")
    ap.add_argument("--filter", type=pathlib.Path, default=None, help="Optional .cube style filter path")
    ap.add_argument("--strength", type=float, default=1.0, help="Filter blend strength [0..1]")
    ap.add_argument("--size", type=int, default=33, choices=[17, 32, 33, 64], help="Output LUT_3D_SIZE")
    ap.add_argument("--out", type=pathlib.Path, required=True, help="Output .cube file path")
    args = ap.parse_args()

    arr = compose_master_lut(args.sat, args.cont, args.temp, args.tint, args.filter, args.strength, args.size)
    meta = f"Sat={args.sat}, Cont={args.cont}, Temp={args.temp}, Tint={args.tint}, Filter={args.filter.name if args.filter else 'None'}({args.strength})"
    save_cube(arr, args.out, args.out.stem, meta)
    print(f"Generated {args.out} (size={args.size}): {meta}")


if __name__ == "__main__":
    main()
