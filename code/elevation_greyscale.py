import os
import urllib.request
import numpy as np
from PyQt5.QtCore import QByteArray
from PyQt5.QtGui import QImage

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
WMS_URL    = "https://maps.geogratis.gc.ca/wms/elevation_en"
WMS_LAYER  = "cdsm_shade"   # NOTE: update to the layer identifier shown in
                             # QGIS Browser → WMS → elevation_en capabilities

IMG_WIDTH  = 3072            # 3:1 matches AOI aspect ratio (6° lng × 2° lat)
IMG_HEIGHT = 1024
OUTPUT_PATH = "/Volumes/Spleen/CABIN/images/elevation/elevation_greyscale.png"

# AOI — same as cropper (EPSG:4326)
LAT_MIN, LAT_MAX = 49, 51
LNG_MIN, LNG_MAX = -125, -119

# ---------------------------------------------------------
# 1. WMS GetMap request
# ---------------------------------------------------------
params = (
    f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
    f"&LAYERS={WMS_LAYER}"
    f"&SRS=EPSG:4326"
    f"&BBOX={LNG_MIN},{LAT_MIN},{LNG_MAX},{LAT_MAX}"
    f"&WIDTH={IMG_WIDTH}&HEIGHT={IMG_HEIGHT}"
    f"&FORMAT=image/png"
    f"&STYLES="
)

print(f"Requesting WMS tile...")
with urllib.request.urlopen(WMS_URL + params) as response:
    data = response.read()

# ---------------------------------------------------------
# 2. Decode image
# ---------------------------------------------------------
img = QImage()
img.loadFromData(QByteArray(data))

if img.isNull():
    raise RuntimeError("WMS returned an invalid or empty image. Check WMS_LAYER name.")

img = img.convertToFormat(QImage.Format_RGBA8888)
ptr = img.bits()
ptr.setsize(img.height() * img.width() * 4)
arr = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.width(), 4).copy()

# ---------------------------------------------------------
# 3. Greyscale — luminosity weights, then min/max stretch
#    so black = lowest elevation, white = highest
# ---------------------------------------------------------
gray = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.float32)

lo, hi = gray.min(), gray.max()
if hi > lo:
    gray = (gray - lo) / (hi - lo) * 255.0
gray = gray.astype(np.uint8)

# ---------------------------------------------------------
# 4. Save
# ---------------------------------------------------------
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

out = QImage(gray.tobytes(), img.width(), img.height(), img.width(), QImage.Format_Grayscale8).copy()
out.save(OUTPUT_PATH, "PNG")

print(f"Saved to '{OUTPUT_PATH}'")
