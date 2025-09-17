#!/usr/bin/env python3
import sys
import requests
import zipfile
from pathlib import Path

def stream_download(url: str, dest: Path, chunk_size: int = 1 << 16):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)

def main():
    url = sys.argv[1]
    out_zip = Path(sys.argv[2])   # e.g., tmp/FVSVariantMap20210525.zip
    out_shp = Path(sys.argv[3])   # e.g., tmp/shapefile/FVS_Variants_and_Locations.shp
    extract_dir = out_shp.parent  # where we’ll extract the ZIP

    print(f"Downloading {url} → {out_zip}")
    stream_download(url, out_zip)

    print(f"Extracting {out_zip} → {extract_dir}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "r") as z:
        z.extractall(extract_dir)

    # If the exact shapefile path isn’t present (name differs), try to find one
    if not out_shp.exists():
        candidates = list(extract_dir.rglob("*.shp"))
        if candidates:
            actual = candidates[0]
            print(f"Note: requested {out_shp.name} not found; using detected shapefile: {actual}")
        else:
            raise FileNotFoundError(f"No .shp found under {extract_dir}")

if __name__ == "__main__":
    main()
