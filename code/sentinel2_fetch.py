from qgis.core import QgsRasterLayer, QgsProject

TILE_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg"

url_encoded = f"type=xyz&url={TILE_URL}&zmax=19&zmin=0"
layer = QgsRasterLayer(url_encoded, "sentinel2_2024", "wms")

if not layer.isValid():
    raise RuntimeError("Failed to load XYZ layer — check the tile URL.")

QgsProject.instance().addMapLayer(layer)
print("Done — 'sentinel2_2024' added to QGIS project.")
