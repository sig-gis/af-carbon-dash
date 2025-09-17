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
    p.add_argument("--keep-variants", nargs="*", default=[],
                   help='List of FVSVariant names to keep (e.g., "PN EC"). Default: keep all.')
    p.add_argument("--precision", type=int, default=6,
                   help="Coordinate precision for GeoJSON output (default: 6)")
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load
    gdf = gpd.read_file(in_path)

    # Optional variant filter (before simplify to drop unneeded geoms early)
    if args.keep_variants and "FVSVariant" in gdf.columns:
        keep_set = {str(v).strip() for v in args.keep_variants if str(v).strip()}
        if keep_set:
            gdf = gdf[gdf["FVSVariant"].astype(str).isin(keep_set)]

    if gdf.empty:
        raise ValueError("No features left after filtering; check --keep-variants values or input data.")

    # Reproject to metric CRS for meter-based tolerance
    gdf_m = gdf.to_crs(3857)

    # Simplify geometry
    gdf_m["geometry"] = gdf_m.geometry.simplify(args.tolerance_m, preserve_topology=True)

    # Back to WGS84 for Folium/Leaflet
    gdf_4326 = gdf_m.to_crs(4326)

    # Keep only selected columns if requested
    if args.keep_cols:
        keep_cols = [c for c in args.keep_cols if c in gdf_4326.columns]  # <-- fixed
        # Ensure we keep geometry
        gdf_4326 = gdf_4326[keep_cols + ["geometry"]]

    # Save compact GeoJSON (driver option for smaller file)
    gdf_4326.to_file(out_path, driver="GeoJSON", **{"COORDINATE_PRECISION": args.precision})

    print(f"Wrote simplified GeoJSON → {out_path.resolve()}")

if __name__ == "__main__":
    main()

