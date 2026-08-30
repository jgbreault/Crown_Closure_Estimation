import os
import csv
import math
from PIL import Image

# ---------------------------------------------------------
# Config — same output dirs and grid as generate_patch_images.py
# ---------------------------------------------------------
SAT_OUT    = "/Volumes/Spleen/CABIN/datasets/patches/satellite_imagery"
DEM_OUT    = "/Volumes/Spleen/CABIN/datasets/patches/elevation"
CANOPY_OUT = "/Volumes/Spleen/CABIN/datasets/patches/crown_closure"
MASK_OUT   = "/Volumes/Spleen/CABIN/datasets/patches/crown_closure_mask"

OUT_DIR = "/Volumes/Spleen/CABIN/datasets/patches/patch_summaries"

PATCH_SIZE_PX = 256
PATCH_SIZE_M  = 6400

# AOI — must match generate_patch_images.py (EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

# DEM patches are stored as a 0-255 brightness scaled over this fixed
# range (see generate_patch_images.py) — decode back to metres here.
DEM_ELEV_MIN = 0
DEM_ELEV_MAX = 4671

# ---------------------------------------------------------
# Web Mercator (EPSG:3857) <-> lon/lat — same spherical formulas
# QGIS uses for this CRS, so the grid lines up with generate_patch_images.py
# ---------------------------------------------------------
EARTH_RADIUS_M = 6378137.0

def lonlat_to_3857(lon, lat):
    x = math.radians(lon) * EARTH_RADIUS_M
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_RADIUS_M
    return x, y

def mercator_3857_to_lonlat(x, y):
    lon = math.degrees(x / EARTH_RADIUS_M)
    lat = math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS_M)) - math.pi / 2)
    return lon, lat

AOI_XMIN, AOI_YMIN = lonlat_to_3857(LNG_MIN, LAT_MIN)
AOI_XMAX, AOI_YMAX = lonlat_to_3857(LNG_MAX, LAT_MAX)
n_cols = int((AOI_XMAX - AOI_XMIN) / PATCH_SIZE_M)

# ---------------------------------------------------------
# Gather patch filenames — repos are kept in sync by filename
# ---------------------------------------------------------
patch_files = sorted(
    f for f in os.listdir(SAT_OUT) if f.startswith("patch_") and f.endswith(".png")
)
total_patches = len(patch_files)
print(f"Found {total_patches} patches -> {total_patches * PATCH_SIZE_PX * PATCH_SIZE_PX:,} pixel rows")

FIELDS = ["patch_id", "x", "y", "latitude", "longitude", "elevation_m", "r", "g", "b", "mask", "crown_closure"]

os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------
# One CSV per patch — every pixel of that patch, written to
# datasets/patches/patch_summaries/patch_XXXX.csv
# ---------------------------------------------------------
for i, filename in enumerate(patch_files):
    patch_id = int(filename[len("patch_"):-len(".png")])
    col = patch_id % n_cols
    row = patch_id // n_cols
    patch_xmin = AOI_XMIN + col * PATCH_SIZE_M
    patch_ymin = AOI_YMIN + row * PATCH_SIZE_M

    sat_px  = Image.open(os.path.join(SAT_OUT, filename)).convert("RGB").load()
    dem_px  = Image.open(os.path.join(DEM_OUT, filename)).convert("L").load()
    can_px  = Image.open(os.path.join(CANOPY_OUT, filename)).convert("L").load()
    mask_px = Image.open(os.path.join(MASK_OUT, filename)).convert("L").load()

    out_path = os.path.join(OUT_DIR, filename.replace(".png", ".csv"))
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)

        for y in range(PATCH_SIZE_PX):
            # Pixel y grows downward while northing grows upward, so
            # flip y when converting to world coordinates.
            world_y = patch_ymin + (PATCH_SIZE_PX - y - 0.5) / PATCH_SIZE_PX * PATCH_SIZE_M
            for x in range(PATCH_SIZE_PX):
                world_x = patch_xmin + (x + 0.5) / PATCH_SIZE_PX * PATCH_SIZE_M
                lon, lat = mercator_3857_to_lonlat(world_x, world_y)

                r, g, b = sat_px[x, y]
                dem_raw = dem_px[x, y]
                elevation_m = dem_raw / 255 * (DEM_ELEV_MAX - DEM_ELEV_MIN) + DEM_ELEV_MIN
                crown_closure = can_px[x, y]  # already 0-100, no scaling needed
                mask = 1 if mask_px[x, y] > 0 else 0

                writer.writerow([
                    patch_id, x, y, round(lat, 6), round(lon, 6),
                    round(elevation_m, 1), r, g, b, mask, crown_closure,
                ])

    if (i + 1) % 10 == 0:
        print(f"  {i + 1}/{total_patches} patches written")

print(f"Saved {total_patches} per-patch CSVs -> {OUT_DIR}")
