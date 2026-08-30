import os
import zipfile
import urllib.request
from osgeo import gdal, ogr, osr
import processing
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsFeatureRequest,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsRasterLayer,
)
from PyQt5.QtCore import QVariant

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
GDB_ZIP_URL  = "https://pub.data.gov.bc.ca/datasets/02dba161-fdb7-48ae-a4bb-bd6ef017c36d/current/VEG_COMP_LYR_R1_POLY_2025.gdb.zip"
GDB_NAME     = "VEG_COMP_LYR_R1_POLY_2025.gdb"
LAYER_NAME   = "VEG_COMP_LYR_R1_POLY"
DATASETS_DIR = "/Volumes/Spleen/CABIN/datasets"
GDB_PATH     = os.path.join(DATASETS_DIR, GDB_NAME)

KEEP_FIELDS  = ["CROWN_CLOSURE"]
BURN_FIELD   = "CROWN_CLOSURE"
PIXEL_SIZE   = 25
NO_DATA      = -9999

# AOI — same as cropper (EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

GPKG_PATH   = os.path.join(DATASETS_DIR, "crown_closure_polygons.gpkg")
MASK_DIR    = os.path.join(DATASETS_DIR, "crown_closure_mask")
RASTER_DIR  = os.path.join(DATASETS_DIR, "crown_closure_raster")
MASK_PATH   = os.path.join(MASK_DIR, "crown_closure_mask.tif")
RASTER_PATH = os.path.join(RASTER_DIR, "crown_closure_raster.tif")
os.makedirs(MASK_DIR, exist_ok=True)
os.makedirs(RASTER_DIR, exist_ok=True)

# ---------------------------------------------------------
# 1. Download GDB if not present
# ---------------------------------------------------------
if os.path.exists(GDB_PATH):
    print(f"GDB found at {GDB_PATH} — skipping download.")
else:
    zip_path = GDB_PATH + ".zip"
    tmp_path = zip_path + ".part"
    print(f"GDB not found. Downloading (~6 GB) ...")

    def progress(block_count, block_size, total_size):
        downloaded = block_count * block_size
        if total_size > 0 and block_count % 500 == 0:
            pct = downloaded / total_size * 100
            gb  = downloaded / 1_000_000_000
            print(f"  {gb:.2f} GB / {total_size/1_000_000_000:.2f} GB ({pct:.1f}%)")

    urllib.request.urlretrieve(GDB_ZIP_URL, tmp_path, reporthook=progress)
    os.rename(tmp_path, zip_path)
    print("Download complete. Extracting...")

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(DATASETS_DIR)
    os.remove(zip_path)
    print(f"Extracted to {GDB_PATH}")

# ---------------------------------------------------------
# 2. Load GDB layer
# ---------------------------------------------------------
layer = QgsVectorLayer(f"{GDB_PATH}|layername={LAYER_NAME}", LAYER_NAME, "ogr")
if not layer.isValid():
    raise RuntimeError(f"Could not load '{LAYER_NAME}' from '{GDB_PATH}'.")

# ---------------------------------------------------------
# 3. Crop to AOI (same logic as crown_canopy_cropper.py)
# ---------------------------------------------------------
src_crs   = QgsCoordinateReferenceSystem("EPSG:4326")
layer_crs = layer.crs()
out_crs   = QgsCoordinateReferenceSystem("EPSG:3857")

bbox_rect = QgsGeometry.fromWkt(
    f"POLYGON(({LNG_MIN} {LAT_MIN},{LNG_MAX} {LAT_MIN},"
    f"{LNG_MAX} {LAT_MAX},{LNG_MIN} {LAT_MAX},{LNG_MIN} {LAT_MIN}))"
)

bbox_native = QgsGeometry(bbox_rect)
bbox_native.transform(QgsCoordinateTransform(src_crs, layer_crs, QgsProject.instance()))

bbox_3857 = QgsGeometry(bbox_rect)
bbox_3857.transform(QgsCoordinateTransform(src_crs, out_crs, QgsProject.instance()))

to_3857 = QgsCoordinateTransform(layer_crs, out_crs, QgsProject.instance())

layer_fields  = layer.fields()
field_indices = [layer_fields.indexOf(f) for f in KEEP_FIELDS if layer_fields.indexOf(f) != -1]
request       = (
    QgsFeatureRequest()
    .setFilterRect(bbox_native.boundingBox())
    .setSubsetOfAttributes(field_indices)
)

out_fields = QgsFields()
out_fields.append(QgsField("CROWN_CLOSURE", QVariant.Int))

mem_layer = QgsVectorLayer(
    f"MultiPolygon?crs={out_crs.authid()}", "study_area", "memory"
)
prov = mem_layer.dataProvider()
prov.addAttributes(out_fields.toList())
mem_layer.updateFields()

print("Cropping features to AOI...")
matching = []
for feat in layer.getFeatures(request):
    if not feat.hasGeometry():
        continue
    geom = QgsGeometry(feat.geometry())
    geom.transform(to_3857)
    if not geom.intersects(bbox_3857):
        continue
    clipped = geom.intersection(bbox_3857)
    if clipped.isEmpty():
        continue
    new_feat = QgsFeature(out_fields)
    new_feat.setGeometry(clipped)
    new_feat.setAttributes([feat[f] for f in KEEP_FIELDS])
    matching.append(new_feat)

prov.addFeatures(matching)
mem_layer.updateExtents()
print(f"  {len(matching)} features after clipping")

# ---------------------------------------------------------
# 4. Save to GeoPackage
# ---------------------------------------------------------
if os.path.exists(GPKG_PATH):
    os.remove(GPKG_PATH)

options              = QgsVectorFileWriter.SaveVectorOptions()
options.driverName   = "GPKG"
options.layerName    = "study_area"
options.fileEncoding = "UTF-8"

error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
    mem_layer, GPKG_PATH, QgsProject.instance().transformContext(), options
)
if error != QgsVectorFileWriter.NoError:
    raise RuntimeError(f"Failed to write GeoPackage: {msg}")

print(f"Saved vector → {GPKG_PATH}")

# ---------------------------------------------------------
# 5. Rasterize CROWN_CLOSURE (same logic as canopy_rasterizer.py)
# ---------------------------------------------------------
vec_layer  = QgsVectorLayer(f"{GPKG_PATH}|layername=study_area", "study_area", "ogr")
extent     = vec_layer.extent()
extent_str = (
    f"{extent.xMinimum()},{extent.xMaximum()},"
    f"{extent.yMinimum()},{extent.yMaximum()} [{out_crs.authid()}]"
)

result = processing.run("gdal:rasterize", {
    "INPUT":     vec_layer,
    "FIELD":     BURN_FIELD,
    "BURN":      0,
    "USE_Z":     False,
    "UNITS":     1,
    "WIDTH":     PIXEL_SIZE,
    "HEIGHT":    PIXEL_SIZE,
    "EXTENT":    extent_str,
    "NODATA":    NO_DATA,
    "OPTIONS":   "COMPRESS=LZW",
    "DATA_TYPE": 5,
    "INIT":      None,
    "INVERT":    False,
    "EXTRA":     "",
    "OUTPUT":    RASTER_PATH,
})

print(f"Saved raster → {RASTER_PATH}")

# ---------------------------------------------------------
# 6. Load into QGIS
# ---------------------------------------------------------
raster_layer = QgsRasterLayer(result["OUTPUT"], "crown_closure")
if not raster_layer.isValid():
    raise RuntimeError(f"Raster invalid: {result['OUTPUT']}")

QgsProject.instance().addMapLayer(raster_layer)
print("Done — 'crown_closure' added to QGIS project.")

# ---------------------------------------------------------
# 7. Build VRI validity mask via OGR/GDAL directly
#    White (1) = CROWN_CLOSURE not null, Black (0) = null or no polygon
# ---------------------------------------------------------
x_min  = extent.xMinimum()
y_max  = extent.yMaximum()
n_px_x = int(round((extent.xMaximum() - x_min) / PIXEL_SIZE))
n_px_y = int(round((y_max - extent.yMinimum()) / PIXEL_SIZE))

vec_ds  = ogr.Open(GPKG_PATH)
ogr_lyr = vec_ds.GetLayerByName("study_area")
ogr_lyr.SetAttributeFilter("CROWN_CLOSURE IS NOT NULL")
print(f"  Features with non-null CROWN_CLOSURE: {ogr_lyr.GetFeatureCount()}")

drv     = gdal.GetDriverByName("GTiff")
mask_ds = drv.Create(MASK_PATH, n_px_x, n_px_y, 1, gdal.GDT_Byte, ["COMPRESS=LZW"])
mask_ds.SetGeoTransform([x_min, PIXEL_SIZE, 0, y_max, 0, -PIXEL_SIZE])
srs_out = osr.SpatialReference()
srs_out.ImportFromEPSG(3857)
mask_ds.SetProjection(srs_out.ExportToWkt())

band = mask_ds.GetRasterBand(1)
band.Fill(0)
band.FlushCache()

gdal.RasterizeLayer(mask_ds, [1], ogr_lyr, burn_values=[1])
mask_ds.FlushCache()
mask_ds = None
vec_ds  = None

mask_layer = QgsRasterLayer(MASK_PATH, "crown_closure_mask")
if not mask_layer.isValid():
    raise RuntimeError(f"Mask raster invalid: {MASK_PATH}")
QgsProject.instance().addMapLayer(mask_layer)
print(f"Saved mask → {MASK_PATH}  ('crown_closure_mask' added to QGIS project)")
