#!/usr/bin/env python3
import sys
import requests
import zipfile
from pathlib import Path

url, out_zip, out_shp = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out_zip.parent.mkdir(parents=True, exist_ok=True)
out_shp.parent.mkdir(parents=True, exist_ok=True)

print(f"Downloading {url} → {out_zip}")
r = requests.get(url)
out_zip.write_bytes(r.content)

print(f"Extracting {out_zip} → {out_shp}")
with zipfile.ZipFile(out_zip, "r") as z:
    z.extractall(out_shp.parent)