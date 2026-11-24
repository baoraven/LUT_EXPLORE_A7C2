"""
Sony A7C II Still Photo Batch Hasselblad Processor
==================================================
Applies any exported Rec.709/sRGB Hasselblad .cube LUT (e.g., Hasselblad Standard HNCS,
Serenity, Radiance, Emerald, Fuji NC/CC/NH) to A7C II JPEG/PNG/TIFF photos, with
optional strength blending and optional Master Mode optical vignette (`VigTab_Main`).

Usage:
  python scripts/apply_a7c2_photo_batch.py \
      --input ./A7C2_JPG \
      --output ./A7C2_Hasselblad \
      --lut output/Hasselblad_Standard_HNCS/Hasselblad_Standard_HNCS_Main_D65_ColorOnly_33.cube \
      --strength 1.0 --vignette 0.5
"""

import argparse
import json
import pathlib
import numpy as np
from PIL import Image
from scipy.interpolate import RegularGridInterpolator

VIG_JSON = pathlib.Path("D:/AI_LUT/output/08_DNG_HNCS_and_Vignette/vignette_tables_13x17.json")


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


def apply_vignette(img_rgb: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0.0 or not VIG_JSON.exists():
        return img_rgb
    vig_tab = np.array(json.loads(VIG_JSON.read_text(encoding="utf-8"))["VigTab_Main"]["table"], dtype=np.float32)
    h, w, _ = img_rgb.shape
    # Bilinear resize 13x17 optical vignette gain map to image size
    vig_im = Image.fromarray(vig_tab, mode="F").resize((w, h), resample=Image.Resampling.BILINEAR)
    gain = np.array(vig_im, dtype=np.float32)
    gain = 1.0 - strength * (1.0 - gain)
    return np.clip(img_rgb * gain[..., None], 0.0, 1.0)


def process_image(src: pathlib.Path, dst: pathlib.Path, interp: RegularGridInterpolator, strength: float, vig: float):
    im = Image.open(src)
    exif = im.info.get("exif")
    icc = im.info.get("icc_profile")
    rgb = np.array(im.convert("RGB"), dtype=np.float32) / 255.0

    # Apply 3D LUT
    mapped = np.clip(interp(rgb[..., [2, 1, 0]]), 0.0, 1.0)
    out = (1.0 - strength) * rgb + strength * mapped

    # Optional Hasselblad Master Mode optical vignette
    out = apply_vignette(out, vig)

    dst.parent.mkdir(parents=True, exist_ok=True)
    out_im = Image.fromarray((np.clip(out, 0.0, 1.0) * 255.0).round().astype(np.uint8))
    save_kwargs = {"quality": 96, "subsampling": 0} if dst.suffix.lower() in (".jpg", ".jpeg") else {}
    if exif:
        save_kwargs["exif"] = exif
    if icc:
        save_kwargs["icc_profile"] = icc
    out_im.save(dst, **save_kwargs)


def main():
    ap = argparse.ArgumentParser(description="Batch-apply Hasselblad .cube LUT (+ optical vignette) to A7C II photos")
    ap.add_argument("--input", type=pathlib.Path, required=True, help="Input photo file or directory")
    ap.add_argument("--output", type=pathlib.Path, required=True, help="Output file or directory")
    ap.add_argument("--lut", type=pathlib.Path, required=True, help="Path to Rec.709/sRGB .cube LUT")
    ap.add_argument("--strength", type=float, default=1.0, help="LUT strength [0.0 .. 1.0]")
    ap.add_argument("--vignette", type=float, default=0.0, help="Hasselblad optical vignette (VigTab_Main) strength [0.0 .. 1.0]")
    args = ap.parse_args()

    lut = load_cube(args.lut)
    N = lut.shape[0]
    g = np.linspace(0.0, 1.0, N, dtype=np.float32)
    interp = RegularGridInterpolator((g, g, g), lut, bounds_error=False, fill_value=None)

    exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    if args.input.is_file():
        dst = args.output if args.output.suffix else args.output / args.input.name
        process_image(args.input, dst, interp, args.strength, args.vignette)
        print(f"Processed: {args.input.name} -> {dst}")
    else:
        files = [f for f in sorted(args.input.iterdir()) if f.is_file() and f.suffix.lower() in exts]
        for f in files:
            process_image(f, args.output / f.name, interp, args.strength, args.vignette)
            print(f"Processed: {f.name}")
        print(f"Done! {len(files)} photos saved to {args.output}")


if __name__ == "__main__":
    main()
