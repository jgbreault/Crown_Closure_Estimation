import os
import re
import glob
import subprocess
import urllib.request
import urllib.error
import zipfile

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
BASE_URL    = "https://pub.data.gov.bc.ca/datasets/175624"
OUT_DIR     = "/Volumes/Spleen/CABIN/datasets/dem"
MERGED_PATH = "/Volumes/Spleen/CABIN/datasets/dem_merged.tif"

# GDAL CLI tools installed by QGIS — update path if needed
GDAL_BIN = "/Applications/QGIS.app/Contents/MacOS/bin"

# NTS 1:250,000 sheets covering approx lat 49-51, lng -119 to -125.
# Add or remove sheets as needed — full list at:
# https://pub.data.gov.bc.ca/datasets/175624/
SHEETS = [
    "82e", "82f",           # ~49-50N, eastern AOI
    "82l", "82m",           # ~50-51N, eastern AOI
    "92h", "92i",           # ~49-50N, western AOI
    "92j", "92k",           # ~50-51N, western AOI
]

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def list_zips(sheet):
    url = f"{BASE_URL}/{sheet}/"
    with urllib.request.urlopen(url) as r:
        html = r.read().decode()
    return re.findall(r'href="([^"]+\.dem\.zip)"', html)

def download_file(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        return  # zip already on disk (interrupted run), skip to unzip
    tmp = dest + ".part"
    try:
        urllib.request.urlretrieve(url, tmp)
        os.rename(tmp, dest)
        size_mb = os.path.getsize(dest) / 1_000_000
        print(f"    ok    {os.path.basename(dest)}  ({size_mb:.1f} MB)")
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"    error {os.path.basename(dest)}: {e}")

def unzip_and_remove(path):
    try:
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(os.path.dirname(path))
        os.remove(path)
        print(f"    unzipped {os.path.basename(path)}")
    except Exception as e:
        print(f"    error unzipping {os.path.basename(path)}: {e}")

# ---------------------------------------------------------
# Download & unzip
# ---------------------------------------------------------
for sheet in SHEETS:
    print(f"\n[{sheet}]")
    try:
        zips = list_zips(sheet)
    except urllib.error.HTTPError as e:
        print(f"  could not list sheet: {e}")
        continue

    if not zips:
        print("  no .dem.zip files found")
        continue

    print(f"  {len(zips)} files")
    for fname in zips:
        dest      = os.path.join(OUT_DIR, sheet, fname)
        extracted = dest[:-4]  # strip .zip → expected .dem path

        if os.path.exists(extracted):
            print(f"    skip  {fname} (already extracted)")
            continue

        download_file(f"{BASE_URL}/{sheet}/{fname}", dest)
        if os.path.exists(dest):
            unzip_and_remove(dest)

# ---------------------------------------------------------
# Stitch all .dem files into one GeoTIFF
# ---------------------------------------------------------
print("\nSearching for .dem files...")
dem_files = sorted(glob.glob(os.path.join(OUT_DIR, "**", "*.dem"), recursive=True))

if not dem_files:
    print("No .dem files found — skipping stitch.")
else:
    print(f"Stitching {len(dem_files)} tiles into {MERGED_PATH} ...")

    vrt_path        = MERGED_PATH.replace(".tif", ".vrt")
    gdalbuildvrt    = os.path.join(GDAL_BIN, "gdalbuildvrt")
    gdal_translate  = os.path.join(GDAL_BIN, "gdal_translate")

    subprocess.run([gdalbuildvrt, vrt_path] + dem_files, check=True)

    subprocess.run([
        gdal_translate,
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
        "-co", "BIGTIFF=IF_SAFER",
        vrt_path, MERGED_PATH,
    ], check=True)

    print(f"Saved {MERGED_PATH}")

print("\nDone.")
