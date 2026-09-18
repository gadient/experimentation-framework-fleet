# Experimental framework for policy comparisons

This document presents a framework for evaluating whether a candidate operating policy should replace
a baseline policy under declared operating conditions. Results are not published here. A policy assigns vehicles to requests, initiates repositioning, and
directs vehicles to charge. The resulting conclusions apply to the declared operating and input
models.

The design uses paired replications. Each pair holds the scenario and random future constant while
changing the policy. Policy development, experiment sizing, and the final evaluation use separate
seed sets.

## 1. Outcomes and decision roles

Each experiment assigns every key performance indicator one of three roles:

- **Primary:** the outcome that must improve by at least a declared amount.
- **Guardrail:** an outcome for which the experiment must rule out deterioration beyond a declared
  limit.
- **Diagnostic:** a reported outcome that helps explain the result but does not determine the
  decision.

The following four measures would decide a Brooklyn policy comparison. Timely service is the headline
and primary outcome. The declaration can add further diagnostics.

| KPI | Identifier | Role | Per replication definition |
|---|---|---|---|
| Timely service: on time pickup rate | `timely_service_pct` | Primary | Reporting window requests picked up within the configured service threshold, divided by all requests arriving in the window. Declines, system rejections, and abandonments remain in the denominator. |
| Quote decline rate | `decline_share_pct` | Guardrail | Requests that receive an estimated pickup time and decline it, divided by all requests arriving in the reporting window. |
| Empty km per request | `empty_km_per_arrival` | Guardrail | Distance traveled without a passenger on legs beginning in the reporting window, divided by all requests arriving in the window. |
| Total charger queue time | `queue_vehicle_hours` | Diagnostic | Vehicle time spent waiting for a charge point, summed across the fleet and clipped to the reporting window. |

The service threshold is a declared scenario control. The current Brooklyn dataset pack uses ten
minutes. A policy effect on timely service is reported in percentage points.

The guardrails address two ways in which the primary outcome could improve at an unacceptable cost.
A policy could produce shorter observed waits by inducing more riders to decline, or it could improve
vehicle positioning through excessive empty travel. Charger queue time records whether the policy
also transfers capacity pressure to charging.

Other measures, including pickup wait, abandonment, feasible vehicle coverage, low charge exposure,
and site power, remain available as diagnostics. They do not enter the decision unless the experiment
declaration assigns them a deciding role and provides the corresponding threshold.

## 2. Experimental unit and paired differences

The experimental unit is one complete replication. A seed fixes the random future. The baseline and
candidate policies are evaluated with the same seed, scenario, initial conditions, fitted inputs, and
configuration.

For seed `s` and KPI `j`, the paired difference is:

```text
d[s,j] = Y_candidate[s,j] - Y_baseline[s,j]
```

Direction is declared for every KPI so that the report identifies whether a positive raw difference
is an improvement or a deterioration.

Each KPI is calculated within a replication before the paired difference is formed. Counts and records from
different replications are not pooled. Ratios across replications are means of per replication ratios, and percentiles
are calculated within each replication before they are summarized across replications. Riders in one replication share fleet
capacity, vehicle locations, and charging resources and are not independent experimental units.

## 3. Primary and guardrail tests

The primary test asks whether the improvement exceeds the smallest effect worth acting on. Let `g[s]`
be the paired effect after orienting the KPI so that positive values indicate improvement, and let `B`
be the required gain.

```text
H0: mean(g) <= B
H1: mean(g) > B
```

The primary passes when the one sided lower confidence bound for `mean(g)` is greater than `B`.

For a guardrail, let `h[s]` be the paired effect oriented so that positive values indicate
deterioration, and let `H` be the largest acceptable deterioration.

```text
H0: mean(h) >= H
H1: mean(h) < H
```

The guardrail passes when the one sided upper confidence bound for `mean(h)` is less than `H`. A
confidence interval that includes zero can still satisfy a guardrail if it rules out deterioration
larger than `H`.

The required gain and harm limits are operational inputs. They are declared before the comparison and
are not selected from the observed effect or pilot variance. Diagnostic KPIs receive estimates and
intervals but no pass or fail result.

The primary analysis uses a paired t interval on the vector of per pair differences. A bootstrap that
resamples complete pairs is reported as a sensitivity calculation when the differences are skewed or
influenced by a small number of pairs.

## 4. Decision rule

A candidate is approved only when all of the following conditions hold:

1. the primary test passes;
2. every guardrail passes;
3. every declared seed has one valid baseline replication and one valid candidate replication;
4. all replication and cohort validation checks pass; and
5. the declaration matches the policy versions, scenario, input artifacts, KPI roles, thresholds,
   and seeds recorded with the replications.

The reported outcome is `approve`, `decline`, `no verdict`, or `experiment invalid`. A result that
does not approve the candidate may reflect an insufficient primary gain, a guardrail breach, or
insufficient precision. The report identifies the relevant condition.

A development or pilot seed bank cannot produce an approval or decline. Results from those banks
describe effects, variability, and required sample size.

## 5. Multiple decision requirements

Approval is a joint claim that the primary and every guardrail meet their requirements. Because all
deciding tests must pass, a false approval requires at least one false rejection among the
requirements whose null condition is true. Testing each component at level `alpha` therefore bounds
the false approval probability at `alpha`, regardless of dependence among the KPIs.

This result applies only to the joint approval claim. It does not provide simultaneous confidence
coverage for every interval in the report or support separate claims that each KPI improved. When
individual KPI claims are required, the report must use simultaneous intervals or an explicit
multiplicity adjustment.

Adding guardrails reduces the probability that a suitable policy clears every requirement. The
noisiest deciding KPI can therefore determine the required number of pairs.

## 6. Seed separation and experiment declaration

Seeds are stored in disjoint, versioned banks. Each bank carries a digest so that the report can
identify the exact set used.

| Bank | Purpose | May inform policy selection | May determine the final decision |
|---|---|---:|---:|
| Development | Debugging and policy tuning | Yes | No |
| Pilot | Estimating paired variation and experiment size | Yes | No |
| Confirmation | Evaluating the locked candidate | No | Yes |
| Stress | Sensitivity to assumptions and operating conditions | No | No |

The sequence is:

1. develop and tune policies on development seeds;
2. estimate paired variability on pilot seeds;
3. select the candidate and declare the scenario, policy versions, fitted inputs, KPI roles,
   required gain, guardrail limits, significance level, and confirmation seeds;
4. determine the confirmation sample size from the pilot variation; and
5. evaluate the locked comparison on the confirmation bank.

The confirmation replication count is fixed before its results are inspected. Adding seeds after
reviewing an interim result changes the error rate and is not permitted under this design. A change to
the declaration produces a new digest and requires a new comparison.

## 7. Common random numbers

Both policies face the same underlying request arrivals, origins, destinations, patience values, and
travel draws within each pair. Random values are keyed to individual requests, trips, and vehicles
rather than to the order in which a policy requests them. The match therefore persists after the
policies make different decisions and consume different numbers of random values.

The two operating histories are expected to diverge after the policies act. Pairing requires the same
underlying random field, not identical event histories.

The report provides the correlation between the baseline and candidate values and the resulting
variance reduction for each KPI. Weak correlation indicates that pairing provides little precision
benefit for that measure.

## 8. Replication validity and reporting

A replication must finish with a valid terminal state and pass the validation checks. An invalid
replication is treated as an experiment defect rather than as an ordinary missing observation. The
experiment remains invalid pending diagnosis because excluding a policy induced failure could bias
the comparison.

A KPI with no valid denominator is reported as unavailable rather than as zero. The report also
records the number of included and excluded replications, the paired standard deviation, confidence interval,
one sided decision bound, declared threshold, seed bank, and declaration digest.

The same attribution rule is applied in both arms. Requests belong to the reporting window in which
they arrive, even when their later outcome occurs during cooldown or drain. Time based quantities are
clipped to the reporting window. Distance is assigned to the window in which a leg begins because the
state representation does not record a vehicle's position partway through a leg.

## 9. Scope of inference

Within the declared operating model, the paired comparison estimates the effect of changing the policy
while holding the scenario, initial conditions, fitted inputs, and random future fixed. Three sources
of uncertainty remain distinct:

- **Stochastic variation:** results vary across random futures. Additional independent pairs reduce
  this uncertainty.
- **Input uncertainty:** demand, travel time, and patience are estimated or assumed. Repeating one
  fitted model does not measure this uncertainty.
- **Model fidelity:** the operating model simplifies or omits operational mechanisms. Additional
  replications do not address those omissions.

The paired experiment directly addresses stochastic variation. Input uncertainty requires refitting
or sampling alternative input models. Model fidelity requires external evidence, additional
mechanisms, or comparison with observed operations.

The Brooklyn input evidence and its retained limitations are summarized in
[`docs/eda-findings-nyc.md`](eda-findings-nyc.md).

## References

1. Sara Shashaani, “Simulation Optimization: An Introductory Tutorial on Methodology,” *Proceedings
   of the 2024 Winter Simulation Conference*. The tutorial discusses independent evaluation of
   selected solutions and variance reduction through common random numbers.
   <https://informs-sim.org/wsc24papers/inv215.pdf>
2. Linyun He and Eunhye Song, “Simulation Optimization Under Input Uncertainty,” *Proceedings of the
   2024 Winter Simulation Conference*. The paper distinguishes ordinary stochastic variation from
   uncertainty in the fitted input model.
   <https://informs-sim.org/wsc24papers/inv219.pdf>
