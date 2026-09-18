# Findings from the NYC HVFHV exploratory analysis

This document summarizes the evidence used to construct the Brooklyn demand and travel inputs. The
supporting analyses are:

1. [initial assessment](../eda/01_first_look.ipynb);
2. [temporal and spatial demand structure](../eda/02_demand_structure.ipynb);
3. [travel time during the June heat event](../eda/03_heat_travel_time.ipynb);
4. [Brooklyn travel time and distance estimation](../eda/04_travel_time.ipynb); and
5. [Brooklyn demand estimation](../eda/05_demand.ipynb).

The initial assessment uses June 2025. The fitted demand and travel inputs use June and July 2025.
August 2025 is used to evaluate the fitted demand table.

The source is the New York City Taxi and Limousine Commission High Volume For Hire Vehicle trip
record dataset. It contains completed trips. Requests that were rejected, canceled, abandoned, or
never served are absent. The fitted rates therefore describe recorded demand associated with
completed trips and do not estimate latent demand. The fitted outputs and their input hashes are
recorded in the [travel provenance](../datasets/nyc-brooklyn/artifacts/PROVENANCE-20-v1.toml) and
[demand provenance](../datasets/nyc-brooklyn/artifacts/PROVENANCE-demand-20-v1.toml) files.

## Summary

The implemented dataset uses a closed Brooklyn service region divided into 20 contiguous decision
zones. Demand is represented by hourly rates for four day types. Travel duration is represented by
48 empirical quantiles for each origin, destination, and hour cell, supplemented by a documented
fallback hierarchy. Distance is represented by one arithmetic mean for each ordered pair of decision
zones.

The main retained limitations are:

- the demand level is based on completed trips and a configurable capture share;
- Thursday and Friday remain pooled despite a material difference in late night demand;
- fixed Poisson rates understate variation across dates and do not represent correlated demand
  changes;
- spatial aggregation removes variation within decision zones;
- one route distance suppresses journey level distance and energy variation;
- passenger trip travel inputs are applied to empty vehicle movements without direct validation; and
- the June and July demand level exceeds the August evaluation level by 6.0 to 7.6 percent.

## Findings

### Data coverage and demand measurement

| No. | Analysis | Result and interpretation |
|---:|---|---|
| 1 | June record count and validity filters | The June file contains 19.87 million trips. Request, vehicle arrival, pickup, and dropoff timestamps are complete in the analyzed fields. Positive distance and duration filters retain 99.96 percent of records, so no imputation step is used. |
| 2 | Monthly dispatched vehicle counts | The June aggregate report lists 71,571 unique vehicles for Uber and 54,778 for Lyft. Vehicles may appear under both providers, so the distinct combined count is between 71,571 and 126,349. The aggregates do not measure simultaneous vehicle availability. |
| 3 | Trips divided by reported vehicles | The corresponding exposure ratios are 6.6 trips per vehicle day for Uber and 3.5 for Lyft. Any vehicle dispatched during the month enters the denominator, so these ratios are not estimates of continuous utilization. They are not used to infer fleet capacity. |
| 4 | Observed demand boundary | Every demand record is a completed trip. Latent requests and abandonment are unavailable. The fitted table estimates the spatial and temporal distribution of recorded trips. Its level in an experiment is set by the configurable capture share. Demand uncensoring would require request, cancellation, acceptance, and contemporaneous supply data. |
| 5 | Service classes | The demand fit retains shared, wheelchair accessible, and Access A Ride records but does not model separate service classes. The travel fit excludes matched shared rides because their movement can include another passenger's detour. Service outcomes for riders requiring an accessible vehicle cannot be evaluated. |

### Temporal demand

| No. | Analysis | Result and interpretation |
|---:|---|---|
| 6 | June hourly volume | Mean weekday volume ranges from 6,661 requests at 03:00 to 37,939 at 08:00, a ratio of 5.7. Mean weekend volume ranges from 12,255 at 05:00 to 37,707 at 18:00, a ratio of 3.1. Demand varies materially by hour and day of week. |
| 7 | Calibration dates | The demand fit contains 54 complete demand dates after excluding two incomplete boundary periods and six externally identified event dates. The sample contains 24 Monday through Wednesday dates, 15 Thursday and Friday dates, 7 Saturdays, and 8 Sundays. Pooling June and July improves cell support, but July demand is lower on most weekdays. |
| 8 | June heat event and Independence Day period | Brooklyn demand is 14.7, 23.8, and 6.8 percent above the corresponding weekday means on June 23 through 25. It is 6.0, 20.2, and 9.2 percent below the corresponding means on July 4 through 6. Both periods are excluded from baseline demand estimation. Their effects must be introduced separately when those conditions are studied. |
| 9 | Day of week profiles | The June citywide peak moves from 08:00 on Monday through Wednesday to 19:00 on Thursday, 22:00 on Friday and Saturday, and 00:00 on Sunday. The Brooklyn fit uses four day types: Monday through Wednesday, Thursday and Friday, Saturday, and Sunday. |
| 10 | Demand date convention | A demand date runs from 04:00 through 03:59, assigning late night demand to the preceding evening. This classification convention does not prescribe the start time of a run. The dataset pack defines the warmup period, and a run may begin at any time. |
| 11 | Monthly Brooklyn passenger flow | Brooklyn records 5,353,864 passenger arrivals and 5,353,441 departures in June, a net difference of 423 trips. The near zero monthly total does not imply hourly or local balance because positive and negative flows offset across time and zones. |
| 12 | Thursday and Friday pooling | Thursday and Friday normalized profiles differ by 7.3 percent. On the Friday demand date, mean demand is 67.5 to 120.9 percent higher from midnight through 03:00. The difference is 4.9 to 6.8 percent during the 16:00 through 18:00 reporting period. Pooling is retained for sample support but overstates Thursday night and understates Friday night. |
| 13 | Variation across dates | For high volume cells representing 77.3 percent of fitted demand, the median dispersion index is 1.64 and 38.5 percent exceed the approximate upper Poisson reference. Daily standard deviations are 15.8 to 33.5 times those implied by fixed Poisson rates. Fixed rates therefore understate variation across dates. |
| 14 | Variation within an hour | Holding rates constant within each hour produces a request weighted difference of 1.87 to 2.25 percent from the observed quarter hour distribution. The most affected hour differs by 6.54 to 9.57 percent, depending on day type. The hourly representation is close in aggregate but smooths localized demand ramps. |

### Geographic scope and spatial demand

| No. | Analysis | Result and interpretation |
|---:|---|---|
| 15 | Pickup share by borough | Manhattan accounts for 35.8 percent of June pickups, Brooklyn for 27.3 percent, Queens for 22.4 percent, the Bronx for 12.8 percent, and Staten Island for 1.6 percent. Volume alone does not identify a preferred service region. |
| 16 | Within borough retention | Using all destination codes, 75.6 percent of trips originating in Brooklyn remain there, compared with 66.4 percent for Manhattan and 65.0 percent for Queens. After unresolved destination codes are excluded, the corresponding values are 76.7, 71.6, and 69.7 percent. Brooklyn provides the strongest observed combination of pickup volume and internal retention among the large borough markets. |
| 17 | Closed Brooklyn sample | In June and July, 10,658,762 completed trips begin in Brooklyn. Of these, 8,033,670, or 75.37 percent, also end there. The demand model excludes the remaining 24.63 percent and all trips entering Brooklyn from elsewhere. Cross boundary distance, energy use, and vehicle redistribution are absent. |
| 18 | Citywide origin and destination coverage | The June sample contains 60,749 observed ordered pairs among 68,643 possible pairs, or 88.5 percent. Hourly disaggregation creates sparse cells and motivates spatial aggregation. |
| 19 | Airport concentration | LaGuardia and John F. Kennedy International Airport are the two highest volume pickup zones, with approximately 437,000 and 344,000 June pickups. Their inclusion materially affects the demand attributed to Queens. They are outside the selected Brooklyn region. |
| 20 | Entropy diagnostics | Destination entropy ranges from 3.79 to 6.70 bits but is associated with pickup volume and observed destination coverage. Normalized temporal entropy ranges from 0.843 to 0.995, with borough means from 0.966 to 0.973. Neither measure determines the implemented zoning. |
| 21 | Passenger flow imbalance | At the 61 taxi zone resolution, hourly passenger flow imbalance equals 7.2 percent of internal weekday trips and reaches 17.2 percent at 06:00. At the implemented 20 zone resolution, the Monday through Wednesday index is 5.9 percent, compared with 7.6 percent at 61 zones for the same request cohorts. Aggregation removes approximately 23 percent of the measured imbalance. This statistic describes passenger redistribution and is not an estimate or lower bound for empty repositioning. |

### Spatial aggregation and travel inputs

| No. | Analysis | Result and interpretation |
|---:|---|---|
| 22 | Choice of 20 decision zones | Brooklyn's 61 taxi zones are merged into 20 contiguous decision zones containing one to six taxi zones each. At 61 zones, the median observed origin, destination, and hour cell contains 22 trips and 43.5 percent of observed cells meet the 30 trip threshold. At 20 zones, the median is 200 trips and 85.3 percent of observed cells meet the threshold. The analysis does not identify 20 as a unique optimum. |
| 23 | Candidate zone counts | Sixteen zones provide greater direct coverage but remove more spatial and energy variation. Twenty four zones preserve more variation but increase the unweighted share of cells using a duration fallback from 15.92 to 21.81 percent. Twenty zones retain the intermediate specification used by both demand and travel inputs. |
| 24 | Travel interval | The travel matrix represents pickup to dropoff time. Request to vehicle arrival and boarding dwell remain separate. For records with nonnegative timestamps, median request to arrival is 3.47 minutes, its 90th percentile is 7.65 minutes, median boarding dwell is 0.65 minutes, and median occupied travel time is 12.75 minutes. Completed trips underrepresent long waits and provide no observations for unserved requests, so these statistics do not estimate patience or determine a service threshold. |
| 25 | Travel duration representation | Within an origin, destination, and hour cell, 27.8 percent of the variance in log trip duration remains unexplained, so a single stored duration for each cell would discard that variation. Blocked cross validation compares empirical quantile grids, lognormal and gamma fits, and a kernel density reference. The 48 and 101 point empirical grids and gamma have similar performance in the leading comparisons. The 48 point grid is retained because it preserves an empirical distribution with fewer stored values than the 101 point grid. It is a supported representation choice rather than a unique statistical optimum. |
| 26 | Duration coverage and fallbacks | Of the 9,600 travel cells, 84.08 percent are measured directly, 7.62 percent use adjacent hours, 7.54 percent use the whole route, and 0.75 percent use a distance based prior. Directly measured cells contain 99.79 percent of observed passenger trips. Fallback accuracy is evaluated on withheld, well observed cells and does not establish accuracy for genuinely unobserved or policy generated movements. |
| 27 | Route distance | The artifact stores one arithmetic mean distance for each of 400 observed ordered zone pairs. This preserves average journey energy closely but reduces journey level energy variation and its upper tail. Vehicle state of charge paths and charging congestion may therefore be more regular than they would be with journey specific distances. |
| 28 | Extreme travel records | The current travel artifacts retain unusual records because no independent validity label is available. Removing the flagged 0.426 percent has little effect on typical duration but materially changes the upper tail of some cells and the mean distance of a small number of routes. Sparse within zone routes are the most exposed. |
| 29 | Day type travel adjustment | Travel distributions pool all calibration dates and apply 96 factors for four day types and 24 hours. A full four type split would reduce direct cell coverage from 84.1 to 57.9 percent. The shared factors improve cross month median duration estimates but leave route specific day effects and variation among weekdays within a type unmodeled. |
| 30 | Event dates in the travel fit | June 23 through 25 remain in the travel fit because the heat comparison finds duration and speed differences within the selected 3 percent materiality threshold. July 4 through 6 also remain because their inclusion changes the median fitted cell by only minus 0.126 percent. Event dates are treated separately in demand and travel because the fitted quantities differ. |

### Demand artifact and evaluation

| No. | Analysis | Result and interpretation |
|---:|---|---|
| 31 | Demand table | Four day types, 20 origins, 20 destinations, and 24 hours produce 38,400 rates. Empty cells account for 4.2 to 6.3 percent of each day type. The highest rate decile contains approximately 58 percent of requests. |
| 32 | Unobserved demand cells | Empty cells are assigned a zero rate. In August, these cells contain 0.010 to 0.045 percent of observed demand, or approximately 11 to 54 requests per date. Their aggregate volume is small, but their operational effect may be larger when a policy depends on an affected location or route. |
| 33 | Capture share | Capture share is a configurable scenario input and is not estimated by the demand artifact. At 5 percent, the approximate peak passenger load is 1.20 for 100 vehicles and 0.80 for 150 vehicles before charging, repositioning, and other unavailable time. Five percent is therefore a capacity constrained scenario for 100 vehicles, not a fixed property of the model. |
| 34 | August demand evaluation | The fitted daily level exceeds August by 6.0 to 7.6 percent across day types. Hourly marginal error is 0.82 to 1.66 percent; origin and destination marginal errors are 1.03 to 2.88 percent and 1.06 to 2.70 percent. Complete origin, destination, and hour error is 4.28 to 7.33 percent and exceeds the 90th percentile of the multinomial sampling reference for every day type. Broad marginal patterns transfer more closely than the complete joint table. |
| 35 | Evaluation status | August was not used for fitting, but its results have now been examined. It is an evaluation sample rather than an untouched holdout. A revision informed by August requires a later sample for independent evaluation. |

## Retained modeling tradeoffs

| Choice | Reason retained | Consequence |
|---|---|---|
| Use completed trips as observed demand | Request time, origin, destination, duration, and distance are available in one consistent source. | Rejected, canceled, abandoned, and otherwise unserved requests are absent. Demand level and service outcomes cannot be interpreted as estimates of latent market demand. |
| Pool Uber and Lyft records | Pooling provides greater support in spatial and hourly cells and matches the aggregate fleet setting. | Provider specific demand, service quality, and operating behavior are not represented. |
| Use a closed Brooklyn region | Brooklyn combines high pickup volume with comparatively high internal retention, and the demand and travel inputs share one regional boundary. | The model excludes cross boundary trips and their distance, energy use, and redistribution effects. |
| Use a 04:00 demand date boundary | The convention keeps midnight through 03:59 with the preceding evening profile. | Demand weekday labels differ from calendar weekdays. The convention does not determine the start time of a run. |
| Exclude identified event dates from demand but retain them in travel | Event demand differs materially from the recurring profile, while fitted travel changes are limited under the analyses used. | Baseline demand contains six fewer dates. Small event related travel differences remain in the pooled travel distributions. |
| Pool June and July | Two months reduce empty demand cells by 27 to 42 percent relative to June alone and improve support for travel cells. | The window covers summer only. It averages monthly changes, and its fitted demand level is above August. |
| Use four demand day types | Pooling improves cell support while preserving the principal differences between weekdays, Saturday, and Sunday. | Thursday and Friday remain materially different late at night. Saturday and Sunday rely on seven and eight fitted dates. |
| Use fixed hourly Poisson arrivals | The model is compact, interpretable, and reproducible from the rate table. | It understates variation across dates, omits correlated changes among cells, and smooths demand within each hour. |
| Use 20 contiguous decision zones | Twenty zones balance direct cell coverage with more spatial detail than the 16 zone alternative and provide one index for demand and travel. | The count is a working choice rather than an estimated optimum. Aggregation removes spatial, distance, energy, and passenger imbalance variation. |
| Store 48 empirical duration quantiles | The grid represents observed skew and upper tails with performance comparable to larger or fitted alternatives. | Sparse cells require fallbacks, stored endpoints depend on observed extremes, and the percentile positions remain defined in fitting code rather than in the CSV schema. |
| Store one mean distance per route | The mean preserves aggregate distance and mean energy while matching the current input interface. | Journey level distance variation and dependence between distance and duration are removed. State of charge trajectories and charging queues may be too regular. |
| Apply passenger travel inputs to empty movements | Passenger trips are the available source with origin, destination, time, duration, and distance. | Travel time and distance for repositioning and pickup approaches are not directly validated. |
| Assign zero demand to unobserved cells | The artifact avoids introducing spatial and temporal patterns without observations. | Rare combinations are understated, even though their aggregate August volume is small. |
| Configure capture share by scenario | The same fitted distribution can be evaluated at different operating loads without treating monthly vehicle counts as simultaneous capacity. | Capture share is an assumption. Absolute service levels and policy behavior near capacity depend on its configured value. |

These limitations carry into policy evaluation results. Sensitivity analysis can measure their effect on
specific policy comparisons, but it does not convert the fitted inputs into estimates of latent demand
or validate unobserved empty vehicle movement.
