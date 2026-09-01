# Adds EOX's s2cloudless 2025 mosaic (a cloud-free, global Sentinel-2 RGB
# composite, https://s2maps.eu/) to the current QGIS project as an XYZ
# tile layer, so it can be sampled patch-by-patch later.
from qgis.core import QgsRasterLayer, QgsProject

TILE_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg"

# QGIS has no dedicated "XYZ tile" provider -- "wms" is the provider that
# understands the type=xyz URL scheme, even though this isn't a real WMS.
url_encoded = f"type=xyz&url={TILE_URL}&zmax=19&zmin=0"
layer = QgsRasterLayer(url_encoded, "sentinel2_2025", "wms")

if not layer.isValid():
    raise RuntimeError("Failed to load XYZ layer — check the tile URL.")

QgsProject.instance().addMapLayer(layer)
print("Done — 'sentinel2_2025' added to QGIS project.")
