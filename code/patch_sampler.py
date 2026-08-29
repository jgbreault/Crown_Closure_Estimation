import os
import random
from qgis.core import (
    QgsProject,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapSettings,
    QgsMapRendererSequentialJob,
)
from PyQt5.QtCore import QSize

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
N            = 1     # number of patch pairs to generate
IMG_SIZE_PX  = 256   # side length in pixels
PIXEL_SIZE_M = 25    # metres per pixel — sets real-world patch size
RANDOM_SEED  = 42

CANOPY_LAYER = "crown_closure"
SAT_LAYER    = "ESRI_world_imagery_2024-08-15"

CANOPY_OUT   = "/Volumes/Spleen/CABIN/images/crown_coverage"
SAT_OUT      = "/Volumes/Spleen/CABIN/images/satellite_imagery"

# AOI (same bounding box as crown_canopy_cropper.py, EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

# ---------------------------------------------------------
# 1. Get both layers
# ---------------------------------------------------------
def get_layer(name):
    layers = QgsProject.instance().mapLayersByName(name)
    if not layers:
        raise ValueError(f"Layer '{name}' not found in project.")
    return layers[0]

canopy_layer = get_layer(CANOPY_LAYER)
sat_layer    = get_layer(SAT_LAYER)

os.makedirs(CANOPY_OUT, exist_ok=True)
os.makedirs(SAT_OUT,    exist_ok=True)

# ---------------------------------------------------------
# 2. Reproject AOI to layer CRS
# ---------------------------------------------------------
src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
dst_crs = QgsCoordinateReferenceSystem("EPSG:3857")
xform   = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())

bl = xform.transform(LNG_MIN, LAT_MIN)
tr = xform.transform(LNG_MAX, LAT_MAX)

aoi_x_min = min(bl.x(), tr.x())
aoi_y_min = min(bl.y(), tr.y())
aoi_x_max = max(bl.x(), tr.x())
aoi_y_max = max(bl.y(), tr.y())

patch_m = IMG_SIZE_PX * PIXEL_SIZE_M

# ---------------------------------------------------------
# 3. Sample N random positions and render both layers
# ---------------------------------------------------------
def render_patch(layer, extent):
    settings = QgsMapSettings()
    settings.setDestinationCrs(dst_crs)
    settings.setOutputSize(QSize(IMG_SIZE_PX, IMG_SIZE_PX))
    settings.setLayers([layer])
    settings.setExtent(extent)
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    return job.renderedImage()

random.seed(RANDOM_SEED)

for i in range(N):
    x = random.uniform(aoi_x_min, aoi_x_max - patch_m)
    y = random.uniform(aoi_y_min, aoi_y_max - patch_m)
    extent = QgsRectangle(x, y, x + patch_m, y + patch_m)

    fname = f"patch_{i:04d}.png"

    render_patch(canopy_layer, extent).save(os.path.join(CANOPY_OUT, fname), "PNG")
    render_patch(sat_layer,    extent).save(os.path.join(SAT_OUT,    fname), "PNG")

    print(f"[{i + 1}/{N}] {fname}")

print(f"Done. {N} pair(s) saved.")
