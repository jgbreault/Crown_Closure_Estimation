import os
import urllib.request
import numpy as np
from osgeo import gdal, osr
from PyQt5.QtCore import QByteArray
from PyQt5.QtGui import QImage
from qgis.core import QgsProject, QgsRasterLayer

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
WMS_URL = "https://geo.weather.gc.ca/geomet-climate"

# AOI — same as cropper (EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

IMG_WIDTH  = 1200   # 3:1 matches AOI aspect ratio (6° lng × 2° lat)
IMG_HEIGHT = 400

LAYERS = [
    ("CANGRD.ANO.TM_SUMMER", "temp_summer_absolute_anomaly.tif",  "CANGRD Summer Temp Anomaly"),
    ("CANGRD.ANO.PR_ANNUAL", "precip_annual_relative_anomaly.tif", "CANGRD Annual Precip Anomaly"),
]

OUT_DIR = "/Volumes/Spleen/CABIN/datasets"

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def fetch_wms(layer_name):
    params = (
        f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS={layer_name}"
        f"&SRS=EPSG:4326"
        f"&BBOX={LNG_MIN},{LAT_MIN},{LNG_MAX},{LAT_MAX}"
        f"&WIDTH={IMG_WIDTH}&HEIGHT={IMG_HEIGHT}"
        f"&FORMAT=image/png"
        f"&STYLES="
    )
    with urllib.request.urlopen(WMS_URL + params) as r:
        return r.read()

def to_greyscale_array(data):
    img = QImage()
    img.loadFromData(QByteArray(data))
    if img.isNull():
        raise RuntimeError("WMS returned an invalid image.")

    img = img.convertToFormat(QImage.Format_RGBA8888)
    ptr = img.bits()
    ptr.setsize(img.height() * img.width() * 4)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.width(), 4).copy()

    gray  = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.float32)
    alpha = arr[:, :, 3]

    visible = gray[alpha > 0]
    if visible.size == 0 or visible.max() == visible.min():
        raise RuntimeError("No visible pixel data — check layer name or AOI.")

    lo, hi = visible.min(), visible.max()
    gray   = np.clip((gray - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    gray[alpha == 0] = 0

    return gray

def save_geotiff(gray, out_path):
    x_res = (LNG_MAX - LNG_MIN) / IMG_WIDTH
    y_res = (LAT_MAX - LAT_MIN) / IMG_HEIGHT

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(out_path, IMG_WIDTH, IMG_HEIGHT, 1, gdal.GDT_Byte,
                       ["COMPRESS=LZW"])
    ds.SetGeoTransform([LNG_MIN, x_res, 0, LAT_MAX, 0, -y_res])
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(gray)
    ds.GetRasterBand(1).SetNoDataValue(0)
    ds.FlushCache()
    ds = None

# ---------------------------------------------------------
# Fetch, convert, save, add to project
# ---------------------------------------------------------
for layer_name, fname, display_name in LAYERS:
    out_path = os.path.join(OUT_DIR, fname)
    print(f"Fetching {layer_name} ...")
    try:
        gray = to_greyscale_array(fetch_wms(layer_name))
        save_geotiff(gray, out_path)

        layer = QgsRasterLayer(out_path, display_name)
        if not layer.isValid():
            raise RuntimeError(f"Layer failed to load: {out_path}")
        QgsProject.instance().addMapLayer(layer)

        print(f"  saved and added → {out_path}")
    except Exception as e:
        print(f"  error: {e}")

print("\nDone.")
