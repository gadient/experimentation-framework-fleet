"""Shared data access for the EDA notebooks.

One definition of "the working set" lives here, so notebook 02 cannot quietly
disagree with notebook 01 about which trips count. Notebooks do:

    from common import session
    con = session()          # duckdb connection over CALIBRATION_MONTHS, views `t` and `z`
    con = session("2025-08")  # or one month, to score a fit against it

The heavy table is never loaded into memory — duckdb queries the parquet in
place and only the small aggregate results become dataframes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ssl
import sys
import tomllib
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import certifi
import duckdb
import pandas as pd

# The python.org macOS build ships no CA bundle; point urllib at certifi.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# NYC Open Data — FHV Base Aggregate Report (dataset id 2v9c-2k7f). Monthly
# dispatched trips and unique dispatched vehicles per TLC base. This is the only
# public source for vehicle counts: the trip records carry no vehicle identifier.
BASE_AGGREGATE_URL = "https://data.cityofnewyork.us/resource/2v9c-2k7f.csv"

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

#: The bytes every fit was made from. `data/raw/` is not tracked, so this is the only record.
DIGESTS = Path(__file__).resolve().parent / "raw-digests.toml"

# Calibration WINDOW. Pinned post-congestion-pricing (the Manhattan CBD toll began
# Jan 2025 and moved travel times). Two months rather than one: a single month
# leaves the Saturday day type resting on four days, and two months carry it to
# seven. The cost is that the window is entirely summer.
CALIBRATION_MONTHS = ("2025-06", "2025-07")

#: First month of the window. Kept because a per-month artifact (the base-aggregate
#: vehicle counts) is still fetched for one month, not the window.
CALIBRATION_MONTH = CALIBRATION_MONTHS[0]

# Test month. Fitted artifacts are SCORED against this and never refitted on it.
# Looking at it spends it: after a fit is scored here, August can no longer
# answer "does this generalize" for a later fitting choice.
TEST_MONTH = "2025-08"

# Held-out month. Different season, same regulatory regime. DO NOT look at this
# until the final experiment runs — its value is that it has not informed any modeling
# choice.
HOLDOUT_MONTH = "2025-10"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


#: One full digest per file per process. Hashing a month of trip records costs about a second, and a
#: notebook opens a session more than once.
_digested: dict[str, str] = {}


def verify_raw(paths: Sequence[Path], full: bool = True) -> list[str]:
    """Check raw files against eda/raw-digests.toml. Returns one line per problem, empty when clean.

    Sizes are compared on every call and cost nothing. The SHA-256 of a given file is computed at
    most once per process.

    **This reports; it does not raise.** A digest that has moved most often means the TLC
    republished that month in place rather than that the copy is damaged, and refusing to run would
    present an upstream revision as a broken repository. The caller decides what to do about it.
    """
    if not DIGESTS.exists():
        return [f"{DIGESTS.name} is missing, so the raw files cannot be checked"]
    expected = tomllib.loads(DIGESTS.read_text())["artifacts"]
    problems: list[str] = []
    for p in paths:
        want = expected.get(p.name)
        if want is None:
            problems.append(f"{p.name} is not listed in {DIGESTS.name}")
            continue
        if not p.exists():
            continue
        size = p.stat().st_size
        if size != want["bytes"]:
            problems.append(f"{p.name}: {size:,} bytes on disk against {want['bytes']:,} expected")
            continue
        if not full:
            continue
        got = _digested.get(p.name) or _sha256(p)
        _digested[p.name] = got
        if got != want["sha256"]:
            problems.append(
                f"{p.name}: sha256 {got[:12]}... on disk against {want['sha256'][:12]}... expected"
            )
    return problems


def parquet_path(month: str = CALIBRATION_MONTH) -> Path:
    return RAW / f"fhvhv_tripdata_{month}.parquet"


def month_bounds(month: str) -> tuple[str, str]:
    """(inclusive start, exclusive end) as ISO dates."""
    start = dt.date.fromisoformat(f"{month}-01")
    end = dt.date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def window_bounds(months: Sequence[str]) -> tuple[str, str]:
    """(inclusive start, exclusive end) spanning consecutive months.

    Raises on a gap: a window with a hole in it would silently average two
    separated periods, and the day counts a fit reports would not describe the
    days it actually used.
    """
    ordered = sorted(months)
    for a, b in zip(ordered, ordered[1:]):
        if month_bounds(a)[1] != month_bounds(b)[0]:
            raise ValueError(f"calibration window is not contiguous: {a} then {b}")
    return month_bounds(ordered[0])[0], month_bounds(ordered[-1])[1]


def base_aggregate_path(month: str = CALIBRATION_MONTH) -> Path:
    """Where the cached base-aggregate CSV lives. Separate from the loader so
    fetch_data.py can digest the file into MANIFEST.txt without parsing it."""
    return RAW / f"fhv_base_aggregate_{month}.csv"


def base_aggregate(month: str = CALIBRATION_MONTH) -> pd.DataFrame:
    """Per-base dispatched trips and unique vehicles for one month.

    Cached to data/raw/ on first call so the notebook is not tied to the API
    being reachable, and so a rerun sees identical bytes.
    """
    year, mon = month.split("-")
    cache = base_aggregate_path(month)

    if not cache.exists():
        query = f"?$where=year={year} AND month={int(mon)}&$limit=5000"
        url = BASE_AGGREGATE_URL + urllib.parse.quote(query, safe="?$=&")
        with urllib.request.urlopen(url, timeout=60, context=SSL_CTX) as resp:
            cache.write_bytes(resp.read())

    return pd.read_csv(cache)


def session(months: str | Sequence[str] = CALIBRATION_MONTHS) -> duckdb.DuckDBPyConnection:
    """Connection exposing two views over one month or a contiguous window.

    `t` — the working set. Filtered on `request_datetime` inside the window
    (the files are partitioned by pickup time, so requests spill across the
    boundary) and on positive miles and duration, which drops a handful of
    degenerate rows.

    `z` — the 263 TLC taxi zones: LocationID, zone name, borough.

    A string is accepted for a single month, so `session("2025-08")` still reads
    one month — which is how the test month is scored without being pooled into
    the fit.
    """
    if isinstance(months, str):
        months = (months,)
    months = tuple(months)

    paths = [parquet_path(m) for m in months]
    missing = [(m, p) for m, p in zip(months, paths) if not p.exists()]
    if missing:
        cmds = " && ".join(f"uv run eda/fetch_data.py --month {m}" for m, _ in missing)
        raise FileNotFoundError(f"{[str(p) for _, p in missing]} missing — run: {cmds}")

    # Check the bytes before duckdb reads them. Without this the notebooks derive every figure
    # from whatever happens to be on disk and say nothing about which bytes those were.
    for problem in verify_raw([*paths, RAW / "taxi_zone_lookup.csv"]):
        print(f"raw data: {problem}", file=sys.stderr)

    lo, hi = window_bounds(months)
    files = ", ".join(f"'{p}'" for p in paths)
    con = duckdb.connect()
    con.execute(f"""
        CREATE VIEW raw AS SELECT * FROM read_parquet([{files}]);
        CREATE VIEW t AS SELECT * FROM raw
            WHERE request_datetime >= DATE '{lo}'
              AND request_datetime <  DATE '{hi}'
              AND trip_miles > 0
              AND trip_time  > 0;
        CREATE VIEW z AS SELECT * FROM read_csv('{RAW / "taxi_zone_lookup.csv"}');
    """)
    return con
