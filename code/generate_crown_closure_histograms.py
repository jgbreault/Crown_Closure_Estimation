# Optional diagnostic plots over the VRI polygons clipped to the AOI --
# reads crown_closure_polygons.gpkg, written by generate_crown_closure.py,
# so run that first. Not used by any downstream step; purely descriptive.
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from osgeo import ogr

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
GPKG_PATH  = "/Volumes/Spleen/CABIN/datasets/crown_closure_polygons.gpkg"
LAYER_NAME = "study_area"
PLOTS_DIR  = "/Volumes/Spleen/CABIN/plots"

os.makedirs(PLOTS_DIR, exist_ok=True)

# ---------------------------------------------------------
# Load polygons
# ---------------------------------------------------------
ds    = ogr.Open(GPKG_PATH)
layer = ds.GetLayerByName(LAYER_NAME)

total_polygons = layer.GetFeatureCount()
print(f"Total polygons in AOI: {total_polygons}")

# Area is a geometric property independent of CROWN_CLOSURE, so every
# polygon is included in the area histogram — even ones with a NULL
# CROWN_CLOSURE. Crown closure values with NULL are dropped from the
# crown closure histogram since there's no numeric value to bin.
areas          = []  # km², includes NULL-CROWN_CLOSURE polygons
crown_closures = []  # %, excludes NULL CROWN_CLOSURE

for feat in layer:
    geom = feat.GetGeometryRef()
    areas.append(geom.GetArea() / 1_000_000)  # m² -> km²
    cc = feat.GetField("CROWN_CLOSURE")
    if cc is not None:
        crown_closures.append(cc)

ds = None

null_cc_count = total_polygons - len(crown_closures)

# ---------------------------------------------------------
# Polygon area histogram (log-log — areas span several orders
# of magnitude, so linear bins/axes would bury the small polygons)
# ---------------------------------------------------------
area_avg = sum(areas) / len(areas)

zero_area_count = sum(1 for a in areas if a <= 0)
loggable_areas  = [a for a in areas if a > 0]
if zero_area_count:
    print(f"  {zero_area_count} zero-area polygon(s) excluded from the log area histogram")

log_bins = np.logspace(
    np.log10(min(loggable_areas)), np.log10(max(loggable_areas)), 21
)

fig, ax = plt.subplots(figsize=(8, 5))
ax.hist(loggable_areas, bins=log_bins)
ax.axvline(area_avg, color="red", linestyle="--", label=f"Average = {area_avg:,.3f} km²")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_title(
    "Polygon Area Distribution\n"
    f"({len(loggable_areas)} of {total_polygons} polygons shown, "
    "includes polygons with NULL CROWN_CLOSURE)"
)
ax.set_xlabel("Area (km², log scale)")
ax.set_ylabel("Count (log scale)")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "polygon_area_histogram.png"))
plt.close(fig)

# ---------------------------------------------------------
# Crown closure value histogram
# ---------------------------------------------------------
cc_avg = sum(crown_closures) / len(crown_closures)

fig, ax = plt.subplots(figsize=(8, 5))
ax.hist(crown_closures, bins=range(0, 105, 5))
ax.axvline(cc_avg, color="red", linestyle="--", label=f"Average = {cc_avg:.1f}%")
ax.set_title(
    "Crown Closure Value Distribution\n"
    f"({len(crown_closures)} of {total_polygons} polygons shown, "
    f"{null_cc_count} with NULL CROWN_CLOSURE excluded)"
)
ax.set_xlabel("Crown Closure (%)")
ax.set_ylabel("Count")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS_DIR, "crown_closure_histogram.png"))
plt.close(fig)

print(f"Saved histograms -> {PLOTS_DIR}")
