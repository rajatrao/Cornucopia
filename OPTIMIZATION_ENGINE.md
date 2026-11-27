# Resource compiler and optimization engine

## Phase 3: deterministic resource compiler (`backend/cornucopia/compiler`, `depgraph`)

Everything here is a pure function of an `OperationalSnapshot`. That snapshot is one consistent read produced by the `get_operational_snapshot` RPC. The compiler does no I/O, reads no clock and uses no randomness. The same snapshot always gives byte-identical output, and a test reshuffles every input table to prove that the result does not depend on row order.

### Calculators

| Calculator | Rule |
|---|---|
| Recipe requirements | Per meal: `line.quantity_base × component portions ÷ recipe yield`, exact Decimal. Optional lines that break a commitment's diet are left out for that commitment and reported. |
| Dietary rules | Each diet forbids a fixed attribute set (vegetarian ⇒ no meat/pork/poultry/fish/shellfish; vegan adds dairy/egg/animal_product; gluten_free, nut_free, dairy_free, halal). A *required* violating ingredient makes the meal unusable for that commitment. |
| Availability | `available` lots with quantity > 0 and not expired by the snapshot time. An expiry date in the past counts even if nobody reported it. Pledged lots are counted only when explicitly requested. |
| Allocation | First-expiring-first; ties break on creation time, then id. |
| Preparation capacity | `rate × available hours × staffing`, where staffing = available cooks ÷ assigned cooks (1 if none assigned), rounded down. |
| Delivery capacity | Route capacity in meals; cancelled or completed routes carry nothing. A route departing after a commitment's due time is reported as a risk. |

Rounding: total consumption per ingredient is `ceil` to 0.001 base units, so the plan never under-allocates. A test at 59.999 lb of rice shows the plan dropping to 249 plates rather than over-drawing.

### Baseline planner

The baseline planner serves commitments in planning order: earliest due first, then creation time, then id. Each commitment gets the largest whole number of meals that the remaining ingredients, preparation capacity and its route allow. The planner records exactly which resource capped each commitment. It then allocates lots FIFO and fills teams in a fixed order. It uses no substitutions; that is the optimizer's job in Phase 4.

### Independent validator

`validate_plan` recomputes every requirement from the snapshot and the plan's *decisions*: planned meals, substitutions and allocations. It checks diets, lot usability, over-allocation, exact allocation totals, substitution rules (scope, ratio, diet, amount), preparation capacity, route capacity and that the state version is current. It shares no bookkeeping with the planner. A plan is shown as feasible only when the validator reports zero violations.

### Substitutions

A substitution option is valid for a recipe when a rule exists for that recipe (or a global one), the substitute breaks no diet of any active commitment whose meal uses the recipe, and there is spare stock. The engine reports how much of the original ingredient the substitute could replace.

### Dependency graph

```
donation → lot → ingredient → recipe → batch → meal → commitment
                  substitute ⇢ recipe
volunteer → team → batch                     delivery → commitment
```

The impact of an event is its origin node plus everything downstream. For a changed commitment, the upstream resources it draws on are included too. Event types map to origins: a donation, a lot, a volunteer, a delivery, a commitment or a team.

### Plan identity and comparison

`canonical_json` gives sorted, normalised decimals and excludes `as_of`. `fingerprint` is its SHA-256. `compare_plans` lists changes to commitments, recipes, ingredient and lot allocations, teams, routes and substitutions. Phase 6 binds approvals to this fingerprint.

## Phase 4: CP-SAT recovery optimizer (`backend/cornucopia/optimizer`)

The optimizer is independent of LangGraph: `optimizer.service.run(snapshot, config, reference)` is a plain function.

### Decision variables

| Variable | Meaning |
|---|---|
| `meals[c]` ∈ 0..requested | meals planned for each active commitment. Fixed at 0 when its meal breaks the commitment's diet, is malformed, or has no usable route. |
| `route[c,d]` | meals of commitment c carried on route d. Only the original route is allowed when rerouting is disabled. |
| `need[r,i]` | mg of ingredient i that recipe r needs: exactly ceil(Σ qty_mg·portions·meals ÷ yield), using integer numerator/denominator |
| `sub_r[k]`, `sub_u[k]`, `sub_z[k]` | per valid substitution option: original replaced (mg), substitute used (= ceil(r·ratio) exactly), rule used |

Substitution options are created only for rules in scope that break no diet of any active commitment using the recipe.

### Hard constraints

- Ingredient use ≤ usable stock, after substitutions.
- Portions ≤ preparation capacity (staffing-aware).
- Meals per route ≤ route capacity; only usable routes.
- Replaced quantity ≤ what the recipe actually needs.
- Diets are enforced structurally: a conflicting commitment's meals are fixed at 0.

### Lexicographic objectives

Each stage fixes the optimum of the one before it.

| # | Objective | Direction |
|---|---|---|
| 1 | commitments fully met ("preserve commitments") | max |
| 2 | meals served | max |
| 3 | change vs. reference plan: Σ\|meals − reference\| + substitution rules used | min |
| 4 | food waste: stock expiring within 72 h left unused (mg) | min |
| 5 | delivery disruption: meals moved off their route + meals on routes departing after the due time | min |
| 6 | earlier-due priority (tie-break) | max |

The reference plan is the approved plan from Phase 6. Until then, stage 3 counts only the substitution rules used.

### Exactness and verification

The solver's decisions are rebuilt with exact Decimal arithmetic: allocations are FIFO by expiry, substitute amounts are `ceil3(replaced × ratio)`, and teams are filled in a fixed order. The result is then checked by the independent validator. The run's `verdict` is the only feasibility label:

- `verified_feasible`: every commitment met, validator clean.
- `verified_partial`: a validated plan that serves fewer meals, with an explanation.
- `unverified`: the validator found violations. This is never shown as feasible.
- `failed`: the solver returned no solution.

A loophole found and closed during testing: substitute use is pinned to exactly ceil(r·ratio). Otherwise the waste objective could "use" expiring stock without replacing anything.

### Infeasibility diagnosis

Every serviceable commitment is forced to its full count and each limit gets a slack. Slacks are minimised in order (ingredients, then preparation, then routes), with substitutions and rerouting still available. Each non-zero slack is reported as a shortfall, for example "Rice 80.0 lb (after using every valid substitution)". Commitments that no resource could fix, such as diet conflicts, are listed as blocked.

### Determinism

The solver uses one search worker, `random_seed = 0`, and `max_deterministic_time` per stage, which is machine independent. A wall-clock cap is a safety net only. Tests and the live Sprite both show identical fingerprints and objectives across repeated runs.

### Candidates

Each run also solves `no_substitutions` and `no_rerouting`, and includes the greedy `baseline`. Each candidate gets its own verdict and a deterministic diff against the recommended plan.

### Performance (demonstration dataset, rice cancelled, 40 lb quinoa)

| Where | Measure |
|---|---|
| Solver, all 6 stages (Sprite) | ≈ 28 ms, 30 variables, 49 constraints |
| Full API call incl. diagnosis, 3 alternatives, persistence via the connector (Sprite) | ≈ 1.0 s |
| Test suite budget | < 10 s for the full run with candidates (actual < 0.1 s) |

Every run is stored append-only in `optimization_runs` and `optimization_results` through the transactional `record_optimization_run` RPC.
