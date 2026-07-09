#!/usr/bin/env python3
"""Export one consistently styled PNG per feature from a single shapefile.

Example:
    python -m utils.functions.export_variant_pngs \
      --input data/FVSVariantMap20210525/FVS_Variants_and_Locations_4326.shp \
      --output-dir model_service/quarto/data/fig \
      --id-column FVSLocCode
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from shapely.ops import transform as shapely_transform


def _unwrap_lon(geom):
    """Shift positive longitudes by -360 so an antimeridian-crossing feature is
    contiguous instead of spanning the whole globe.

    Safe for the CONUS+AK FVS dataset: every real longitude is negative except
    the Aleutian tips that wrap past +180. Without this, Alaska's Aleutians
    feature has a naive lon span of ~359deg and its map renders the entire globe.
    """

    def _shift(x, y, z=None):
        x = np.where(np.asarray(x) > 0, np.asarray(x) - 360.0, x)
        return (x, y) if z is None else (x, y, z)

    return shapely_transform(_shift, geom)


def _safe_name(value: object, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = fallback
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read one shapefile and export one PNG per feature with fixed global "
            "extent (same zoom) and consistent styling."
        )
    )
    p.add_argument(
        "--input", required=True, help="Input vector path (SHP/GPKG/GeoJSON)."
    )
    p.add_argument("--output-dir", required=True, help="Directory to write PNG files.")
    p.add_argument(
        "--id-column",
        default="FVSLocCode",
        help="Attribute column used for PNG filename stem (default: FVSLocCode).",
    )
    p.add_argument("--filename-prefix", default="", help="Optional filename prefix.")
    p.add_argument("--filename-suffix", default="", help="Optional filename suffix.")
    p.add_argument("--dpi", type=int, default=300, help="PNG DPI (default: 300).")
    p.add_argument(
        "--fig-width", type=float, default=8.0, help="Figure width in inches."
    )
    p.add_argument(
        "--fig-height", type=float, default=6.0, help="Figure height in inches."
    )
    p.add_argument(
        "--match-example",
        default=None,
        help="Optional PNG path to match output pixel dimensions (e.g., .../fig/102.png).",
    )
    p.add_argument(
        "--feature-padding-pct",
        type=float,
        default=0.08,
        help="Per-feature padding as fraction of feature width/height (default: 0.08).",
    )
    p.add_argument(
        "--padding-pct",
        type=float,
        default=0.05,
        help="Legacy global extent padding (unused in per-feature mode).",
    )
    p.add_argument("--bg-color", default="#f5f7f9", help="Figure background color.")
    p.add_argument(
        "--context-fill", default="#d9dee3", help="Context polygon fill color."
    )
    p.add_argument(
        "--context-edge", default="#9daab5", help="Context polygon edge color."
    )
    p.add_argument(
        "--highlight-fill",
        default="none",
        help="Highlighted polygon fill color (default: none for transparent fill).",
    )
    p.add_argument(
        "--highlight-edge", default="#00383a", help="Highlighted polygon edge color."
    )
    p.add_argument(
        "--context-alpha",
        type=float,
        default=0.45,
        help="Context alpha (default: 0.45).",
    )
    p.add_argument(
        "--highlight-alpha",
        type=float,
        default=0.85,
        help="Highlight alpha (default: 0.85).",
    )
    p.add_argument(
        "--context-linewidth", type=float, default=0.5, help="Context edge linewidth."
    )
    p.add_argument(
        "--highlight-linewidth",
        type=float,
        default=1.1,
        help="Highlight edge linewidth.",
    )
    return p.parse_args()


def _resolve_output_pixels(args: argparse.Namespace) -> tuple[int, int]:
    if args.match_example:
        with Image.open(args.match_example) as im:
            return int(im.width), int(im.height)
    width_px = max(1, int(round(float(args.fig_width) * int(args.dpi))))
    height_px = max(1, int(round(float(args.fig_height) * int(args.dpi))))
    return width_px, height_px


def _expanded_feature_viewport(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    padding_pct: float,
    target_aspect: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    width = max(maxx - minx, 1e-9)
    height = max(maxy - miny, 1e-9)
    pad = max(padding_pct, 0.0)
    half_w = (width * (1.0 + 2.0 * pad)) / 2.0
    half_h = (height * (1.0 + 2.0 * pad)) / 2.0

    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0

    current_aspect = (2.0 * half_w) / max(2.0 * half_h, 1e-9)
    if current_aspect > target_aspect:
        half_h = half_w / max(target_aspect, 1e-9)
    else:
        half_w = half_h * target_aspect

    return (cx - half_w, cx + half_w), (cy - half_h, cy + half_h)


def export_feature_pngs(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gdf = gpd.read_file(in_path)
    if gdf.empty:
        raise ValueError(f"No features found in: {in_path}")

    if gdf.crs is None:
        raise ValueError("Input has no CRS. Please assign CRS before export.")

    if str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs(4326)

    if args.id_column not in gdf.columns:
        raise ValueError(
            f"Column '{args.id_column}' not found. Available: {', '.join(gdf.columns.astype(str))}"
        )

    width_px, height_px = _resolve_output_pixels(args)
    target_aspect = width_px / max(height_px, 1)

    fig_width = width_px / args.dpi
    fig_height = height_px / args.dpi

    count = 0
    for idx, row in gdf.iterrows():
        feature_name = _safe_name(row.get(args.id_column), fallback=f"feature_{idx}")
        filename = f"{args.filename_prefix}{feature_name}{args.filename_suffix}.png"
        out_path = out_dir / filename

        fig, ax = plt.subplots(figsize=(fig_width, fig_height), facecolor=args.bg_color)
        ax.set_facecolor(args.bg_color)

        # Alaska's Aleutians cross the antimeridian
        context_gdf = gdf
        highlight_geom = row.geometry
        fbounds = highlight_geom.bounds
        if fbounds[2] - fbounds[0] > 180:
            context_gdf = gdf.copy()
            context_gdf["geometry"] = context_gdf.geometry.apply(_unwrap_lon)
            highlight_geom = _unwrap_lon(highlight_geom)

        context_gdf.plot(
            ax=ax,
            color=args.context_fill,
            edgecolor=args.context_edge,
            alpha=args.context_alpha,
            linewidth=args.context_linewidth,
        )

        gpd.GeoDataFrame([{"geometry": highlight_geom}], crs=gdf.crs).plot(
            ax=ax,
            color=args.highlight_fill,
            edgecolor=args.highlight_edge,
            alpha=args.highlight_alpha,
            linewidth=args.highlight_linewidth,
        )

        fminx, fminy, fmaxx, fmaxy = highlight_geom.bounds
        xlim, ylim = _expanded_feature_viewport(
            fminx,
            fminy,
            fmaxx,
            fmaxy,
            args.feature_padding_pct,
            target_aspect,
        )

        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")

        fig.savefig(out_path, dpi=args.dpi, bbox_inches=None, pad_inches=0.0)
        plt.close(fig)
        count += 1

    return count


def main() -> None:
    args = parse_args()
    written = export_feature_pngs(args)
    print(f"Wrote {written} PNG files to: {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
