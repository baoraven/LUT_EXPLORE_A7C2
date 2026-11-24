"""
Mobile Hasselblad Color Pipeline 3D LUT Exporter
================================================
Converts 4 native mobile camera 3D LUT formats from extracted firmware partitions
into industry-standard Adobe/DaVinci .cube files:

  1. RGBA8 Raw 3D LUT (.cube.rgb.bin / .3dl.rgb.bin / .bin):
     - Shape: (N, N, N, 4) uint8, axis order [B, G, R, (R, G, B, A)]
     - R varies fastest (identical to .cube standard loop order)
  2. Meishe .MS-LUT binary (odm/etc/camera/meishe_lut/*):
     - Header: magic b".MS-LUT ", version u32, N u32, ..., axis_flag u32 at offset 24,
       data_offset u32 at offset 40 (= 48 + N*4)
     - Payload: (N, N, N, 3) uint8 RGB
     - axis_flag == 1 -> [B, G, R, RGB] (R fastest, direct .cube order)
     - axis_flag == 0 -> [R, G, B, RGB] (B fastest, requires transpose (2, 1, 0, 3))
  3. BasicTone Planar Float32 3D LUT (odm/etc/camera/basictone/* & masterlut/*):
     - Shape: (3, N, N, N) little-endian float32 in [0.0, 1.0], RGB color space
     - Transpose (1, 2, 3, 0) -> [B, G, R, (R, G, B)] (R fastest, direct .cube order)
  4. GPUImage 512x512 PNG HaldCLUT (gallery filter PNGs):
     - 8x8 tiles of 64x64 pixels -> N = 64
     - tile_y = b // 8, tile_x = b % 8, y = g, x = r
"""

import json
import pathlib
import shutil
import struct
from collections import Counter
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
FS = ROOT / "extracted/fs"
APK = ROOT / "extracted/apk_assets"
OUT_ROOT = ROOT / "output"
LUT_OUT = OUT_ROOT / "luts"


def write_cube(arr_bgr_rgb: np.ndarray, out_path: pathlib.Path, title: str, comments: list[str] | None = None):
    """Write a standard .cube 3D LUT from (N, N, N, 3) float32 array indexed [b, g, r, rgb]."""
    assert arr_bgr_rgb.ndim == 4 and arr_bgr_rgb.shape[3] == 3
    N = arr_bgr_rgb.shape[0]
    assert arr_bgr_rgb.shape == (N, N, N, 3)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.clip(arr_bgr_rgb.astype(np.float32), 0.0, 1.0).reshape(-1, 3)
    lines = ["# Exported via Hasselblad Color Pipeline Research Toolkit"]
    if comments:
        lines.extend(f"# {c}" for c in comments)
    lines.extend([
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {N}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
        "",
    ])
    header = "\n".join(lines) + "\n"
    body = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in arr) + "\n"
    out_path.write_text(header + body, encoding="utf-8")
    return N


def load_rgba8_bin(path: pathlib.Path) -> tuple[int, np.ndarray]:
    data = path.read_bytes()
    n_pix = len(data) // 4
    N = round(n_pix ** (1 / 3))
    if N ** 3 * 4 != len(data):
        raise ValueError(f"Invalid RGBA8 LUT size {len(data)} for {path}")
    arr = np.frombuffer(data, dtype=np.uint8).reshape(N, N, N, 4)[..., :3]
    return N, arr.astype(np.float32) / 255.0


def load_mslut(path: pathlib.Path) -> tuple[int, np.ndarray, int]:
    data = path.read_bytes()
    if data[:8] != b".MS-LUT ":
        raise ValueError(f"Not a .MS-LUT file: {path}")
    _ver, N, _u4, _u5, axis_flag, _u7, _grid_off, _u9, data_off = struct.unpack("<9I", data[8:44])
    payload = np.frombuffer(data[data_off : data_off + N ** 3 * 3], dtype=np.uint8).reshape(N, N, N, 3)
    if axis_flag == 0:
        payload = np.transpose(payload, (2, 1, 0, 3))
    return N, payload.astype(np.float32) / 255.0, axis_flag


def load_planar_f32(path: pathlib.Path) -> tuple[int, np.ndarray]:
    raw = np.frombuffer(path.read_bytes(), dtype="<f4")
    N = round((len(raw) / 3) ** (1 / 3))
    if N ** 3 * 3 != len(raw):
        raise ValueError(f"Invalid planar float32 LUT size {len(raw)*4} for {path}")
    arr = raw.reshape(3, N, N, N).transpose(1, 2, 3, 0)
    return N, arr


def load_png_hald512(path: pathlib.Path) -> tuple[int, np.ndarray]:
    im = np.array(Image.open(path).convert("RGB"), dtype=np.uint8)
    assert im.shape == (512, 512, 3), f"Expected 512x512 RGB, got {im.shape} for {path}"
    tiles = im.reshape(8, 64, 8, 64, 3).transpose(0, 2, 1, 3, 4).reshape(64, 64, 64, 3)
    return 64, tiles.astype(np.float32) / 255.0


def find_first(base: pathlib.Path, pattern: str) -> pathlib.Path | None:
    matches = sorted(base.glob(pattern)) if base.exists() else []
    return matches[0] if matches else None


def main():
    if LUT_OUT.exists():
        shutil.rmtree(LUT_OUT)
    LUT_OUT.mkdir(parents=True, exist_ok=True)

    catalog = []
    exported_sources = set()

    def record(category, out_name, src_path, fmt, N, note=""):
        rel_out = str((LUT_OUT / category / out_name).relative_to(OUT_ROOT)).replace("\\", "/")
        catalog.append({"category": category, "output": rel_out, "source": src_path.name, "format": fmt, "size": N, "note": note})

    fl_dir = FS / "odm/etc/camera/filters_lut"
    ms_dir = FS / "odm/etc/camera/meishe_lut"
    bt_dir = FS / "odm/etc/camera/basictone"
    gal_root = next((p for p in APK.iterdir() if p.is_dir() and (p / "assets/filter/filter.cfg").exists()), None) if APK.exists() else None
    gal_lut_dir = (gal_root / "assets/luts") if gal_root else pathlib.Path("__missing__")
    gal_png_dir = (gal_root / "assets/filter") if gal_root else pathlib.Path("__missing__")

    # 01. Hasselblad Master & Nordic & XPan Filters
    cat1 = "01_Hasselblad_Master_Filters"
    hasselblad_specs = [
        ("Hasselblad_Serenity_童话_32.cube", fl_dir / "Serenity.cube.rgb.bin", "rgba8", "哈苏大师滤镜「童话」(Serenity)"),
        ("Hasselblad_Radiance_人像_32.cube", fl_dir / "Radiance.cube.rgb.bin", "rgba8", "哈苏大师滤镜「人像」(Radiance)"),
        ("Hasselblad_Emerald_风光_32.cube", fl_dir / "Emerald.cube.rgb.bin", "rgba8", "哈苏大师滤镜「风光」(Emerald)"),
        ("Hasselblad_XPan_Delta400_黑白_32.cube", fl_dir / "Delta400.3dl.rgb.bin", "rgba8", "哈苏 XPan 经典黑白 (Delta 400)"),
        ("Hasselblad_Nordic_Sarek_III_16.cube", find_first(fl_dir, "*SAREK_III*"), "rgba8", "哈苏北欧风格「萨勒克 Sarek III」"),
        ("Hasselblad_Nordic_Vaeroy_III_16.cube", find_first(fl_dir, "*VAEROY_III*"), "rgba8", "哈苏北欧风格「韦岛 Vaeroy III」"),
        ("Hasselblad_Nordic_Yllas_16.cube", find_first(fl_dir, "*YLLAAS*"), "rgba8", "哈苏北欧风格「玉拉斯 Yllas」"),
        ("Hasselblad_Master_Martin_32.cube", fl_dir / "Martin.cube.rgb.bin", "rgba8", "大师风格 Martin"),
        ("Hasselblad_Master_Texture70_32.cube", fl_dir / "Texture-70.cube.rgb.bin", "rgba8", "质感大师 Texture-70"),
        ("Hasselblad_Master_ToneOfLight_光影_32.cube", ms_dir / "tone-of-light.cube.rgb.bin", "mslut", "光影影调 Tone of Light"),
    ]
    for out_name, src, fmt, note in hasselblad_specs:
        if src is None or not src.exists():
            continue
        N, arr = load_rgba8_bin(src) if fmt == "rgba8" else load_mslut(src)[:2]
        write_cube(arr, LUT_OUT / cat1 / out_name, out_name.replace(".cube", ""), [note])
        record(cat1, out_name, src, fmt, N, note)
        exported_sources.add(src.resolve())

    # 02. Film Simulation
    cat2 = "02_Film_Simulation"
    film_specs = [
        ("Film_Fuji_NC_复古_17.cube", ms_dir / "fuji-nc.bin", "mslut", "胶片滤镜：复古 (Classic Neg / NC)"),
        ("Film_Fuji_CC_通透_17.cube", ms_dir / "fuji_cc.bin", "mslut", "胶片滤镜：通透 (Classic Chrome / CC)"),
        ("Film_Fuji_CC_High_32.cube", ms_dir / "fuji-cc-high.bin", "mslut", "胶片滤镜 Classic Chrome High (32pt)"),
        ("Film_Fuji_CC_Low_17.cube", ms_dir / "fuji-cc-low.bin", "mslut", "胶片滤镜 Classic Chrome Low (17pt)"),
        ("Film_Fuji_NH_ProNegHi_清新_17.cube", ms_dir / "fuji-proNegHi.bin", "mslut", "胶片滤镜：清新 (Pro Neg. Hi / NH)"),
        ("Film_Fuji_Eterna_v2_32.cube", fl_dir / "fuji-eterna-v2.cube.rgb.bin", "rgba8", "电影胶片 Eterna v2"),
        ("Film_Fuji_Classic_32.cube", fl_dir / "fuji.cube.rgb.bin", "rgba8", "经典胶片 Fuji"),
        ("Film_Fuji_Acros_黑白_32.cube", fl_dir / "type_fuji_acros", "rgba8", "黑白胶片 Acros"),
        ("Film_Fuji_Astia_柔和_32.cube", fl_dir / "type_fuji_astia", "rgba8", "柔和胶片 Astia"),
        ("Film_Fuji_Chrome_正片_32.cube", fl_dir / "type_fuji_chrome", "rgba8", "正片 Chrome"),
        ("Film_Fuji_Provia_标准_32.cube", fl_dir / "type_fuji_provia", "rgba8", "标准胶片 Provia"),
        ("Film_Fuji_Velvia_鲜艳_32.cube", fl_dir / "type_fuji_velvia", "rgba8", "鲜艳胶片 Velvia"),
        ("Film_Kodak_32.cube", fl_dir / "kodak.cube.rgb.bin", "rgba8", "经典胶片 Kodak"),
        ("Film_GR3_Slide_正片_32.cube", gal_lut_dir / "G-GR3Slide-1.1.CUBE.rgb.bin", "rgba8", "GR3 正片风格"),
        ("Film_SSX04_胶片_32.cube", gal_lut_dir / "G-SSX04-1.1.CUBE.rgb.bin", "rgba8", "经典胶片 SSX04"),
    ]
    for out_name, src, fmt, note in film_specs:
        if not src.exists():
            continue
        N, arr = load_rgba8_bin(src) if fmt == "rgba8" else load_mslut(src)[:2]
        write_cube(arr, LUT_OUT / cat2 / out_name, out_name.replace(".cube", ""), [note])
        record(cat2, out_name, src, fmt, N, note)
        exported_sources.add(src.resolve())

    # 03. BasicTone & Master Mode Engine (Planar Float32)
    cat3 = "03_BasicTone_MasterMode_Engine"
    bt_core = [
        ("LMT/BasicTone_BaseLut_Identity_64.cube", bt_dir / "lmt/BaseLut", "BasicTone 64pt 基准恒等 LUT"),
        ("LMT/BasicTone_LMTLut0_64.cube", bt_dir / "lmt/LMTLut0", "BasicTone 64pt LMT"),
        ("ODT/BasicTone_ODT_Photo_64.cube", bt_dir / "odt/ODT_Photo", "BasicTone 64pt Photo ODT"),
        ("ODT/BasicTone_ODT_Dolby_64.cube", bt_dir / "odt/ODT_Dolby", "BasicTone 64pt Dolby Preview ODT"),
        ("ODT/MasterLut_ODT_BT2020_PQ10000_to_P3_sRGB_64.cube", fl_dir / "masterlut/ODT_Photo", "MasterLut 64pt BT.2020 PQ -> P3/sRGB ODT"),
    ]
    for rel_out, src, note in bt_core:
        if not src.exists():
            continue
        N, arr = load_planar_f32(src)
        write_cube(arr, LUT_OUT / cat3 / rel_out, pathlib.Path(rel_out).stem, [note])
        record(cat3, rel_out, src, "planar_f32", N, note)

    sat_labels = ["Sat-100", "Sat0", "Sat+100"]
    cont_labels = ["Cont-100", "Cont0", "Cont+100"]
    cowa_labels = ["Cool-100", "Temp0", "Warm+100"]
    cyma_labels = ["Cyan-100", "Tint0", "Magenta+100"]
    for idx in range(9):
        for prefix, sub, sz_tag in [("SC32Lut", "MasterMode_Sat_Contrast_3x3_32pt", "32"), ("SCLut", "MasterMode_Sat_Contrast_3x3_64pt", "64")]:
            src = bt_dir / "lmt" / f"{prefix}{idx}"
            if src.exists():
                N, arr = load_planar_f32(src)
                rel_out = f"{sub}/{prefix}{idx}_{sat_labels[idx//3]}_{cont_labels[idx%3]}_{sz_tag}.cube"
                write_cube(arr, LUT_OUT / cat3 / rel_out, pathlib.Path(rel_out).stem, ["Master Mode 3x3 Basis LUT"])
                record(cat3, rel_out, src, "planar_f32", N, "Master Mode Sat x Cont Basis")
        src = bt_dir / "lmt" / f"CWCM32Lut{idx}"
        if src.exists():
            N, arr = load_planar_f32(src)
            rel_out = f"MasterMode_Temp_Tint_3x3_32pt/CWCM32Lut{idx}_{cowa_labels[idx//3]}_{cyma_labels[idx%3]}_32.cube"
            write_cube(arr, LUT_OUT / cat3 / rel_out, pathlib.Path(rel_out).stem, ["Master Mode 3x3 Basis LUT"])
            record(cat3, rel_out, src, "planar_f32", N, "Master Mode Temp x Tint Basis")

    # 06. Gallery 512x512 HaldCLUT PNGs
    cat6 = "06_Gallery_HaldCLUT_64"
    if (gal_png_dir / "filter.cfg").exists():
        fcfg = json.loads((gal_png_dir / "filter.cfg").read_text(encoding="utf-8"))
        for item in fcfg:
            rp = item.get("resourcePath", "")
            if not rp.endswith(".png"):
                continue
            src = gal_png_dir / pathlib.Path(rp).name
            if not src.exists():
                continue
            zh = item.get("zhName", "").replace("/", "_")
            en = item.get("enName", "").replace(" ", "_").replace("/", "_")
            out_name = f"Gallery_{en}_{zh}_64.cube"
            N, arr = load_png_hald512(src)
            write_cube(arr, LUT_OUT / cat6 / out_name, f"{en} ({zh})", [f"Gallery 64pt HaldCLUT: {zh}"])
            record(cat6, out_name, src, "png_hald512", N, f"相册滤镜 {zh}")

    counts = Counter(item["category"] for item in catalog)
    print(f"Exported {len(catalog)} standard .cube LUT files to {LUT_OUT}")
    for cat, cnt in sorted(counts.items()):
        print(f"  {cat:38s}: {cnt:3d} LUTs")


if __name__ == "__main__":
    main()
