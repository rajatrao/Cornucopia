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

## Phase 4: CP-SAT optimizer

Planned. See IMPLEMENTATION_PLAN.md.
