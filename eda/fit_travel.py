"""Fit the Brooklyn travel artifacts from the TLC records.

    uv run eda/fit_travel.py                 # 20 places, the working count
    uv run eda/fit_travel.py --places 16     # an alternative place count

Produces three files, and nothing else in the repository writes them:

    config/zoning/brooklyn-<k>-v1.csv        the place map
    datasets/nyc-brooklyn/artifacts/duration-<k>-v1.csv
    datasets/nyc-brooklyn/artifacts/distance-<k>-v1.csv
    datasets/nyc-brooklyn/artifacts/daytype-<k>-v1.csv
    datasets/nyc-brooklyn/artifacts/PROVENANCE-<k>-v1.toml

**What a duration row is.** One (origin place, destination place, hour) cell, holding 48
percentile values in milliseconds, an expectation computed *from those percentiles* rather than from
the raw journeys, the number of journeys behind it, and the ladder rung that produced it.

**Why the expectation is computed from the knots and not from the data.** The travel interface quotes a
rider an ETA from `expectation()` and then realises a duration from `draw()`. If the two came
from different objects the quote would be biased against the draw by the compression error, and that
bias would look like a modelling result. Computing both from the same 48 numbers makes the mean of
many draws equal the quoted expectation by construction — a property checked to floating point
rather than assumed.

**The ladder.** A cell is measured if it holds at least `MIN_JOURNEYS`. Otherwise it borrows,
in order: the same route at neighbouring hours, then the same route across all hours, then a
distance-conditioned prior across other routes. Every cell records which rung answered it, because a
result resting on borrowed cells is a different claim from one resting on measured cells.

**Days.** All days of the calibration window, including the two events notebook 05 excludes from the
demand fit. Notebook 04 section 1.1 measures why: including them moves the fitted cell by 0.00% and
-0.13%.

**The day-type dimension is a multiplier, not a fifth index.** A cell pools every day of the
window; `daytype-<k>-v1.csv` then holds one factor per (day type, hour) — 96 numbers — which the pack
applies to a cell's knots at load time. Notebook 04 section 12 measures why it is not a split: at 20
places a four-way split drops well-observed cells from 84.1% to 57.9%, where the multiplier costs no
coverage at all because it divides the data by hour across all 400 routes rather than per cell.

**The factors are normalised so applying one cannot move the pooled level.** Within each hour the four
factors are divided by their journey-weighted mean, so a run of the mixture of day types the window
actually contained reproduces the pooled matrix exactly. Without that, adding the dimension would
silently re-level every duration in the pack.
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

#: Percentile positions stored per cell. Tail-dense: dense near 100 because the slow tail is what
#: a policy meets when it goes wrong, and an even 21-knot grid distorts the sampler's own mean by
#: +31.5%. 48 after removing the duplicated 90 and 99.
KNOTS: np.ndarray = np.unique(np.concatenate([
    np.linspace(0, 90, 19),        # 0, 5, ..., 90
    np.linspace(90, 99, 19),       # 90, 90.5, ..., 99
    np.linspace(99, 99.9, 10),     # 99, 99.1, ..., 99.9
    [99.99, 100],
]))

#: Journeys a cell needs before it is measured rather than borrowed. 30 is the notebook's threshold
#: and the point at which a 48-knot grid stops being mostly interpolation between two observations.
MIN_JOURNEYS = 30

#: Metres per mile. The records carry miles; every stored value is a base-unit integer.
M_PER_MILE = 1609.344

RUNGS = {1: "measured", 2: "neighbouring_hours", 3: "whole_route", 4: "distance_prior"}

#: Day types, and the weekday numbers duckdb's `dayofweek` gives them (0 = Sunday). The same four
#: the demand fit uses — notebook 04 section 12 measured that traffic wants the same partition,
#: which is what lets one `run.day_type` mean one thing for both artifacts.
DAY_TYPES = {"mon_wed": (1, 2, 3), "thu_fri": (4, 5), "sat": (6,), "sun": (0,)}

#: A cell contributes to a factor only if it holds this many journeys on that day type, and this
#: many pooled. The factor is a median over cells, so a few thin cells cannot pull it.
FACTOR_MIN_DAY, FACTOR_MIN_POOLED = 30, 100


def expectation_from_knots(values: np.ndarray, knots: np.ndarray = KNOTS) -> np.ndarray:
    """Mean of the distribution the knots define, by exact integration of its quantile function.

    A draw is `interp(u * 100, knots, values)`, so the quantile function is piecewise linear in
    percentile space and its integral over [0, 1] is the trapezoid rule on the knot grid. Exact for
    the distribution actually sampled, which is the point: `expectation()` and the mean of `draw()`
    describe one object rather than two.

    `values` may be 1-D (one cell) or 2-D (one row per cell).
    """
    w = np.diff(knots) / 100.0
    v = np.atleast_2d(values)
    mids = (v[:, :-1] + v[:, 1:]) / 2.0
    out = mids @ w
    return out if values.ndim == 2 else out[0]


def _percentiles(sorted_values: np.ndarray) -> np.ndarray:
    """The 48 knot values of one already-sorted sample."""
    return np.percentile(sorted_values, KNOTS, method="linear")


def fit_day_factors(con, places: int, verbose: bool = True) -> "pd.DataFrame":
    """One multiplier per (day type, hour): how much slower that day type is than the pooled cell.

    Measured as the **median over cells** of (the cell's median duration on that day type) divided by
    (the cell's pooled median duration), so a busy route cannot outvote a quiet one and each cell is
    its own control — the route mix differs between day types, and a raw comparison of pooled medians
    would read that mix as a traffic difference.

    **Normalised within the hour.** The four factors are divided by their journey-weighted mean, so
    the mixture of day types the window actually held reproduces the pooled cell exactly. The
    dimension then re-distributes duration between day types without re-levelling the pack.
    """
    case = " ".join(f"WHEN dow IN ({', '.join(map(str, d))}) THEN '{n}'"
                    for n, d in DAY_TYPES.items())
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW jd AS
        SELECT *, CASE {case} END AS dt FROM jj""")

    cell = con.sql(f"""
        SELECT dt, zo, zd, h, count(*) AS n, median(ms) AS med FROM jd
        GROUP BY 1, 2, 3, 4 HAVING count(*) >= {FACTOR_MIN_DAY} ORDER BY 1, 2, 3, 4""").df()
    pooled = con.sql(f"""
        SELECT zo, zd, h, count(*) AS n0, median(ms) AS med0 FROM jd
        GROUP BY 1, 2, 3 HAVING count(*) >= {FACTOR_MIN_POOLED} ORDER BY 1, 2, 3""").df()
    m = cell.merge(pooled, on=["zo", "zd", "h"])
    m["ratio"] = m.med / m.med0

    raw = (m.groupby(["dt", "h"])
             .agg(factor_raw=("ratio", "median"), cells=("ratio", "size"))
             .reset_index())
    share = con.sql("SELECT dt, h, count(*) AS journeys FROM jd GROUP BY 1, 2 ORDER BY 1, 2").df()
    f = raw.merge(share, on=["dt", "h"], how="right").fillna({"factor_raw": 1.0, "cells": 0})
    f["w"] = f.journeys / f.groupby("h").journeys.transform("sum")
    norm = (f.factor_raw * f.w).groupby(f.h).transform("sum")
    f["factor"] = f.factor_raw / norm

    if verbose:
        wide = f.pivot(index="h", columns="dt", values="factor")
        span = 100 * (wide.max(axis=1) - wide.min(axis=1))
        print(f"day factors: {len(f)} of {len(DAY_TYPES) * 24}, "
              f"journeys behind the thinnest {int(f.journeys.min()):,}, "
              f"widest hour {span.idxmax():02d}:00 at {span.max():.1f} points")
    return f[["dt", "h", "factor", "factor_raw", "cells", "journeys"]]


def fit(places: int, verbose: bool = True) -> dict:
    """Build every artifact for `places` places. Returns a summary dict for PROVENANCE."""
    con = session()
    bk = [int(v) for v in con.sql(
        "SELECT LocationID FROM z WHERE Borough = 'Brooklyn' ORDER BY LocationID").df().LocationID]
    ids = ",".join(str(i) for i in bk)

    shp = zoning.shapes()
    lab = zoning.contiguous_labels(places, shp, zoning.adjacency(shp))

    # The journeys the matrix is fitted from. Matched shared rides are excluded: a matched
    # ride detours to collect a second party, so its duration describes a different journey.
    vals = ",".join(f"({a},{b})" for a, b in lab.items())
    con.execute(f"CREATE OR REPLACE TEMP VIEW mp AS SELECT * FROM (VALUES {vals}) AS m(lid, z)")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW jj AS
        SELECT mo.z AS zo, md.z AS zd, hour(pickup_datetime) AS h,
               CAST(trip_time * 1000 AS BIGINT) AS ms,
               trip_miles AS miles,
               dayofweek(CAST(pickup_datetime - INTERVAL 4 HOUR AS DATE)) AS dow
        FROM t
        JOIN mp mo ON t.PULocationID = mo.lid
        JOIN mp md ON t.DOLocationID = md.lid
        WHERE t.PULocationID IN ({ids}) AND t.DOLocationID IN ({ids})
          AND shared_match_flag <> 'Y'
          AND trip_time > 0 AND trip_miles > 0
    """)
    j = con.sql("SELECT zo, zd, h, ms, miles FROM jj ORDER BY zo, zd, h").df()
    if verbose:
        print(f"{len(j):,} journeys, {places} places, "
              f"window {' + '.join(CALIBRATION_MONTHS)}")

    # ---- distance: the mean of a route's recorded distances -----------------------------------
    route = (j.groupby(["zo", "zd"], sort=True)
              .agg(n=("miles", "size"), mean_miles=("miles", "mean"))
              .reset_index())
    route["distance_m"] = np.rint(route.mean_miles * M_PER_MILE).astype(np.int64)

    # Straight line between place centers, as a plausibility reference and the last-resort value
    # for a route nobody travelled. Never the primary value.
    cent = (shp.assign(place=shp.LocationID.map(lab))
               .groupby("place")[["X", "Y"]].mean())          # feet, EPSG:2263
    grid_r = pd.MultiIndex.from_product([range(places), range(places)],
                                        names=["zo", "zd"]).to_frame(index=False)
    dx = cent.X.values[grid_r.zo] - cent.X.values[grid_r.zd]
    dy = cent.Y.values[grid_r.zo] - cent.Y.values[grid_r.zd]
    grid_r["crow_m"] = np.rint(np.hypot(dx, dy) * 0.3048).astype(np.int64)
    dist = grid_r.merge(route[["zo", "zd", "n", "distance_m"]], how="left")
    unmeasured = dist.distance_m.isna()
    # An intra-place crow distance is 0 by construction, which would make speed undefined. Half the
    # place's own radius is the same rule grid-v1 uses for its diagonal.
    same = unmeasured & (dist.zo == dist.zd)
    if same.any():
        area_ft2 = shp.assign(place=shp.LocationID.map(lab)).groupby("place").area_sqmi.sum()
        radius_m = np.sqrt(area_ft2 / np.pi) * M_PER_MILE
        dist.loc[same, "crow_m"] = np.rint(radius_m.values[dist.loc[same, "zo"]] / 2).astype(np.int64)
    dist["rung"] = np.where(unmeasured, RUNGS[4], RUNGS[1])
    dist["distance_m"] = dist.distance_m.fillna(dist.crow_m).astype(np.int64)
    dist["n"] = dist.n.fillna(0).astype(np.int64)

    # ---- duration: 48 knots per (route, hour) with the fallback ladder -------------------------
    ms = j.ms.to_numpy()
    key = (j.zo.to_numpy() * places + j.zd.to_numpy()) * 24 + j.h.to_numpy()
    order = np.argsort(key, kind="stable")
    key_s, ms_s = key[order], ms[order]
    starts = np.searchsorted(key_s, np.arange(places * places * 24), side="left")
    ends = np.searchsorted(key_s, np.arange(places * places * 24), side="right")

    def sample_for(zo: int, zd: int, hours) -> np.ndarray:
        parts = []
        for h in hours:
            k = (zo * places + zd) * 24 + h
            if ends[k] > starts[k]:
                parts.append(ms_s[starts[k]:ends[k]])
        return np.concatenate(parts) if parts else np.empty(0, dtype=ms.dtype)

    # The rung-4 prior: every measured cell's knots, grouped by how far the route is. Built once.
    prior_bins = np.array([0, 1500, 3000, 5000, 8000, 12000, 20000, np.inf])
    measured_rows, measured_dist = [], []

    rows = []
    for zo in range(places):
        for zd in range(places):
            for h in range(24):
                own = sample_for(zo, zd, [h])
                if own.size >= MIN_JOURNEYS:
                    rung, use = 1, own
                else:
                    nb = sample_for(zo, zd, [(h - 1) % 24, h, (h + 1) % 24])
                    if nb.size >= MIN_JOURNEYS:
                        rung, use = 2, nb
                    else:
                        allh = sample_for(zo, zd, range(24))
                        if allh.size >= MIN_JOURNEYS:
                            rung, use = 3, allh
                        else:
                            rung, use = 4, None
                if use is None:
                    rows.append((zo, zd, h, own.size, 4, None))
                    continue
                q = _percentiles(np.sort(use))
                rows.append((zo, zd, h, own.size, rung, q))
                if rung == 1:
                    measured_rows.append(q)
                    measured_dist.append(dist.distance_m.values[zo * places + zd])

    # Fill rung 4 from the distance-conditioned prior: the elementwise median of the knots of every
    # measured cell whose route falls in the same distance band, rescaled to this route's distance.
    if measured_rows:
        M = np.vstack(measured_rows)
        md = np.asarray(measured_dist, dtype=float)
        band_of = np.digitize(md, prior_bins) - 1
        prior = {b: np.median(M[band_of == b], axis=0) for b in np.unique(band_of)}
        prior_all = np.median(M, axis=0)
        prior_dist = {b: np.median(md[band_of == b]) for b in np.unique(band_of)}
    else:                                              # pragma: no cover - a pack with no data
        prior, prior_all, prior_dist = {}, np.zeros(len(KNOTS)), {}

    out = []
    for zo, zd, h, n, rung, q in rows:
        if q is None:
            d = float(dist.distance_m.values[zo * places + zd])
            b = int(np.digitize([d], prior_bins)[0] - 1)
            base = prior.get(b, prior_all)
            ref = prior_dist.get(b, max(np.median(md) if measured_rows else 1.0, 1.0))
            q = base * (d / ref if ref > 0 else 1.0)     # same speed, this route's length
        out.append((zo, zd, h, n, RUNGS[rung], *np.rint(q).astype(np.int64)))

    cols = ["zo", "zd", "h", "n", "rung"] + [f"q{i:02d}" for i in range(len(KNOTS))]
    dur = pd.DataFrame(out, columns=cols)
    qv = dur[[f"q{i:02d}" for i in range(len(KNOTS))]].to_numpy(dtype=float)

    # A cell's knots must be non-decreasing: a quantile function that goes backwards would let
    # `interp` return a duration outside the observed range. Ties are legal and common in the body.
    bad = int((np.diff(qv, axis=1) < 0).any(axis=1).sum())
    if bad:
        raise RuntimeError(f"{bad} cells have decreasing knots")

    dur.insert(5, "expectation_ms", np.rint(expectation_from_knots(qv)).astype(np.int64))

    # ---- write ---------------------------------------------------------------------------------
    factors = fit_day_factors(con, places, verbose)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    zpath = zoning.write_places(f"brooklyn-{places}-v1", places)
    dpath = ARTIFACTS / f"duration-{places}-v1.csv"
    xpath = ARTIFACTS / f"distance-{places}-v1.csv"
    fpath = ARTIFACTS / f"daytype-{places}-v1.csv"
    dur.to_csv(dpath, index=False)
    dist[["zo", "zd", "n", "distance_m", "crow_m", "rung"]].to_csv(xpath, index=False)
    factors.to_csv(fpath, index=False)

    census = dur.rung.value_counts().to_dict()
    summary = {
        "places": places,
        "journeys": int(len(j)),
        "cells": int(len(dur)),
        "rung_census": census,
        "measured_pct": round(100 * census.get("measured", 0) / len(dur), 2),
        "routes": int(len(dist)),
        "routes_measured": int((dist.rung == "measured").sum()),
        "zoning": zpath.name,
        "duration_file": dpath.name,
        "distance_file": xpath.name,
        "daytype_file": fpath.name,
        "day_factor_span_pct": round(float(
            100 * (factors.pivot(index="h", columns="dt", values="factor").max(axis=1)
                   - factors.pivot(index="h", columns="dt", values="factor").min(axis=1)).max()), 1),
    }

    prov = ARTIFACTS / f"PROVENANCE-{places}-v1.toml"
    prov.write_text(_provenance(summary, [zpath, dpath, xpath, fpath]))
    if verbose:
        print(f"wrote {zpath.relative_to(ROOT)}")
        print(f"wrote {dpath.relative_to(ROOT)}   {len(dur):,} cells")
        print(f"wrote {xpath.relative_to(ROOT)}   {len(dist):,} routes")
        print(f"wrote {fpath.relative_to(ROOT)}    {len(factors)} day factors")
        print(f"wrote {prov.relative_to(ROOT)}")
        print(f"rungs: {census}")
    return summary


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _provenance(s: dict, files: list[Path]) -> str:
    raw = [p.name for p in sorted(RAW.glob("fhvhv_tripdata_*.parquet"))
           if p.name.split("_")[-1][:7] in CALIBRATION_MONTHS]
    lines = [
        "# Written by eda/fit_travel.py. Every artifact an evaluation depends on is named and hashed here,",
        "# so a result can be traced to the data it came from.",
        "",
        "[fit]",
        f'generated = "{dt.datetime.now().astimezone().isoformat(timespec="seconds")}"',
        f"months = {list(CALIBRATION_MONTHS)!r}".replace("'", '"'),
        f"places = {s['places']}",
        f"journeys = {s['journeys']}",
        f"knots = {len(KNOTS)}",
        f"min_journeys = {MIN_JOURNEYS}",
        'shared_matched = "excluded"',
        'events_included = "heat wave and Independence Day weekend — travel keeps both, '
        'notebook 04 section 1.1"',
        "",
        "[coverage]",
        f"cells = {s['cells']}",
        f"measured_pct = {s['measured_pct']}",
        "",
        "[day_type]",
        'treatment = "multiplier on the pooled cell, not a fifth index"',
        f"types = {list(DAY_TYPES)!r}".replace("'", '"'),
        f"factors = {len(DAY_TYPES) * 24}",
        f"widest_hour_span_pct = {s['day_factor_span_pct']}",
    ]
    lines += [f'rung_{k} = {v}' for k, v in sorted(s["rung_census"].items())]
    lines += ["", "[inputs]"] + [f'raw_{i} = "{n}"' for i, n in enumerate(raw)]
    # The bytes, not just the names. Naming the file says which month; the digest says which copy of
    # it, which is what makes a fitted artifact traceable to the data it came from.
    lines += ["", "[inputs.sha256]"] + [f'"{n}" = "{_digest(RAW / n)}"' for n in raw]
    lines += ["", "[outputs]"]
    for p in files:
        lines.append(f'"{p.name}" = "{_digest(p)}"')
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--places", type=int, default=20,
                    help="number of places (default: %(default)s)")
    args = ap.parse_args()
    fit(args.places)
    return 0


if __name__ == "__main__":
    sys.exit(main())
