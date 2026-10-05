"""CLI wrapper around AFFDashClient.

Run a single scenario at fixed acreage:

    uv run scenario --variant PN --loccode 609 --net-acres 1000

Solve for the acreage that produces a target Total Net Revenue:

    uv run scenario --variant PN --loccode 609 --target-tnr 500000 --npv-year 40

Solve for the acreage that produces a target NPV at a chosen year horizon:

    uv run scenario --variant PN --loccode 609 --target-npv 1000000 --npv-year 40

Use a local API server:

    CARBON_API_BASE_URL=http://localhost:8001 uv run scenario \\
        --variant PN --loccode 609 --net-acres 1000

Use local joblib models in-process:

    uv run scenario --variant PN --loccode 609 --net-acres 1000 \\
        --local-models-dir ./data/models
"""

from __future__ import annotations

import argparse
import json
import sys

from aff_dash_client.client import AFFDashClient


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="scenario",
        description="Run an AFF carbon financial scenario via the model service.",
    )
    p.add_argument("--variant", required=True, help="FVS variant code (e.g. PN, CR_1).")
    p.add_argument("--loccode", required=True, help="FVS location code (e.g. 609).")

    p.add_argument("--net-acres", type=float, default=None,
                   help="Project acreage. Mutually exclusive with --target-tnr/--target-npv.")
    p.add_argument("--target-tnr", type=float, default=None,
                   help="Target Total Net Revenue. Solver mode — finds the acreage "
                        "that produces this TNR. Single protocol only.")
    p.add_argument("--target-npv", type=float, default=None,
                   help="Target NPV at --npv-year. Solver mode — finds the acreage "
                        "that produces this NPV. Single protocol only. To target "
                        "NPV under a different discount rate or carbon price, set "
                        "those via the financial_params dict on the API directly.")

    p.add_argument("--survival", type=float, default=None)
    p.add_argument("--si", type=float, default=None)
    p.add_argument("--species-tpa", default=None,
                   help="Comma-separated list of species TPA values, in variant species order.")
    p.add_argument("--pct-level", default=None, choices=[None, "PCT0", "PCT1", "PCT2"])
    p.add_argument("--protocols", default=None,
                   help="Comma-separated list of carbon protocols (default: ACR).")
    p.add_argument("--npv-year", type=int, default=None,
                   help="Year horizon for NPV. Defaults to 40 server-side.")

    p.add_argument("--api-base-url", default=None,
                   help="Override the default API URL. Same as CARBON_API_BASE_URL.")
    p.add_argument("--local-models-dir", default=None,
                   help="Run in-process against this directory of joblib models, "
                        "bypassing the API entirely.")

    p.add_argument("--format", choices=["json", "table"], default="json",
                   help="Output format (default: json).")
    p.add_argument("--return-dataframes", action="store_true",
                   help="Include full proforma/carbon/CU rows in the response.")

    return p.parse_args(argv)


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [s.strip() for s in value.split(",") if s.strip()]


def _split_csv_floats(value: str | None) -> list[float] | None:
    if value is None:
        return None
    return [float(s.strip()) for s in value.split(",") if s.strip()]


def _format_table(result_dict: dict) -> str:
    summaries = result_dict["summaries"]
    inputs = result_dict["inputs"]

    lines = [
        f"Variant:       {inputs['variant']}",
        f"Location:      {inputs['loccode']}",
        f"Net acres:     {inputs['net_acres']:,.4f}",
        f"NPV year:      {inputs['npv_year']}",
        f"Survival:      {inputs['survival']}",
        f"SI:            {inputs['si']}",
        f"Species TPA:   {inputs['species_tpa']}",
        f"PCT level:     {inputs['pct_level']}",
        "",
        f"{'Protocol':<10} {'TNR':>20} {'NPV':>20} {'NPV/Acre':>15}",
        f"{'-' * 67}",
    ]
    for s in summaries:
        lines.append(
            f"{s['protocol']:<10} "
            f"${s['total_net']:>18,.2f} "
            f"${s['npv_yr']:>18,.2f} "
            f"${s['npv_per_acre']:>13,.2f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    mode_flags = [args.net_acres, args.target_tnr, args.target_npv]
    if sum(flag is not None for flag in mode_flags) > 1:
        print(
            "Error: --net-acres, --target-tnr, and --target-npv are mutually exclusive.",
            file=sys.stderr,
        )
        return 2

    client = AFFDashClient(
        api_base_url=args.api_base_url,
        local_models_dir=args.local_models_dir,
    )

    common_kwargs = dict(
        variant=args.variant,
        loccode=args.loccode,
        survival=args.survival,
        si=args.si,
        species_tpa=_split_csv_floats(args.species_tpa),
        pct_level=args.pct_level,
        protocols=_split_csv(args.protocols),
        npv_year=args.npv_year,
        return_dataframes=args.return_dataframes,
    )

    if args.target_tnr is not None:
        result = client.solve_for_tnr(target_tnr=args.target_tnr, **common_kwargs)
    elif args.target_npv is not None:
        result = client.solve_for_npv(target_npv=args.target_npv, **common_kwargs)
    else:
        result = client.run(net_acres=args.net_acres, **common_kwargs)

    payload = result.as_dict()

    if args.format == "table":
        print(_format_table(payload))
    else:
        print(json.dumps(payload, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
