import processing
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
STUDY_AREA_PATH = "/Volumes/Spleen/CABIN/datasets/study_area.gpkg"
STUDY_AREA_NAME = "study_area"
BURN_FIELD      = "CROWN_CLOSURE"
PIXEL_SIZE      = 25          # metres
NO_DATA         = -9999
OUTPUT_PATH     = "/Volumes/Spleen/CABIN/datasets/crown_closure_raster.tif"

# ---------------------------------------------------------
# 1. Load source layer
# ---------------------------------------------------------
layer = QgsVectorLayer(f"{STUDY_AREA_PATH}|layername={STUDY_AREA_NAME}", STUDY_AREA_NAME, "ogr")
if not layer.isValid():
    raise ValueError(f"Could not load '{STUDY_AREA_NAME}' from '{STUDY_AREA_PATH}'. Run crown_canopy_cropper.py first.")

# ---------------------------------------------------------
# 2. Rasterize CROWN_CLOSURE onto a regular grid
# ---------------------------------------------------------
extent = layer.extent()
extent_str = f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()} [{layer.crs().authid()}]"

result = processing.run("gdal:rasterize", {
    "INPUT":        layer,
    "FIELD":        BURN_FIELD,
    "BURN":         0,
    "USE_Z":        False,
    "UNITS":        1,              # georeferenced units
    "WIDTH":        PIXEL_SIZE,
    "HEIGHT":       PIXEL_SIZE,
    "EXTENT":       extent_str,
    "NODATA":       NO_DATA,
    "OPTIONS":      "COMPRESS=LZW",
    "DATA_TYPE":    5,              # Float32
    "INIT":         None,
    "INVERT":       False,
    "EXTRA":        "",
    "OUTPUT":       OUTPUT_PATH,
})

# ---------------------------------------------------------
# 3. Add raster to project
# ---------------------------------------------------------
raster_layer = QgsRasterLayer(result["OUTPUT"], "crown_closure")
if not raster_layer.isValid():
    raise ValueError(f"Raster output is invalid: {result['OUTPUT']}")

QgsProject.instance().addMapLayer(raster_layer)
print(f"Raster added: {result['OUTPUT']}")
