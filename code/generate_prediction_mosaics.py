import os
import re
import glob
import math
import time
import numpy as np
import pandas as pd
from PIL import Image
import torch
import torch.nn.functional as F
from transformers import SegformerForSemanticSegmentation

# We generate a ~368-megapixel image ourselves (not an untrusted file),
# so it's safe to disable PIL's decompression-bomb size limit (default
# ~89.5M px -- our mosaic is ~4.1x that and would otherwise raise
# DecompressionBombError).
Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
SAT_OUT = "/Volumes/Spleen/CABIN/datasets/patches/satellite_imagery"
DEM_OUT = "/Volumes/Spleen/CABIN/datasets/patches/elevation"

MODELS_DIR = "/Volumes/Spleen/CABIN/models"

LINEAR_PRED_OUT    = "/Volumes/Spleen/CABIN/datasets/patches/crown_closure_pred_linear"
SEGFORMER_PRED_OUT = "/Volumes/Spleen/CABIN/datasets/patches/crown_closure_pred_segformer"

MOSAIC_LINEAR_DIR    = "/Volumes/Spleen/CABIN/datasets/crown_closure_pred_linear_mosaic"
MOSAIC_SEGFORMER_DIR = "/Volumes/Spleen/CABIN/datasets/crown_closure_pred_segformer_mosaic"
MOSAIC_LINEAR_PATH    = os.path.join(MOSAIC_LINEAR_DIR, "crown_closure_pred_linear_mosaic.png")
MOSAIC_SEGFORMER_PATH = os.path.join(MOSAIC_SEGFORMER_DIR, "crown_closure_pred_segformer_mosaic.png")

PATCH_SIZE_PX = 256
PATCH_SIZE_M  = 6400
BATCH_SIZE    = 8

RGB_MIN, RGB_MAX = 0, 255

# AOI -- must match mosaic_sampler.py (EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

# ---------------------------------------------------------
# Web Mercator (EPSG:3857) forward projection -- same spherical
# formulas QGIS uses, so the grid lines up with mosaic_sampler.py
# ---------------------------------------------------------
EARTH_RADIUS_M = 6378137.0

def lonlat_to_3857(lon, lat):
    x = math.radians(lon) * EARTH_RADIUS_M
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_RADIUS_M
    return x, y

AOI_XMIN, AOI_YMIN = lonlat_to_3857(LNG_MIN, LAT_MIN)
AOI_XMAX, AOI_YMAX = lonlat_to_3857(LNG_MAX, LAT_MAX)
n_cols = int((AOI_XMAX - AOI_XMIN) / PATCH_SIZE_M)
n_rows = int((AOI_YMAX - AOI_YMIN) / PATCH_SIZE_M)
PIXEL_RES = PATCH_SIZE_M / PATCH_SIZE_PX  # 25m, matches mosaic_sampler.py

os.makedirs(LINEAR_PRED_OUT, exist_ok=True)
os.makedirs(SEGFORMER_PRED_OUT, exist_ok=True)
os.makedirs(MOSAIC_LINEAR_DIR, exist_ok=True)
os.makedirs(MOSAIC_SEGFORMER_DIR, exist_ok=True)

# ---------------------------------------------------------
# Device -- this script only does forward passes (no training), and
# only SegFormer's *backward* pass crashes on this machine's MPS
# backend (see CABIN_segformer_trainer.ipynb), so MPS should be safe
# here. Smoke-tested anyway, with a CPU fallback, for consistency with
# the rest of the project's scripts.
# ---------------------------------------------------------
if torch.cuda.is_available():
    DEVICE = torch.device("cuda")
elif torch.backends.mps.is_available():
    DEVICE = torch.device("mps")
else:
    DEVICE = torch.device("cpu")
print("device:", DEVICE)

# ---------------------------------------------------------
# Load both trained models
# ---------------------------------------------------------
coef_candidates = glob.glob(os.path.join(MODELS_DIR, "linear_regression_coefs_testrmse*.csv"))
if not coef_candidates:
    raise RuntimeError("No linear regression coefficients CSV found under models/ -- run linear_regression_trainer.ipynb first.")
COEFS_CSV = max(coef_candidates, key=os.path.getmtime)  # most recently trained
coefs = pd.read_csv(COEFS_CSV, index_col="feature")["coef"]
print(f"Loaded linear regression coefficients from {COEFS_CSV}")

ckpt_candidates = glob.glob(os.path.join(MODELS_DIR, "segformer_crown_closure_epoch*_testrmse*"))
if not ckpt_candidates:
    raise RuntimeError("No SegFormer checkpoint found under models/ -- train it first.")
SEGFORMER_CKPT = min(
    ckpt_candidates,
    key=lambda d: float(re.search(r"_testrmse([\d.]+)", os.path.basename(d)).group(1)),
)
model = SegformerForSemanticSegmentation.from_pretrained(SEGFORMER_CKPT).to(DEVICE).eval()
print(f"Loaded SegFormer checkpoint: {SEGFORMER_CKPT}")

try:
    smoke_x = torch.randn(BATCH_SIZE, 4, PATCH_SIZE_PX, PATCH_SIZE_PX, device=DEVICE)
    with torch.no_grad():
        _ = model(pixel_values=smoke_x).logits
except RuntimeError as e:
    print(f"{DEVICE} failed a forward smoke test, falling back to CPU: {e}")
    DEVICE = torch.device("cpu")
    model.to(DEVICE)
print("using device:", DEVICE)

# ---------------------------------------------------------
# Linear regression prediction -- per patch, numpy only. Reconstructs
# whatever feature set the model was fit with by reading the coefs
# Series' index, same trick as predict_crown_closure_linear() in
# CABIN_trainer.ipynb.
# ---------------------------------------------------------
def predict_linear(sat, dem):
    rgb_std  = (sat - RGB_MIN) / (RGB_MAX - RGB_MIN)
    elev_std = dem / 255.0
    pred = np.full(dem.shape, coefs.get("const", 0.0))
    for name, value in coefs.items():
        if name == "const":
            continue
        elif name == "r":
            pred = pred + value * rgb_std[:, :, 0]
        elif name == "g":
            pred = pred + value * rgb_std[:, :, 1]
        elif name == "b":
            pred = pred + value * rgb_std[:, :, 2]
        elif name == "elevation_m":
            pred = pred + value * elev_std
        elif name.startswith("elevation_m_deg"):
            d = int(name[len("elevation_m_deg"):])
            pred = pred + value * (elev_std ** d)
    return np.clip(pred, 0, 100).astype(np.uint8)

# ---------------------------------------------------------
# Whole-AOI mosaic canvases -- filled in as each patch is processed
# ---------------------------------------------------------
mosaic_width  = n_cols * PATCH_SIZE_PX
mosaic_height = n_rows * PATCH_SIZE_PX
linear_mosaic    = np.zeros((mosaic_height, mosaic_width), dtype=np.uint8)
segformer_mosaic = np.zeros((mosaic_height, mosaic_width), dtype=np.uint8)
print(f"Mosaic size: {mosaic_width} x {mosaic_height} px ({mosaic_width * mosaic_height / 1e6:.0f} MP each)")

# ---------------------------------------------------------
# Main loop -- one pass over all patches, both models, batched
# SegFormer inference (BATCH_SIZE at a time; linear regression is cheap
# enough to just run per-patch inside the same loop)
# ---------------------------------------------------------
patch_files = sorted(
    f for f in os.listdir(SAT_OUT) if f.startswith("patch_") and f.endswith(".png")
)
print(f"{len(patch_files)} patches")

t0 = time.time()
with torch.no_grad():
    for batch_start in range(0, len(patch_files), BATCH_SIZE):
        chunk = patch_files[batch_start:batch_start + BATCH_SIZE]

        sats, dems, xs, patch_ids = [], [], [], []
        for filename in chunk:
            patch_id = int(filename[len("patch_"):-len(".png")])
            sat = np.array(Image.open(os.path.join(SAT_OUT, filename)).convert("RGB"), dtype=np.float64)
            dem = np.array(Image.open(os.path.join(DEM_OUT, filename)).convert("L"), dtype=np.float64)
            sats.append(sat)
            dems.append(dem)
            patch_ids.append(patch_id)
            xs.append(np.concatenate([(sat / 255.0).transpose(2, 0, 1), (dem / 255.0)[None]], axis=0).astype(np.float32))

        X = torch.tensor(np.stack(xs), device=DEVICE)
        logits = model(pixel_values=X).logits
        preds = F.interpolate(logits, size=(PATCH_SIZE_PX, PATCH_SIZE_PX), mode="bilinear", align_corners=False)[:, 0]
        seg_preds = (preds.cpu().numpy() * 100).clip(0, 100).astype(np.uint8)

        for j, filename in enumerate(chunk):
            patch_id = patch_ids[j]
            col = patch_id % n_cols
            row = patch_id // n_cols  # 0 = southernmost row (matches mosaic_sampler.py's grid)

            lin_pred = predict_linear(sats[j], dems[j])
            seg_pred = seg_preds[j]

            Image.fromarray(lin_pred).save(os.path.join(LINEAR_PRED_OUT, filename))
            Image.fromarray(seg_pred).save(os.path.join(SEGFORMER_PRED_OUT, filename))

            # World row 0 is the southernmost patch -> bottom of the
            # mosaic -> highest output-row index (image row 0 = north).
            # World col increases eastward, same direction as image
            # columns, so no flip needed there.
            out_row = (n_rows - 1 - row) * PATCH_SIZE_PX
            out_col = col * PATCH_SIZE_PX
            linear_mosaic[out_row:out_row + PATCH_SIZE_PX, out_col:out_col + PATCH_SIZE_PX] = lin_pred
            segformer_mosaic[out_row:out_row + PATCH_SIZE_PX, out_col:out_col + PATCH_SIZE_PX] = seg_pred

        batches_done = batch_start // BATCH_SIZE + 1
        if batches_done % 50 == 0:
            done = batch_start + len(chunk)
            print(f"  {done}/{len(patch_files)} patches  ({time.time() - t0:.0f}s elapsed)")

print(f"Per-patch predictions done in {time.time() - t0:.0f}s")

# ---------------------------------------------------------
# Save mosaics -- PNG + world file + .prj. No GDAL needed in this
# environment; a world file is a plain-text sidecar that QGIS (and
# most GIS software) reads natively to georeference an otherwise plain
# raster image, without needing it baked into the file itself.
# ---------------------------------------------------------
PRJ_WKT_3857 = (
    'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",'
    'DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],'
    'PARAMETER["scale_factor",1],PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],UNIT["metre",1]]'
)

def save_georeferenced_png(array, path):
    Image.fromarray(array).save(path)
    worldfile_path = os.path.splitext(path)[0] + ".pgw"
    with open(worldfile_path, "w") as f:
        f.write(
            f"{PIXEL_RES}\n0\n0\n{-PIXEL_RES}\n"
            f"{AOI_XMIN + PIXEL_RES / 2}\n{AOI_YMAX - PIXEL_RES / 2}\n"
        )
    prj_path = os.path.splitext(path)[0] + ".prj"
    with open(prj_path, "w") as f:
        f.write(PRJ_WKT_3857)
    print(f"Saved {path}  (+ .pgw + .prj)")

save_georeferenced_png(linear_mosaic, MOSAIC_LINEAR_PATH)
save_georeferenced_png(segformer_mosaic, MOSAIC_SEGFORMER_PATH)

print(f"\nTotal time: {time.time() - t0:.0f}s = {(time.time() - t0) / 60:.1f} min")
