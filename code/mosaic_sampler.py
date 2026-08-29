import os
import numpy as np
from osgeo import gdal
from PyQt5.QtGui import QImage
from PyQt5.QtCore import QSize, QVariant
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsRectangle,
    QgsGeometry,
    QgsFeature,
    QgsField,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsMapSettings,
    QgsMapRendererSequentialJob,
)

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
N             = 9999   # max patches to generate per run
PATCH_SIZE_M  = 6400   # side length in metres
PATCH_SIZE_PX = 256    # output image size in pixels

# QGIS layer names
SAT_LAYER = "sentinel2_2024"

# Source raster paths
DEM_PATH      = "/Volumes/Spleen/CABIN/datasets/DEM.tif"
CANOPY_PATH   = "/Volumes/Spleen/CABIN/datasets/crown_closure_raster.tif"
CANOPY_NODATA = -9999
MASK_PATH     = "/Volumes/Spleen/CABIN/datasets/crown_closure_mask.tif"

# DEM normalization — fixed BC-wide range
DEM_ELEV_MIN = 0
DEM_ELEV_MAX = 4671    # Mt. Fairweather, highest point in BC

# Output directories
SAT_OUT         = "/Volumes/Spleen/CABIN/datasets/patches/satellite_imagery"
DEM_OUT         = "/Volumes/Spleen/CABIN/datasets/patches/elevation"
CANOPY_OUT      = "/Volumes/Spleen/CABIN/datasets/patches/crown_closure"
MASK_OUT        = "/Volumes/Spleen/CABIN/datasets/patches/crown_closure_mask"
FOOTPRINTS_PATH = "/Volumes/Spleen/CABIN/datasets/patches/patch_footprints.gpkg"

# AOI — same as all other scripts (EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

# ---------------------------------------------------------
# Convert AOI to EPSG:3857
# ---------------------------------------------------------
_src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
_dst_crs = QgsCoordinateReferenceSystem("EPSG:3857")
_xform   = QgsCoordinateTransform(_src_crs, _dst_crs, QgsProject.instance())

_bl = _xform.transform(QgsPointXY(LNG_MIN, LAT_MIN))
_tr = _xform.transform(QgsPointXY(LNG_MAX, LAT_MAX))

AOI_XMIN  = _bl.x()
AOI_XMAX  = _tr.x()
AOI_YMIN  = _bl.y()
AOI_YMAX  = _tr.y()
PIXEL_RES = PATCH_SIZE_M / PATCH_SIZE_PX

# Grid — floor() drops partial patches at the far edge
n_cols = int((AOI_XMAX - AOI_XMIN) / PATCH_SIZE_M)
n_rows = int((AOI_YMAX - AOI_YMIN) / PATCH_SIZE_M)
total  = n_cols * n_rows

# Patch IDs are deterministic: patch_id = row * n_cols + col
def patch_name(row, col):
    return f"patch_{row * n_cols + col:04d}.png"

# ---------------------------------------------------------
# Setup
# ---------------------------------------------------------
for d in (SAT_OUT, DEM_OUT, CANOPY_OUT, MASK_OUT):
    os.makedirs(d, exist_ok=True)

crs_3857 = QgsCoordinateReferenceSystem("EPSG:3857")

sat_layer = QgsProject.instance().mapLayersByName(SAT_LAYER)
if not sat_layer:
    raise RuntimeError(f"Layer '{SAT_LAYER}' not found in QGIS project.")
sat_layer = sat_layer[0]

# ---------------------------------------------------------
# GDAL patch extractor
# ---------------------------------------------------------
def extract_raster_patch(src_path, xmin, ymin, xmax, ymax):
    mem = "/vsimem/patch.tif"
    ds = gdal.Warp(
        mem, src_path,
        dstSRS="EPSG:3857",
        outputBounds=(xmin, ymin, xmax, ymax),
        xRes=PIXEL_RES, yRes=PIXEL_RES,
        resampleAlg="bilinear",
        format="GTiff",
    )
    if ds is None:
        return None
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    gdal.Unlink(mem)
    return arr

# ---------------------------------------------------------
# QGIS renderer — satellite XYZ layer
# ---------------------------------------------------------
def render_layer_patch(layer, xmin, ymin, xmax, ymax):
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(crs_3857)
    settings.setExtent(QgsRectangle(xmin, ymin, xmax, ymax))
    settings.setOutputSize(QSize(PATCH_SIZE_PX, PATCH_SIZE_PX))
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    return job.renderedImage()

# ---------------------------------------------------------
# Save helpers
# ---------------------------------------------------------
def save_gray_png(arr, path, lo, hi):
    if hi == lo:
        gray = np.zeros((PATCH_SIZE_PX, PATCH_SIZE_PX), dtype=np.uint8)
    else:
        gray = np.clip((arr - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    QImage(gray.tobytes(), PATCH_SIZE_PX, PATCH_SIZE_PX,
           PATCH_SIZE_PX, QImage.Format_Grayscale8).save(path, "PNG")

def save_canopy_png(arr, path):
    clean = np.where(arr == CANOPY_NODATA, 0, arr)
    clean = np.clip(clean, 0, 100).astype(np.uint8)
    QImage(clean.tobytes(), PATCH_SIZE_PX, PATCH_SIZE_PX,
           PATCH_SIZE_PX, QImage.Format_Grayscale8).save(path, "PNG")

def save_mask_png(arr, path):
    # 0 = null/no VRI data, 1 = valid → scale to 0/255 for visibility
    scaled = np.where(arr > 0, 255, 0).astype(np.uint8)
    QImage(scaled.tobytes(), PATCH_SIZE_PX, PATCH_SIZE_PX,
           PATCH_SIZE_PX, QImage.Format_Grayscale8).save(path, "PNG")

# ---------------------------------------------------------
# Pre-flight check
# ---------------------------------------------------------
print("Pre-flight check...")
_t = extract_raster_patch(CANOPY_PATH, AOI_XMIN, AOI_YMIN,
                           AOI_XMIN + PATCH_SIZE_M, AOI_YMIN + PATCH_SIZE_M)
if _t is None:
    raise RuntimeError(f"GDAL cannot read {CANOPY_PATH}: {gdal.GetLastErrorMsg()}")
print(f"  Canopy OK  range=[{int(_t.min())}, {int(_t.max())}]")

_t = extract_raster_patch(DEM_PATH, AOI_XMIN, AOI_YMIN,
                           AOI_XMIN + PATCH_SIZE_M, AOI_YMIN + PATCH_SIZE_M)
if _t is None:
    raise RuntimeError(f"GDAL cannot read {DEM_PATH}: {gdal.GetLastErrorMsg()}")
print(f"  DEM OK  range=[{int(_t.min())}, {int(_t.max())}]")

_t = extract_raster_patch(MASK_PATH, AOI_XMIN, AOI_YMIN,
                           AOI_XMIN + PATCH_SIZE_M, AOI_YMIN + PATCH_SIZE_M)
if _t is None:
    raise RuntimeError(f"GDAL cannot read {MASK_PATH}: {gdal.GetLastErrorMsg()}")
print(f"  Mask OK  unique values={sorted(set(_t.flat))}")

# ---------------------------------------------------------
# Grid summary
# ---------------------------------------------------------
print(f"\nGrid    : {n_cols} cols × {n_rows} rows = {total} patches")
print(f"This run : up to {N} patches")

# ---------------------------------------------------------
# Grid iteration — left to right, bottom to top
# Stops after N patches or when the grid is full
# ---------------------------------------------------------
saved       = 0
patch_boxes = []

for row in range(n_rows):
    if saved >= N:
        break
    for col in range(n_cols):
        if saved >= N:
            break

        xmin = AOI_XMIN + col * PATCH_SIZE_M
        xmax = xmin + PATCH_SIZE_M
        ymin = AOI_YMIN + row * PATCH_SIZE_M
        ymax = ymin + PATCH_SIZE_M
        name = patch_name(row, col)

        canopy_arr = extract_raster_patch(CANOPY_PATH, xmin, ymin, xmax, ymax)
        if canopy_arr is None:
            canopy_arr = np.zeros((PATCH_SIZE_PX, PATCH_SIZE_PX), dtype=np.float32)

        dem_arr = extract_raster_patch(DEM_PATH, xmin, ymin, xmax, ymax)
        if dem_arr is None:
            dem_arr = np.zeros((PATCH_SIZE_PX, PATCH_SIZE_PX), dtype=np.int16)

        mask_arr = extract_raster_patch(MASK_PATH, xmin, ymin, xmax, ymax)
        if mask_arr is None:
            mask_arr = np.zeros((PATCH_SIZE_PX, PATCH_SIZE_PX), dtype=np.uint8)

        sat_img = render_layer_patch(sat_layer, xmin, ymin, xmax, ymax)

        sat_img.save(os.path.join(SAT_OUT, name), "PNG")
        save_gray_png(dem_arr, os.path.join(DEM_OUT, name), DEM_ELEV_MIN, DEM_ELEV_MAX)
        save_canopy_png(canopy_arr, os.path.join(CANOPY_OUT, name))
        save_mask_png(mask_arr, os.path.join(MASK_OUT, name))

        patch_boxes.append((row * n_cols + col, name, xmin, ymin, xmax, ymax))
        saved += 1

        if saved % 10 == 0:
            print(f"  {saved} / {total} patches  ({saved*100//total}%)")

# ---------------------------------------------------------
# Final status
# ---------------------------------------------------------
print(f"\n{saved} / {total} patches saved this run")

if saved == total:
    print("Mosaic complete — full AOI covered.")
else:
    print(f"{total - saved} remaining — running again will restart from scratch.")

# ---------------------------------------------------------
# Footprints layer — fresh file, fresh layer, every run
# ---------------------------------------------------------
if patch_boxes:
    mem_layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "footprints", "memory")
    prov = mem_layer.dataProvider()
    prov.addAttributes([
        QgsField("patch_id", QVariant.Int),
        QgsField("filename", QVariant.String),
        QgsField("col",      QVariant.Int),
        QgsField("row",      QVariant.Int),
    ])
    mem_layer.updateFields()

    feats = []
    for patch_id, filename, xmin, ymin, xmax, ymax in patch_boxes:
        col = patch_id % n_cols
        row = patch_id // n_cols
        feat = QgsFeature(mem_layer.fields())
        feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax)))
        feat.setAttributes([patch_id, filename, col, row])
        feats.append(feat)
    prov.addFeatures(feats)

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName   = "GPKG"
    options.layerName    = "patch_footprints"
    options.fileEncoding = "UTF-8"
    QgsVectorFileWriter.writeAsVectorFormatV3(
        mem_layer, FOOTPRINTS_PATH,
        QgsProject.instance().transformContext(), options
    )

    fl = QgsVectorLayer(
        f"{FOOTPRINTS_PATH}|layername=patch_footprints", "patch_footprints", "ogr"
    )
    QgsProject.instance().addMapLayer(fl)
    print(f"Loaded 'patch_footprints' layer — {len(feats)} polygons this run")
