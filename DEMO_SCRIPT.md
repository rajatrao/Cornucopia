# Demo script (about 5 minutes)

Open **https://cornucopia-delta.vercel.app** and sign in.

**Setup (already done on the Sprite).** The Sprite runs the organization **Thanksgiving Community Food Rescue (demonstration data)**, slug `thanksgiving-2026-demo`. It was seeded through the public API by `scripts/seed_sample.py --label "" --quinoa-lb 130`:

| Resource | Quantity |
|---|---|
| Rice (Harvest Co-op) | 180 lb |
| Potatoes | 120 lb |
| Carrots | 100 lb |
| Pantry staples: butter | 10 lb |
| Pantry staples: olive oil | 2 gal |
| Pantry staples: quinoa | 130 lb |
| Volunteers | 12 (8 cooks, 3 drivers, 1 coordinator) |
| Delivery routes | 3 (North, Central, South), 200 meals each |
| Commitments | 500 Thanksgiving plates: Riverside Shelter 200, Oak Street Senior Center 150 (dairy-free), Eastside Family Pantry 150 |

The plate is rice pilaf, mashed potatoes and roasted carrots. Substitution rule: quinoa may replace rice 1:1 in the pilaf. Nothing about the outcome is pre-computed. Everything below is decided live by the agent, the CP-SAT optimizer and the validator.

To reset, deploy a fresh organization slug and seed it again. See `DEPLOYMENT.md`.

## 1. The operation (Command Center, `/`)
- Sign in as an approver (for example `raj`).
- The tiles show **500 committed**, **500 feasible right now**, the agent online, and no pending approvals.
- The inventory health chart shows stock against need for every ingredient.

## 2. Reality changes (Event Center, `/events`)
- Choose **Donation cancelled**, pick **Rice donation**, and enter the reason "The rice donation has been cancelled. All 500 meals remain committed."
- Submit. The event is journaled in Supabase, together with its effect (180 lb removed), in one transaction.
- Submitting twice does not cancel twice: the idempotency key returns the same event.

## 3. The agent recompiles (Agent `/executions`, Recompilation `/recompilation`)
- Within seconds the Sprite worker claims the event. Its timeline runs receive → validate → classify → state → dependencies → impact → strategy → plan → CP-SAT → validate → compare → report → request approval.
- **Reality Recompilation** shows the React Flow graph: the cancelled donation → its lot → Rice → Rice pilaf → cooking batch → the plate → all 3 commitments. Potatoes and carrots are untouched.
- In the rehearsal run, the optimizer found that 500 of 500 meals are still possible by replacing the rice with quinoa (1 substitution, `verified_feasible`). Without recovery the answer would be 0.

## 4. Human approval (Approval Center, `/approvals`)
- The proposal shows plan vN, its fingerprint, the state version it was computed against, the commitments, and the changes (substitution, allocations).
- **Approve and commit** stays disabled until the confirmation box is ticked.
- Optional: sign in as an `operator`-role account and try to approve. The attempt is refused as *unauthorized* and recorded in the decision history.
- Confirm. The worker resumes the paused graph. `commit_approved_plan` re-verifies the approval, fingerprint, state version and lease, then applies batches, stock reservations, routing and planned meals in one transaction. The audit log attributes it to the approver, and the outbox emits a notification.
- The Command Center now shows **Committed plan: 500 (plan vN)** and a notification "Plan vN committed by raj: 500 of 500 meals".

## 5. Interrupt and restart (resilience)
```bash
sprite exec -s cornucopia -- sprite-env services signal cornucopia-worker KILL
```
Run this while the agent is processing an event. The Sprite restarts the worker. After the lease expires (≤ 60 s) the same execution resumes as attempt 2 from its last checkpoint, with no duplicated optimizer runs or commits. The Agent page shows the `resumed` step.

## 6. When resources are insufficient (escalation)
- In the Event Center, choose **Ingredient expired**, pick the Potatoes lot, and enter the reason "Cold-storage failure".
- No substitution exists for potatoes. In the rehearsal run, the optimizer proved 0 of 500 meals possible (`verified_partial`) and the agent **escalated** with: *"To serve every serviceable meal, the operation is missing: Potatoes 120.0 lb (after using every valid substitution)."*
- It does not invent a plan, and nothing is committed.

## 7. What-if without touching production (Simulation Lab, `/simulation`)
- Run **Multiple simultaneous failures**. The real optimizer runs on a copy of the state, and the result shows before and after. No records are written.

## 8. Audit (Audit `/history`)
- Every row change shows its actor: the operator, the agent, or `operator:<approver> (approved plan vN)` for committed changes.

## Script it

`scripts/run_scenarios.py --approve` performs steps 2–6 against the API and prints what the system decided.

| Rehearsal run (org `thanksgiving-2026-rehearsal`) | Result |
|---|---|
| Scenario 1 | proposal 500/500 → approved → committed (plan v2) |
| Scenario 2 | escalated, Potatoes 120.0 lb short |
| Total time | 70 s |
