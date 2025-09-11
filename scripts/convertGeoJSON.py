#!/usr/bin/env python3
import argparse
from pathlib import Path
import geopandas as gpd

def main():
    p = argparse.ArgumentParser(description="Simplify a shapefile and save to GeoJSON (EPSG:4326).")
    p.add_argument("--input", required=True, help="Path to input Shapefile/GeoPackage/GeoJSON")
    p.add_argument("--output", required=True, help="Path to output GeoJSON")
    p.add_argument("--tolerance-m", type=float, default=200.0,
                   help="Douglas-Peucker simplify tolerance in meters (default: 200)")
    p.add_argument("--keep-cols", nargs="*", default=[],
                   help="Attribute columns to keep (besides geometry). Default: keep all")
    p.add_argument('--keep-variants', nargs='*', default=[],
                   help='List of FVSVariant names to keep (e.g., "PN EC"). Default: keep all.')
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load
    gdf = gpd.read_file(in_path)

    # Reproject to a metric CRS for a meaningful meter-based tolerance
    # Web Mercator is fine for overview maps; use a local CRS if you need precision.
    gdf_m = gdf.to_crs(3857)

    # Simplify geometry
    gdf_m["geometry"] = gdf_m.geometry.simplify(args.tolerance_m, preserve_topology=True)

    # Reproject back to WGS84 (Leaflet/Folium expects 4326)
    gdf_4326 = gdf_m.to_crs(4326)

    # Trim columns if requested
    if args.keep_cols:
        keep_cols = [c for c in args.keep if c in gdf_4326.columns]
        gdf_4326 = gdf_4326[keep_cols + ["geometry"]]
    
    if args.keep_variants and "FVSVariant" in gdf_4326.columns:
        gdf_4326 = gdf_4326[gdf_4326["FVSVariant"].isin(args.keep_variants)]

    # Save compact GeoJSON
    gdf_4326.to_file(out_path, driver="GeoJSON")

    print(f"Wrote simplified GeoJSON → {out_path.resolve()}")

if __name__ == "__main__":
    main()
