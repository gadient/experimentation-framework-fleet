"""Fit the Brooklyn rate table from the TLC records.

    uv run eda/fit_demand.py                 # 20 places, the working count
    uv run eda/fit_demand.py --places 16     # an alternative place count

Produces one file, and nothing else in the repository writes it:

    datasets/nyc-brooklyn/artifacts/demand-<k>-v1.csv
    datasets/nyc-brooklyn/artifacts/PROVENANCE-demand-<k>-v1.toml

**What a row is.** One (day type, origin place, destination place, hour) cell, holding the number of
requests observed in it, the number of days of that type behind it, and the resulting **rate in
requests per hour**. 4 x 20 x 20 x 24 = 38,400 rows, zeros included: an unobserved cell is written
out rather than omitted, so the sparsity is visible in the artifact instead of implied by absence.

**The rate is the offered demand of the whole market, not of the fleet.** `datasets/nyc-brooklyn`
multiplies it by the capture share alpha at load time. Alpha is declared in the scenario; nothing
here decides how much of Brooklyn's demand a 100-vehicle fleet sees.

**Four day types**, and `run.day_type` selects the slice. Saturday and Sunday are separate: they are
36% apart in level and peak seven hours apart.

**What counts as a request** (notebook 05 section 1). A rider asking, at
`request_datetime` — not the pickup, which is a consequence of the operator's dispatch and is the
decision the operating model has to make. Shared and wheelchair-accessible requests are **counted**: a
matched ride differs from an asked-for one in the ride, not in the asking. Trips **leaving Brooklyn
are excluded** — 24.4% of Brooklyn pickups, which the fleet cannot serve because the travel matrix
has no entry for them and the service region is Brooklyn.

**Which days** (notebook 05 section 2). The demand date begins at 04:00, so a request at
01:00 on a Saturday belongs to Friday's day. Dropped: the two partial days at the ends of the window,
the heat wave of 23-25 June, and the Independence Day weekend of 4-6 July.

**An unobserved cell gets a rate of zero**, declared rather than smoothed (notebook 05 section 4.1).
The bound on what that discards was derived without August and measured against it in section 10.1:
at most 0.18% of a day's demand by the bound, and 0.010% to 0.045% measured.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import zoning
from common import CALIBRATION_MONTHS, RAW, session

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "datasets" / "nyc-brooklyn" / "artifacts"

#: Day types and the weekday numbers duckdb's `dayofweek` gives them (0 = Sunday).
DAY_TYPES = {"mon_wed": (1, 2, 3), "thu_fri": (4, 5), "sat": (6,), "sun": (0,)}

#: Days excluded from the fit, each an event a scenario might later inject.
HEAT = ("2025-06-23", "2025-06-24", "2025-06-25")          # heat wave
JUL4 = ("2025-07-04", "2025-07-05", "2025-07-06")          # Independence Day weekend

#: The first and last complete demand date of the window. 31 May holds only its last four hours
#: and 31 July loses its last four to the August file; averaging a partial day with full ones would
#: lower every rate it touches.
FIRST_DAY, LAST_DAY = "2025-06-01", "2025-07-30"


def fit(places: int, verbose: bool = True) -> dict:
    con = session()
    bk = ",".join(str(int(v)) for v in con.sql(
        "SELECT LocationID FROM z WHERE Borough = 'Brooklyn' ORDER BY LocationID").df().LocationID)

    shp = zoning.shapes()
    lab = zoning.contiguous_labels(places, shp, zoning.adjacency(shp))
    vals = ",".join(f"({a},{b})" for a, b in lab.items())
    con.execute(f"CREATE OR REPLACE TEMP VIEW mp AS SELECT * FROM (VALUES {vals}) AS m(lid, z)")

    case = " ".join(f"WHEN dow IN ({', '.join(map(str, d))}) THEN '{n}'"
                    for n, d in DAY_TYPES.items())
    excluded = ", ".join(f"DATE '{d}'" for d in HEAT + JUL4)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW q AS
        SELECT * FROM (
            SELECT mo.z AS zo, md.z AS zd,
                   hour(request_datetime) AS h,
                   CAST(request_datetime - INTERVAL 4 HOUR AS DATE) AS sim_dt,
                   dayofweek(CAST(request_datetime - INTERVAL 4 HOUR AS DATE)) AS dow
            FROM t
            JOIN mp mo ON t.PULocationID = mo.lid
            JOIN mp md ON t.DOLocationID = md.lid
            WHERE t.PULocationID IN ({bk}) AND t.DOLocationID IN ({bk})
        )
        WHERE sim_dt BETWEEN DATE '{FIRST_DAY}' AND DATE '{LAST_DAY}'
          AND sim_dt NOT IN ({excluded})
    """)
    con.execute(f"CREATE OR REPLACE TEMP VIEW qd AS SELECT *, CASE {case} END AS dt FROM q")

    days = con.sql("SELECT dt, count(DISTINCT sim_dt) AS days FROM qd GROUP BY 1 ORDER BY 1").df()
    n_days = dict(zip(days.dt, days.days))
    if set(n_days) != set(DAY_TYPES):
        raise RuntimeError(f"expected every day type in the window, got {sorted(n_days)}")
    total = con.sql("SELECT count(*) FROM qd").fetchone()[0]
    if verbose:
        print(f"{total:,} requests, {places} places, window {' + '.join(CALIBRATION_MONTHS)}")
        print(f"days per type: {n_days}")

    obs = con.sql("""
        SELECT dt, zo, zd, h, count(*) AS n FROM qd
        GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4""").df()

    grid = pd.MultiIndex.from_product(
        [sorted(DAY_TYPES), range(places), range(places), range(24)],
        names=["dt", "zo", "zd", "h"]).to_frame(index=False)
    grid = grid.merge(obs, how="left").fillna({"n": 0})
    grid["n"] = grid.n.astype(np.int64)
    grid["days"] = grid.dt.map(n_days).astype(np.int64)
    # Requests per hour: the cell already spans one hour, so the count divided by the days of that
    # type is a rate per hour directly. Rounded to 6 decimals — a rate below 1e-6 per hour is one
    # request per 114 years and is not a number this table can support.
    grid["rate_per_hour"] = (grid.n / grid.days).round(6)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / f"demand-{places}-v1.csv"
    grid[["dt", "zo", "zd", "h", "n", "days", "rate_per_hour"]].to_csv(path, index=False)

    per_type = grid.groupby("dt").apply(
        lambda g: pd.Series({
            "requests_per_day": round(float(g.rate_per_hour.sum()), 1),
            "empty_pct": round(100 * float((g.n == 0).mean()), 2),
            # A cell spans one hour, so its rate per hour IS its contribution to the day.
            "under_one_per_day_pct": round(100 * float((g.rate_per_hour < 1).mean()), 2),
        }), include_groups=False)

    summary = {
        "places": places, "requests": int(total), "cells": int(len(grid)),
        "days": {k: int(v) for k, v in sorted(n_days.items())},
        "per_type": {k: v.to_dict() for k, v in per_type.iterrows()},
        "demand_file": path.name,
    }
    prov = ARTIFACTS / f"PROVENANCE-demand-{places}-v1.toml"
    prov.write_text(_provenance(summary, [path]))

    if verbose:
        print(per_type.to_string())
        print(f"\nwrote {path.relative_to(ROOT)}   {len(grid):,} cells")
        print(f"wrote {prov.relative_to(ROOT)}")
    return summary


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _provenance(s: dict, files: list[Path]) -> str:
    raw = [p.name for p in sorted(RAW.glob("fhvhv_tripdata_*.parquet"))
           if p.name.split("_")[-1][:7] in CALIBRATION_MONTHS]
    lines = [
        "# Written by eda/fit_demand.py. Every artifact an evaluation depends on is named and hashed here,",
        "# so a result can be traced to the data it came from.",
        "",
        "[fit]",
        f'generated = "{dt.datetime.now().astimezone().isoformat(timespec="seconds")}"',
        f"months = {list(CALIBRATION_MONTHS)!r}".replace("'", '"'),
        f"places = {s['places']}",
        f"requests = {s['requests']}",
        f"cells = {s['cells']}",
        'timestamp = "request_datetime — the rider asking, not the pickup"',
        'counted = "shared and wheelchair-accessible requests included"',
        'excluded = "trips leaving Brooklyn; heat wave; Independence Day weekend"',
        'unobserved_cell = "rate 0.0, declared — notebook 05 sections 4.1 and 10.1"',
        'level = "market demand; the pack multiplies by capture share alpha"',
        "",
        "[days]",
    ]
    lines += [f"{k} = {v}" for k, v in s["days"].items()]
    lines.append("")
    for name, vals in s["per_type"].items():
        lines.append(f"[per_type.{name}]")
        lines += [f"{k} = {v}" for k, v in vals.items()]
        lines.append("")
    lines += ["[inputs]"] + [f'raw_{i} = "{n}"' for i, n in enumerate(raw)]
    # The bytes, not just the names. Naming the file says which month; the digest says which copy of
    # it, which is what makes a fitted artifact traceable to the data it came from.
    lines += ["", "[inputs.sha256]"] + [f'"{n}" = "{_digest(RAW / n)}"' for n in raw]
    lines += ["", "[outputs]"] + [f'"{p.name}" = "{_digest(p)}"' for p in files]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--places", type=int, default=20)
    args = ap.parse_args()
    fit(args.places)
    return 0


if __name__ == "__main__":
    sys.exit(main())
