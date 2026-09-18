# Fleet policy experimentation framework

This repository presents a framework for evaluating fleet dispatch policies under stochastic demand
and travel conditions. The framework connects empirical input construction, paired policy
comparisons, predefined decision criteria, and a Clairvoyant (perfect information) reference.
Brooklyn, New York provides the empirical case.

The notebooks and scripts reproduce the construction of the Brooklyn demand and travel inputs. The
supporting documents specify the experimental design, the benchmark formulation, and the retained
limitations. Results are not published here.

## Framework components

| Component | Role in the framework | Published material |
|---|---|---|
| Empirical inputs | Defines demand, travel, geography, and their uncertainty | [`eda/`](eda/), [`datasets/nyc-brooklyn/`](datasets/nyc-brooklyn/) |
| Experiment declaration | Records policies, input versions, seed bank, KPI roles, and decision thresholds before evaluation | [`docs/experimental-framework.md`](docs/experimental-framework.md) |
| Paired comparison | Exposes the baseline and candidate to the same initial conditions and random future | [`docs/experimental-framework.md`](docs/experimental-framework.md) |
| Promotion decision | Requires a declared improvement in timely service while limiting deterioration in guardrail measures | [`docs/experimental-framework.md`](docs/experimental-framework.md) |
| Perfect information reference | Compares online policy outcomes with attainable and optimistic reference values for the same realized demand | [`docs/clairvoyant-benchmark.md`](docs/clairvoyant-benchmark.md), [`optimization/model/clairvoyant.pdf`](optimization/model/clairvoyant.pdf) |

The framework separates policy development from final evaluation. Development and pilot seed banks may
inform policy selection and experiment size. A separate confirmation bank evaluates the locked policy
and declaration. Stress seeds examine sensitivity but do not determine promotion.

## Brooklyn empirical case

The source data are the New York City Taxi and Limousine Commission High Volume For Hire Vehicle trip
records. The initial assessment uses June 2025. The demand and travel inputs use June and July 2025,
and August 2025 provides a later evaluation sample.

The Brooklyn input model has the following structure:

- **Service region.** Trips must begin and end in Brooklyn. Among the large borough markets,
  Brooklyn combines substantial pickup volume with the highest observed share of trips that remain
  within the borough.
- **Spatial representation.** Brooklyn's 61 taxi zones are aggregated into 20 contiguous decision
  zones. This improves support for origin, destination, and hour cells while removing some local
  travel and passenger flow variation.
- **Demand.** Hourly rates are estimated for four day types: Monday through Wednesday, Thursday and
  Friday, Saturday, and Sunday. A demand date runs from 04:00 through 03:59 so that late night demand
  remains associated with the preceding evening. This convention does not constrain when an evaluation
  period begins.
- **Travel duration.** Each origin, destination, and hour cell contains 48 empirical quantiles.
  Sparse cells use a documented fallback hierarchy based on adjacent hours, the full route, or a
  distance based prior.
- **Distance.** Each ordered zone pair has one mean passenger trip distance. This preserves average
  distance while removing journey level distance and energy variation.

The records contain completed trips rather than all attempted requests. Rejected, canceled,
abandoned, and unserved requests are absent. The fitted demand table therefore estimates the spatial
and temporal distribution of recorded trips. Its level is controlled by a configurable capture
share. Latent demand cannot be recovered from these data alone.

The fixed hourly Poisson demand model is compact and reproducible, but it understates variation across
dates, omits correlated changes among cells, and smooths demand within each hour. Thursday and Friday
remain pooled despite a material late night difference. The June and July fit also exceeds the August
demand level by 6.0 to 7.6 percent across day types. The complete evidence and retained tradeoffs are
reported in [`docs/eda-findings-nyc.md`](docs/eda-findings-nyc.md).

## Reproducing the input analysis

The analysis requires Python 3.12 or later.

```bash
python -m pip install certifi duckdb geopandas jupyterlab mapclassify matplotlib numpy pandas scikit-learn scipy
```

No individual trip records are distributed with this repository. Download the June through August
source files before running the notebooks. June and July form the calibration window, and August is
used for evaluation.

```bash
python eda/fetch_data.py --month 2025-06
python eda/fetch_data.py --month 2025-07
python eda/fetch_data.py --month 2025-08
```

The files are stored in `data/raw/`, which is excluded from version control. The complete download is
approximately 1.4 GB. [`eda/raw-digests.toml`](eda/raw-digests.toml) records the expected file sizes
and SHA 256 digests. The retrieval script and notebooks compare local files with these records before
using them.

Run the notebooks in numerical order:

1. [`01_first_look.ipynb`](eda/01_first_look.ipynb)
2. [`02_demand_structure.ipynb`](eda/02_demand_structure.ipynb)
3. [`03_heat_travel_time.ipynb`](eda/03_heat_travel_time.ipynb)
4. [`04_travel_time.ipynb`](eda/04_travel_time.ipynb)
5. [`05_demand.ipynb`](eda/05_demand.ipynb)

```bash
jupyter lab
```

The notebooks query the Parquet files through DuckDB and do not load each complete monthly file into
memory. Rebuild the fitted inputs with:

```bash
python eda/fit_travel.py
python eda/fit_demand.py
```

Both commands write to `datasets/nyc-brooklyn/artifacts/`. The travel fit also writes the Brooklyn
zone map to `config/zoning/`, which is excluded from version control.

## Published experiment inputs

The published artifacts comprise:

- 38,400 hourly demand rates for four day types, 20 origins, 20 destinations, and 24 hours;
- 48 travel duration quantiles for each represented origin, destination, and hour cell;
- one mean distance for each of the 400 ordered zone pairs; and
- travel adjustment factors by day type and hour.

The demand table is estimated from 7,089,190 completed Brooklyn trips. The artifacts contain
aggregate counts, rates, quantiles, means, and identifiers. They contain no individual trip record,
timestamp, route, vehicle, driver, license, or company identifier.

The source window, exclusions, fitted date counts, input hashes, and output hashes are recorded in
[`PROVENANCE-20-v1.toml`](datasets/nyc-brooklyn/artifacts/PROVENANCE-20-v1.toml) and
[`PROVENANCE-demand-20-v1.toml`](datasets/nyc-brooklyn/artifacts/PROVENANCE-demand-20-v1.toml).
Declared operating assumptions are recorded in
[`datasets/nyc-brooklyn/pack.toml`](datasets/nyc-brooklyn/pack.toml).

## Experimental design

The experimental unit is one complete replication. Each seed produces a matched baseline and candidate
pair with the same scenario, initial conditions, fitted inputs, and random future. Random quantities are
assigned to individual requests, trips, and vehicles so the match remains valid after policy actions
produce different event histories.

Each key performance indicator receives a declared decision role:

| KPI | Role | Definition |
|---|---|---|
| Timely service | Primary | Share of reporting window requests collected within the configured service threshold |
| Quote decline rate | Guardrail | Share of reporting window requests that receive and reject a quoted pickup time |
| Empty km per request | Guardrail | Distance traveled without a passenger per reporting window request |
| Charger queue time | Diagnostic | Vehicle hours spent waiting for a charge point during the reporting window |

Declines, system rejections, and abandonments remain in the timely service denominator. Timely
service therefore measures availability across all requests arriving in the reporting window.

The promotion rule is specified before confirmation replications begin. Timely service must exceed its
required improvement, both guardrails must remain within their allowed deterioration, every declared
pair must be present, and all validity checks must pass. The outcome is recorded as `approve`,
`decline`, `no verdict`, or `experiment invalid`. Diagnostic measures explain the result but do not
determine promotion unless they are assigned a decision role in a new declaration.

Paired differences are calculated within each replication. Requests from different replications are
not pooled, and requests within one replication are not treated as independent experimental units.
Common random numbers reduce variance when baseline and candidate outcomes remain correlated.

The full statistical specification appears in
[`docs/experimental-framework.md`](docs/experimental-framework.md).

## Clairvoyant reference

The Clairvoyant (perfect information) benchmark is a framework for measuring how close a policy came to
the best attainable result. It evaluates a realized day using the full request sequence and the fleet
state at the start of the reporting window. Its target, `N*`, is the largest timely pickup count
attainable from that state under the declared dispatch rules. Online policies do not observe future
requests.

The mixed integer program reports two reference values. A conservative schedule, executed under the
same operating rules, establishes an attainable value `L <= N*`. An optimistic solve reports `U`.
Interpreting `U` as an upper bound on `N*` requires the formulation to include every trajectory
permitted by the dispatch rules. Restrictions on invocation timing, pickups after the reporting
window, and repeated quotes make `U` a conditional upper comparison.

`L` is the value of one attainable conservative schedule and need not equal the optimum. A policy can
therefore exceed `L`. In that case the policy outcome replaces `L` as the stronger attainable value.
`N*` remains the perfect information optimum.

The formulation and its coverage conditions are documented in
[`docs/clairvoyant-benchmark.md`](docs/clairvoyant-benchmark.md) and
[`optimization/model/clairvoyant.pdf`](optimization/model/clairvoyant.pdf).

## Interpretation

The framework is designed to estimate the effect of changing a policy while holding the declared
operating conditions, empirical inputs, and random future fixed within each pair. It does not estimate the
fleet required to serve Brooklyn or predict absolute service levels in observed operations. Fleet
size, capture share, service threshold, vehicle characteristics, and charging capacity are study
parameters. The fleet itself is a hypothetical operation defined for study purposes and is not a
description of an existing service.

Three sources of uncertainty remain distinct:

- variation across random futures is addressed through independent paired replications;
- uncertainty in fitted demand and travel inputs requires refitting or sampling alternative inputs;
  and
- model fidelity requires external operational evidence or additional mechanisms.

## License, data terms, and citation

The repository is licensed under the [Apache License 2.0](LICENSE). The project license does not alter
the terms governing the source data.

The trip records, taxi zone lookup table, and taxi zone boundaries are published by the
[New York City Taxi and Limousine Commission](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).
No TLC trip record is redistributed here. Additional attribution and data details appear in
[`NOTICE`](NOTICE).

Citation metadata are provided in [`CITATION.cff`](CITATION.cff).

## AI usage

AI tools assisted with design discussion, implementation, documentation, and review. The author made
the modeling decisions and is responsible for the resulting analysis and conclusions.
