"""Fetch the pinned TLC source files for the EDA stage.

Everything downstream derives from these four artifacts — the trip records, the
zone lookup, the zone polygons, and the base-aggregate vehicle counts. The month is pinned so
the analysis is reproducible from a fresh clone; pass --month to override for a
sensitivity check.

    uv run eda/fetch_data.py
    uv run eda/fetch_data.py --month 2025-01

Files land in data/raw/, which is gitignored, and their sizes and digests go to
data/raw/MANIFEST.txt. That file is written from whatever is on disk, so it records rather than
verifies. Each artifact is therefore also compared against eda/raw-digests.toml, which is tracked
and holds the bytes every fitted artifact was made from; a file that differs is reported instead of
being recorded as though it were expected.
"""

from __future__ import annotations

import argparse
import hashlib
import ssl
import sys
import tomllib
import urllib.request
from pathlib import Path

import certifi

# The calibration month is defined once, in common.py, and imported here. Two
# copies of a pinned constant is one copy too many: they drift, and the drift is
# silent because each file still looks self-consistent. The rationale for the pin
# lives with the definition.
from common import CALIBRATION_MONTH as DEFAULT_MONTH

BASE = "https://d37ci6vzurychx.cloudfront.net"

# The python.org macOS build has no system CA bundle, so urllib fails TLS
# verification out of the box. Point it at certifi rather than skipping checks.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MANIFEST = RAW_DIR / "MANIFEST.txt"


def sources(month: str) -> list[tuple[str, str]]:
    """(url, local filename) for the pinned month."""
    return [
        # ~490 MB, ~20M high-volume for-hire trips (Uber/Lyft/Via/Juno).
        (f"{BASE}/trip-data/fhvhv_tripdata_{month}.parquet", f"fhvhv_tripdata_{month}.parquet"),
        # LocationID -> zone name + borough, for the 263 TLC taxi zones.
        (f"{BASE}/misc/taxi_zone_lookup.csv", "taxi_zone_lookup.csv"),
        # Zone polygons: centroids for the zone matrix, geometry for choropleths.
        (f"{BASE}/misc/taxi_zones.zip", "taxi_zones.zip"),
    ]


def remote_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        length = resp.headers.get("Content-Length")
    return int(length) if length else None


def download(url: str, dest: Path, expected: int | None) -> None:
    """Stream to a .part file, then move into place, so an interrupted run
    never leaves a truncated file looking complete."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    done = 0
    with urllib.request.urlopen(url, timeout=60, context=SSL_CTX) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if expected:
                pct = 100 * done / expected
                print(f"\r  {done / 1e6:8.1f} / {expected / 1e6:.1f} MB  ({pct:5.1f}%)", end="")
    print()
    if expected is not None and tmp.stat().st_size != expected:
        tmp.unlink()
        raise RuntimeError(f"size mismatch for {url}: expected {expected}, got {done}")
    tmp.replace(dest)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default=DEFAULT_MONTH, help="YYYY-MM (default: %(default)s)")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    entries = []

    for url, name in sources(args.month):
        dest = RAW_DIR / name
        expected = remote_size(url)

        if dest.exists() and not args.force and (expected is None or dest.stat().st_size == expected):
            print(f"present  {name}")
        else:
            print(f"fetching {name}")
            download(url, dest, expected)

        entries.append((name, dest.stat().st_size, sha256(dest), url))

    # The base-aggregate CSV is fetched lazily by common.base_aggregate() when a
    # notebook first asks for vehicle counts. Pull it here too, so all four raw
    # artifacts carry a digest: a manifest that covers three of four files reads
    # as complete provenance while one input is unpinned.
    from common import BASE_AGGREGATE_URL, base_aggregate, base_aggregate_path

    agg = base_aggregate_path(args.month)
    if agg.exists() and not args.force:
        print(f"present  {agg.name}")
    else:
        print(f"fetching {agg.name}")
        agg.unlink(missing_ok=True)
        base_aggregate(args.month)
    entries.append((agg.name, agg.stat().st_size, sha256(agg), BASE_AGGREGATE_URL))

    # Merge into whatever the manifest already records, keyed by filename. A
    # calibration window spans several months (common.CALIBRATION_MONTHS), and
    # each is fetched by a separate run of this script — so rewriting the file
    # with only this run's entries would drop the digest of every month fetched
    # before it, leaving a manifest that reads as complete provenance while
    # covering one of the raw inputs the analysis actually reads.
    merged: dict[str, tuple[str, int, str, str]] = {}
    if MANIFEST.exists():
        lines = MANIFEST.read_text().splitlines()
        for head, url in zip(lines[::2], lines[1::2]):
            digest, size, name = head.split(None, 2)
            merged[name] = (name, int(size), digest, url.strip())
    for name, size, digest, url in entries:
        merged[name] = (name, size, digest, url)

    # Compare against the tracked expectation before recording. Rewriting the manifest from disk is
    # exactly what made the old one unable to disagree with it. The digests were computed above, so
    # nothing is hashed twice here.
    from common import DIGESTS

    expected = tomllib.loads(DIGESTS.read_text())["artifacts"] if DIGESTS.exists() else {}
    differs = []
    for name, _size, digest, _url in entries:
        want = expected.get(name)
        if want is None:
            differs.append(f"{name} is not listed in {DIGESTS.name}")
        elif want["sha256"] != digest:
            differs.append(f"{name}: got {digest[:12]}..., expected {want['sha256'][:12]}...")
    for line in differs:
        print(f"  DIFFERS  {line}")
    if differs:
        print(f"\n{len(differs)} artifact(s) differ from {DIGESTS.name}. Either the local copy is "
              "damaged,\nor the TLC republished in place — they revise files after publication. "
              "Re-fetch with\n--force and compare. If upstream moved, update that file in its own "
              "commit, so a change\nto the analysis inputs appears in the history.")

    MANIFEST.write_text(
        "\n".join(f"{d}  {s:>12}  {n}\n    {u}"
                  for n, s, d, u in sorted(merged.values())) + "\n"
    )
    print(f"\nwrote {MANIFEST}  ({len(merged)} artifacts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
