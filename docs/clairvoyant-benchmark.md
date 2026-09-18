# A clairvoyant benchmark for fleet dispatch

An electric mobility service must assign vehicles to arriving requests while managing their location,
availability, and stored energy. A policy comparison estimates the effect of changing those operating
decisions. It does not establish how close either policy came to the best result available from the
same fleet state and realized demand.

This document presents a framework for constructing a Clairvoyant (perfect information) benchmark
that provides this reference. For each realized day, the benchmark observes the complete request sequence and the
fleet state at the start of the reporting window. A mixed-integer program then maximizes the number of
requests collected within the service threshold. The benchmark is retrospective and uses future
requests that an online policy cannot observe.

The mathematical target is `N*`, the largest timely pickup count attainable by any trajectory
permitted by the declared dispatch rules from the same initial state. The program produces an
executable conservative value `L` and an optimistic value `U`. Execution establishes `L <= N*`. The
interpretation of `U` as an upper bound depends on whether the program represents every trajectory
permitted by the operating model. The restrictions in section 6 make `U` a conditional upper
comparison. Results are not published here.

## 1. Operational setting

The operating model represents a battery-electric fleet within a closed service region. Each request
has an arrival time, origin, destination, assignment deadline, and rider-specific tolerance for the
quoted pickup time. An assigned vehicle drives empty to the origin, collects the rider, and completes
the passenger journey. The vehicle remains unavailable until that work is complete. Requests may
instead be declined, rejected by the system, or abandoned while waiting.

At regular invocation times, a policy can assign available vehicles, direct idle vehicles to another
zone, and send vehicles to charge. These actions use the same fleet capacity. Repositioning may place a
vehicle closer to a later request, while consuming time and energy and reducing coverage elsewhere.
Charging restores energy while temporarily removing a vehicle from service. Each decision changes the
locations, energy levels, and availability times presented to later requests.

### Timely service

A request is timely when pickup occurs no more than ten minutes after the request arrives. The timely
service rate divides timely pickups by every request arriving in the reporting window. Declines,
system rejections, and abandonments remain in the denominator. The benchmark maximizes the count of
timely pickups because the number of arrivals is fixed within a realized instance.

The ten-minute threshold is a scenario parameter rather than an estimate fitted from observed pickup
times. In the pooled Uber and Lyft records used for the Monday through Wednesday demand calculation,
completed Brooklyn trips have a mean request-to-pickup interval of 4.5 minutes. That sample excludes
requests that were never served and therefore cannot estimate rider patience or define a service
requirement. The observed interval also reflects operations in physical space, whereas the zonal model
represents vehicle and rider locations through aggregate zones.

The Brooklyn inputs aggregate the borough into 20 decision zones. Under that representation, none of
the 400 expected zone-pair travel times is five minutes or less; the minimum is 7.2 minutes. Pickup
within the rider's zone is represented by approximately 9.5 to 10.7 minutes of travel. A five-minute threshold
would largely measure the lower tail of the zonal travel approximation and would leave little scope
for policy decisions to affect the result. Ten minutes was selected as the shortest threshold that
clears the model's travel-time floor while remaining restrictive.

This choice is a modeling tradeoff. Modeled timely service at ten minutes is not directly comparable
with the observed 4.5-minute mean because the two quantities use different spatial representations and
sampling processes.

## 2. Inputs and interpretation

The Brooklyn inputs are fitted from New York City Taxi and Limousine Commission High Volume
For-Hire Vehicle records for June and July 2025. The demand artifact contains 7,089,190 completed trips
with both endpoints in Brooklyn, represented by day type, origin, destination, and request hour. The
travel artifact contains 7,857,311 completed passenger journeys, represented by origin, destination,
and hour. Brooklyn's 61 taxi zones are aggregated into 20 contiguous decision zones.

The source records contain completed trips rather than all attempted requests. Demand levels are
conditional on the fitted completed-trip distribution and a declared capture share. The capture share
and the fleet size are scenario parameters rather than estimates of market share or of the fleet
required to serve Brooklyn.

Travel dispersion is disabled when a benchmark instance is built. Each movement then takes the expected
duration in the matrix cell selected by its origin, destination, and departure hour, and the benchmark
cannot improve the objective by selecting favorable travel-time draws.

### Outputs

For each policy and realized day, the inputs to the benchmark are the policy's timely pickup count `Np`
and the fleet state at the start of the reporting window. The benchmark combines that state with the
realized requests in the window and reports `L` and `U`. All three values refer to the same request
sequence and policy-produced initial state. Differences in `L` and `U` across policies also reflect
differences in those initial states and are not estimates of a policy effect.

A policy may exceed `L` because `L` is the value of one feasible conservative plan. When `Np > L`, the
policy supplies a stronger attainable value, and the lower benchmark becomes `max(L, Np)`. `N*` remains
the perfect-information optimum. When the upper coverage condition also holds, the policy's share of
the optimum satisfies:

```text
Np / U <= Np / N* <= Np / max(L, Np)
```

## 3. Perfect-information objective

Fix a realized day, a reporting window, and the fleet state at the start of that window. Let the
reachable set contain every trajectory that can be generated from that state by instructions permitted
by the dispatch rules. For each trajectory, count the requests arriving in the reporting window whose
pickups occur within the service threshold. `N*` is the largest count over the reachable set.

For an evaluated policy, `Np` is its timely pickup count on the same realized day. The policy's own
trajectory belongs to the reachable set, so:

```text
Np <= N*
```

This relation follows from the definition of `N*` and does not depend on the mixed-integer model.

The benchmark instance contains every request time, origin, destination, assignment deadline, and
acceptance threshold during the reporting window. It also contains expected movement durations and
distances and each vehicle's location, next available time, and stored energy at the start of the
window. These quantities make the optimization instance deterministic.

## 4. Conservative and optimistic solves

Travel duration depends on departure hour. Passenger journeys begin at modeled pickup times, so the
program selects their departure hour exactly. The program does not explicitly represent the departure
time of the initial movement to a first rider, approaches between consecutive riders, movements to and
from the depot, or within-zone movements to pickup. Their feasible departure intervals may cross an
hour boundary inside the reporting window.

The same program is therefore solved under two travel duration assignments:

- **Conservative solve.** Each affected movement receives the longest expected duration over its
  feasible departure hours. The resulting schedule is executed under the same operating rules.
  Rider-level agreement between the schedule and its execution establishes an attainable value `L`.
- **Optimistic solve.** Each affected movement receives the shortest expected duration over its
  feasible departure hours. This relaxes the travel-time component and produces `U`. The relation
  `N* <= U` also requires the remaining formulation to represent every trajectory permitted by those
  operating rules.

When the conservative execution succeeds and the optimistic formulation has complete coverage:

```text
L <= N* <= U
```

The two solves keep the program small while measuring the approximation introduced by time-dependent
travel: `U - L` bounds the effect of fixing each affected movement's duration before solving.

## 5. Mixed-integer formulation

A vehicle's work during the reporting window is represented as a path through the requests it serves.
The network contains three arc types:

- an entry arc from a vehicle's initial state to its first request;
- a rider arc between consecutive requests served by the same vehicle; and
- a depot arc that inserts a charging visit, in fifteen-minute increments, between two requests.

An arc is omitted when its estimated arrival time would cause the rider to reject the quote. Binary
variables select arcs and identify collected and timely requests. Continuous variables record pickup
times and stored energy after each passenger journey.

The principal constraints require:

- each vehicle to enter at most one path;
- each collected request to have one predecessor and at most one successor;
- pickup times to respect passenger travel, empty approaches, and charging visits;
- vehicles to commit by the rider's assignment deadline;
- timely requests to be collected within ten minutes;
- stored energy to remain above the reserve required to reach the depot;
- total charging increments to fit the aggregate capacity of the declared charge points; and
- selected work to fit the available vehicle time over the complete window and selected subintervals.

The program also permits a vehicle to reach a request zone before the request arrives, wait there, and
then complete the within-zone pickup movement. This represents coordinated prepositioning enabled by
future information. The vehicle must arrive one full policy invocation interval before the request.

The objective is the number of timely pickups.

## 6. Conditions and verification

### Attainable value

The conservative solution records the assigned vehicle, pickup time, departure time, service mode, and
request order for every selected rider. To establish `L`, the fleet follows that schedule during the
reporting window and follows the originating policy outside it, so that the benchmark begins from the
same fleet state.

The relation `L <= N*` requires execution to reproduce the scheduled rider outcomes. Reconciliation
is performed rider by rider because offsetting errors could leave the aggregate count unchanged.

### Conditional upper value

The relation `N* <= U` requires every trajectory permitted by the operating model to be representable
in the optimistic formulation. Three rules in the formulation are stricter than the declared operating
rules:

1. A vehicle waiting in a request zone must arrive one complete invocation interval before the
   request.
2. Pickups after the reporting window are excluded, although a request arriving before the end of the
   window may be collected afterward and still count as timely under the evaluation rules.
3. Each rider receives at most one quote.

Until their combined effect is measured, `U` is a conditional upper comparison rather than a certified
upper bound on unrestricted `N*`.

Each solve also reports two diagnostic counts: selected riders whose vehicle departs after the
assignment deadline and selected riders whose passenger journey duration does not match the travel
matrix at the planned pickup time. Both counts must be zero.
