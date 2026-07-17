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
import math
from pathlib import Path

import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image
from shapely.geometry import Point
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
    p.add_argument(
        "--no-inset",
        action="store_true",
        help="Disable the locator inset map.",
    )
    p.add_argument(
        "--no-scalebar",
        action="store_true",
        help="Disable the scale bar.",
    )
    p.add_argument(
        "--inset-width-frac",
        type=float,
        default=0.30,
        help="Inset width as fraction of main axes width (default: 0.30).",
    )
    p.add_argument(
        "--inset-zoom-factor",
        type=float,
        default=3.0,
        help="Inset extent as multiple of feature span (default: 3.0).",
    )
    p.add_argument(
        "--inset-min-span",
        type=float,
        default=8.0,
        help="Minimum inset width in degrees longitude (default: 8.0).",
    )
    p.add_argument(
        "--states",
        default="data/cb_2023_us_state_20m.zip",
        help="US state boundaries layer for the inset basemap.",
    )
    p.add_argument(
        "--locator-color",
        default="#c62828",
        help="Locator viewport box color (default: #c62828).",
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
    lon_scale: float = 1.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    width = max(maxx - minx, 1e-9)
    height = max(maxy - miny, 1e-9)
    pad = max(padding_pct, 0.0)
    half_w = (width * (1.0 + 2.0 * pad)) / 2.0
    half_h = (height * (1.0 + 2.0 * pad)) / 2.0

    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0

    current_aspect = (2.0 * half_w * lon_scale) / max(2.0 * half_h, 1e-9)
    if current_aspect > target_aspect:
        half_h = half_w * lon_scale / max(target_aspect, 1e-9)
    else:
        half_w = half_h * target_aspect / lon_scale

    return (cx - half_w, cx + half_w), (cy - half_h, cy + half_h)


def _farthest_corner(highlight_geom, xlim, ylim, w: float, h: float, margin: float = 0.025):
    corners = {
        "sw": (Point(xlim[0], ylim[0]), (margin, margin)),
        "se": (Point(xlim[1], ylim[0]), (1 - margin - w, margin)),
        "nw": (Point(xlim[0], ylim[1]), (margin, 1 - margin - h)),
        "ne": (Point(xlim[1], ylim[1]), (1 - margin - w, 1 - margin - h)),
    }
    key = max(corners, key=lambda k: highlight_geom.distance(corners[k][0]))
    return key, corners[key][1]


def _nice_miles(target: float) -> float:
    power = math.floor(math.log10(max(target, 1e-9)))
    for mult in (5, 2, 1):
        nice = mult * 10**power
        if nice <= target:
            return nice
    return 10**power


def _draw_scale_bar(ax, xlim, ylim, corner: str, color: str) -> None:
    dx, dy = xlim[1] - xlim[0], ylim[1] - ylim[0]
    mi_per_deg = 69.172 * math.cos(math.radians((ylim[0] + ylim[1]) / 2.0))
    miles = _nice_miles(0.25 * dx * mi_per_deg)
    bar = miles / mi_per_deg

    x0 = xlim[0] + 0.05 * dx if corner.endswith("w") else xlim[1] - 0.05 * dx - bar
    y = ylim[0] + 0.05 * dy
    halo = [pe.withStroke(linewidth=3, foreground="#ffffff")]
    ax.plot(
        [x0, x0 + bar],
        [y, y],
        color=color,
        linewidth=2,
        solid_capstyle="butt",
        path_effects=halo,
    )
    for x in (x0, x0 + bar):
        ax.plot(
            [x, x],
            [y, y + 0.012 * dy],
            color=color,
            linewidth=1.5,
            path_effects=halo,
        )
    ax.text(
        x0 + bar / 2.0,
        y + 0.02 * dy,
        f"{miles:g} mi",
        ha="center",
        va="bottom",
        fontsize=11,
        color=color,
        path_effects=halo,
    )


def _draw_locator_inset(
    ax,
    states_gdf,
    context_gdf,
    highlight_geom,
    main_xlim,
    main_ylim,
    target_aspect: float,
    args: argparse.Namespace,
) -> None:
    fminx, fminy, fmaxx, fmaxy = highlight_geom.bounds
    cx = (fminx + fmaxx) / 2.0
    cy = (fminy + fmaxy) / 2.0
    lon_scale = math.cos(math.radians(cy))
    half_w = max((fmaxx - fminx) * args.inset_zoom_factor, args.inset_min_span) / 2.0
    half_h = (
        max(
            (fmaxy - fminy) * args.inset_zoom_factor,
            args.inset_min_span * lon_scale / target_aspect,
        )
        / 2.0
    )
    if half_w * lon_scale / half_h > target_aspect:
        half_h = half_w * lon_scale / target_aspect
    else:
        half_w = half_h * target_aspect / lon_scale
    ix0, ix1, iy0, iy1 = cx - half_w, cx + half_w, cy - half_h, cy + half_h

    w = h = args.inset_width_frac
    corner, (x0, y0) = _farthest_corner(highlight_geom, main_xlim, main_ylim, w, h)

    iax = ax.inset_axes([x0, y0, w, h])
    iax.set_facecolor("#ffffff")
    states_gdf.plot(
        ax=iax,
        color="#e8ecef",
        edgecolor="#8894a0",
        linewidth=0.6,
        aspect=None,
    )
    context_gdf.plot(
        ax=iax,
        facecolor="none",
        edgecolor=args.context_edge,
        linewidth=0.3,
        aspect=None,
    )
    gpd.GeoSeries([highlight_geom]).plot(
        ax=iax, color=args.highlight_edge, aspect=None
    )

    # Dynamic inset map sizing
    bw = max(main_xlim[1] - main_xlim[0], 0.05 * (ix1 - ix0))
    bh = max(main_ylim[1] - main_ylim[0], 0.05 * (iy1 - iy0))
    if bw < 0.7 * (ix1 - ix0) and bh < 0.7 * (iy1 - iy0):
        cx = (main_xlim[0] + main_xlim[1]) / 2.0
        cy = (main_ylim[0] + main_ylim[1]) / 2.0
        iax.add_patch(
            Rectangle(
                (cx - bw / 2, cy - bh / 2),
                bw,
                bh,
                fill=False,
                edgecolor=args.locator_color,
                linewidth=0.9,
            )
        )
    iax.set_xlim(ix0, ix1)
    iax.set_ylim(iy0, iy1)
    iax.set_aspect(1.0 / lon_scale, adjustable="box")
    iax.set_xticks([])
    iax.set_yticks([])
    for spine in iax.spines.values():
        spine.set_edgecolor("#9daab5")
        spine.set_linewidth(0.6)
    return corner


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

    if not args.no_inset:
        gdf_u = gdf.copy()
        gdf_u["geometry"] = gdf_u.geometry.apply(_unwrap_lon)
        states_u = gpd.read_file(args.states).to_crs(4326)
        states_u["geometry"] = states_u.geometry.apply(_unwrap_lon)

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
        cos_lat = math.cos(math.radians((fminy + fmaxy) / 2.0))
        xlim, ylim = _expanded_feature_viewport(
            fminx,
            fminy,
            fmaxx,
            fmaxy,
            args.feature_padding_pct,
            target_aspect,
            lon_scale=cos_lat,
        )

        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect(1.0 / cos_lat, adjustable="box")
        ax.axis("off")

        inset_corner = None
        if not args.no_inset:
            inset_corner = _draw_locator_inset(
                ax,
                states_u,
                gdf_u,
                highlight_geom,
                xlim,
                ylim,
                target_aspect,
                args,
            )

        if not args.no_scalebar:
            bar_corner = "se" if inset_corner == "sw" else "sw"
            _draw_scale_bar(ax, xlim, ylim, bar_corner, args.highlight_edge)

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
