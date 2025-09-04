#!/usr/bin/env python3
import sys
import requests
import zipfile
from pathlib import Path

url, out_zip = sys.argv[1], Path(sys.argv[2])
out_zip.parent.mkdir(parents=True, exist_ok=True)

print(f"Downloading {url} → {out_zip}")
r = requests.get(url)
out_zip.write_bytes(r.content)

with zipfile.ZipFile(out_zip, "r") as z:
    z.extractall(out_zip.parent / "shapefile")