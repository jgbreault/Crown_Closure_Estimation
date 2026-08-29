import os
from qgis.core import (
    QgsProject,
    QgsRectangle,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsWkbTypes,
    QgsFeature,
    QgsFields
)

# ---------------------------------------------------------
# 1. Define bounding box coordinates (EPSG:4326 / WGS 84)
# ---------------------------------------------------------
LAT_A = 49
LAT_B = 51
LNG_A = -119
LNG_B = -125

LAT_MIN, LAT_MAX = min(LAT_A, LAT_B), max(LAT_A, LAT_B)
LNG_MIN, LNG_MAX = min(LNG_A, LNG_B), max(LNG_A, LNG_B)

LAYER_NAME   = "VEG_COMP_LYR_R1_POLY"
GDB_PATH     = "/Volumes/Spleen/CABIN/datasets/VEG_COMP_LYR_R1_POLY_2025.gdb"
KEEP_FIELDS  = ["CROWN_CLOSURE", "CROWN_CLOSURE_CLASS_CD"]
OUTPUT_PATH  = "/Volumes/Spleen/CABIN/datasets/study_area.gpkg"
OUTPUT_LAYER = "study_area"

# ---------------------------------------------------------
# 2. Get the target layer
# ---------------------------------------------------------
layer = QgsVectorLayer(f"{GDB_PATH}|layername={LAYER_NAME}", LAYER_NAME, "ogr")
if not layer.isValid():
    raise ValueError(f"Could not load layer '{LAYER_NAME}' from '{GDB_PATH}'.")

# ---------------------------------------------------------
# 3. Build bbox in layer's native CRS (for filtering) and in
#    EPSG:3857 (for the output). Features are reprojected on save.
# ---------------------------------------------------------
src_crs   = QgsCoordinateReferenceSystem("EPSG:4326")
layer_crs = layer.crs()
out_crs   = QgsCoordinateReferenceSystem("EPSG:3857")

bbox_rect = QgsRectangle(LNG_MIN, LAT_MIN, LNG_MAX, LAT_MAX)

# bbox in layer's native CRS — used for the spatial filter
bbox_native = QgsGeometry.fromRect(bbox_rect)
bbox_native.transform(QgsCoordinateTransform(src_crs, layer_crs, QgsProject.instance()))

# bbox in EPSG:3857 — used for exact intersection check after reprojection
bbox_3857 = QgsGeometry.fromRect(bbox_rect)
bbox_3857.transform(QgsCoordinateTransform(src_crs, out_crs, QgsProject.instance()))

to_3857 = QgsCoordinateTransform(layer_crs, out_crs, QgsProject.instance())

# ---------------------------------------------------------
# 4. Filter features & fetch only required attributes
# ---------------------------------------------------------
layer_fields = layer.fields()
field_indices = [layer_fields.indexOf(f) for f in KEEP_FIELDS if layer_fields.indexOf(f) != -1]

request = (
    QgsFeatureRequest()
    .setFilterRect(bbox_native.boundingBox())
    .setSubsetOfAttributes(field_indices)
)

subset_fields = QgsFields()
for idx in field_indices:
    subset_fields.append(layer_fields.at(idx))

matching_features = []
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
    new_feat = QgsFeature(subset_fields)
    new_feat.setGeometry(clipped)
    new_feat.setAttributes([feat[f] for f in KEEP_FIELDS])
    matching_features.append(new_feat)

# ---------------------------------------------------------
# 5. Build in-memory layer
# ---------------------------------------------------------
geom_type = QgsWkbTypes.displayString(layer.wkbType())
uri = f"{geom_type}?crs={out_crs.authid()}"
subset_layer = QgsVectorLayer(uri, OUTPUT_LAYER, "memory")

prov = subset_layer.dataProvider()
prov.addAttributes(subset_fields.toList())
subset_layer.updateFields()
prov.addFeatures(matching_features)
subset_layer.updateExtents()

# ---------------------------------------------------------
# 6. Save to GeoPackage (overwrite) and add to project
# ---------------------------------------------------------
if os.path.exists(OUTPUT_PATH):
    os.remove(OUTPUT_PATH)

options = QgsVectorFileWriter.SaveVectorOptions()
options.driverName = "GPKG"
options.layerName  = OUTPUT_LAYER
options.fileEncoding = "UTF-8"

error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
    subset_layer, OUTPUT_PATH, QgsProject.instance().transformContext(), options
)
if error != QgsVectorFileWriter.NoError:
    raise RuntimeError(f"Failed to write GeoPackage: {msg}")

saved_layer = QgsVectorLayer(f"{OUTPUT_PATH}|layername={OUTPUT_LAYER}", OUTPUT_LAYER, "ogr")
QgsProject.instance().addMapLayer(saved_layer)

print(f"Saved {len(matching_features)} features to '{OUTPUT_PATH}' and added to project.")