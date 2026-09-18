"""Zonings: the mapping from TLC taxi zones to decision zones.

A zoning is configuration, not code. Each is a CSV in `config/zoning/` with one
row per TLC `LocationID`, so alternative aggregations can be compared rather than
one being fixed in code, since the right zone count is an empirical question.

    from zoning import load, available, attach
    available()                 # ['borough', 'service_zone', ...]
    attach(con, "borough")      # adds a duckdb view `dz`; join on location_id

The operating model never sees taxi zones. A zoning is applied upstream, when the rate
table and zone matrix are built:

    263 taxi zones --[zoning]--> N decision zones --> rate table + matrix --> sim

CSV over JSON deliberately: it diffs cleanly in git, so a zoning change is
reviewable line by line.

Regenerate the baseline zonings (both fall out of the TLC lookup, no analysis):

    uv run eda/zoning.py --rebuild
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ZONING_DIR = ROOT / "config" / "zoning"

COLUMNS = ["location_id", "zone_id", "zone_label"]


def available() -> list[str]:
    """Names of every zoning on disk."""
    return sorted(p.stem for p in ZONING_DIR.glob("*.csv"))


def load(name: str) -> pd.DataFrame:
    """A zoning as location_id -> zone_id, zone_label."""
    path = ZONING_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"no zoning {name!r}; available: {available()}")

    df = pd.read_csv(path)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns {sorted(missing)}")
    if df.location_id.duplicated().any():
        dupes = df.location_id[df.location_id.duplicated()].tolist()
        raise ValueError(f"{path} maps these location_ids more than once: {dupes}")
    return df[COLUMNS]


def attach(con, name: str, view: str = "dz") -> pd.DataFrame:
    """Register a zoning as a duckdb view. Returns the loaded frame.

    The frame is bound into the connection rather than inlined as SQL, so a
    zoning with hundreds of rows costs nothing to attach.
    """
    df = load(name)
    con.register(f"_{view}_src", df)
    con.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM _{view}_src")
    return df


def summary(name: str) -> pd.DataFrame:
    """Decision zones in a zoning, with how many taxi zones each absorbs."""
    df = load(name)
    return (df.groupby(["zone_id", "zone_label"], as_index=False)
              .location_id.count()
              .rename(columns={"location_id": "taxi_zones"})
              .sort_values("taxi_zones", ascending=False, ignore_index=True))


# --------------------------------------------------------------------------
# Algorithm-derived places. One implementation, read
# by notebook 04 (travel time) and notebook 05 (demand), so the two cannot fit
# their artifacts on different maps. Heavy imports stay inside the functions so
# `load`/`attach` work without geopandas.
# --------------------------------------------------------------------------

ADJACENCY_TOL_FT = 50.0   # two zones touch if their outlines come within this


def shapes(borough: str = "Brooklyn"):
    """Taxi-zone polygons of one borough in EPSG:2263 (NY State Plane, feet),
    with centroid columns `X`, `Y`, `area_sqmi` and `zone` name."""
    import geopandas as gpd
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import RAW

    shp = gpd.read_file(f"zip://{RAW / 'taxi_zones.zip'}!taxi_zones/taxi_zones.shp")
    g = shp[shp.borough == borough].to_crs(2263).copy().reset_index(drop=True)
    g["X"] = g.geometry.centroid.x
    g["Y"] = g.geometry.centroid.y
    g["area_sqmi"] = g.geometry.area / 27_878_400
    return g


def adjacency(g, tol_ft: float = ADJACENCY_TOL_FT):
    """Symmetric 0/1 matrix over the rows of `g`: 1 where two outlines come
    within `tol_ft`. Each polygon is buffered by half the tolerance."""
    import numpy as np
    from scipy.sparse import csr_matrix

    buf = g.geometry.buffer(tol_ft / 2)
    A = np.zeros((len(g), len(g)), dtype=int)
    for i in range(len(g)):
        for j in buf.sindex.query(buf.iloc[i], predicate="intersects"):
            if i != int(j):
                A[i, int(j)] = A[int(j), i] = 1
    return csr_matrix(A)


def contiguous_labels(k: int, g=None, adj=None) -> dict[int, int]:
    """LocationID -> place, for `k` places. Ward-linkage agglomerative merging
    on zone centroids, allowed only between zones that touch. Deterministic:
    the algorithm draws nothing."""
    from sklearn.cluster import AgglomerativeClustering

    g = shapes() if g is None else g
    adj = adjacency(g) if adj is None else adj
    m = AgglomerativeClustering(n_clusters=k, connectivity=adj, linkage="ward").fit(g[["X", "Y"]])
    return {int(lid): int(lab) for lid, lab in zip(g.LocationID, m.labels_)}


def write_places(name: str, k: int) -> Path:
    """Write `config/zoning/<name>.csv` for `k` contiguous Brooklyn places."""
    g = shapes()
    lab = contiguous_labels(k, g)
    names = (pd.DataFrame({"location_id": g.LocationID, "zone": g.zone})
               .assign(zone_id=lambda d: d.location_id.map(lab)))
    label = names.groupby("zone_id").zone.apply(lambda s: " / ".join(sorted(s)))
    out = (names.assign(zone_label=names.zone_id.map(label))[COLUMNS]
                .sort_values("location_id"))
    ZONING_DIR.mkdir(parents=True, exist_ok=True)
    path = ZONING_DIR / f"{name}.csv"
    out.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------
# Baseline zonings. Both fall straight out of the TLC lookup — no analysis, no
# judgment. They exist so the zoning seam has a second consumer alongside the
# algorithm-derived zonings.
# --------------------------------------------------------------------------

def _rebuild() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import RAW

    lookup = pd.read_csv(RAW / "taxi_zone_lookup.csv")
    ZONING_DIR.mkdir(parents=True, exist_ok=True)

    for name, col in [("borough", "Borough"), ("service_zone", "service_zone")]:
        labels = sorted(lookup[col].dropna().unique())
        ids = {label: i for i, label in enumerate(labels)}
        out = (pd.DataFrame({
                    "location_id": lookup.LocationID,
                    "zone_id": lookup[col].map(ids),
                    "zone_label": lookup[col]})
                 .dropna(subset=["zone_id"])
                 .astype({"zone_id": int})
                 .sort_values("location_id"))

        path = ZONING_DIR / f"{name}.csv"
        out.to_csv(path, index=False)
        print(f"wrote {path.relative_to(ROOT)}  "
              f"{len(out)} taxi zones -> {out.zone_id.nunique()} decision zones")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="regenerate baseline zonings")
    args = ap.parse_args()

    if args.rebuild:
        _rebuild()
    elif not available():
        print("no zonings yet — run with --rebuild")
    else:
        for n in available():
            df = load(n)
            print(f"{n:16} {len(df):>4} taxi zones -> {df.zone_id.nunique():>3} decision zones")
