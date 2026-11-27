# Agent workflow

The recovery agent is a LangGraph state machine (`backend/cornucopia/agent`). It runs as its own Fly.io Sprite service, `cornucopia-worker`, separately from the API and the browser. Every decision is deterministic code; no language model is involved.

## Graph

```
START → receive_event → validate_event ─(invalid)──────────────────────────────┐
                           │                                                     │
                     classify_event → update_operational_state                   │
                           → analyze_dependencies → assess_impact                │
                           → select_recovery_strategy ─(nothing at risk)→ record_outcome → END
                                     │
                           generate_candidate_plan ←──(unverified, retries left)──┐
                           → run_cpsat_optimizer → validate_candidate ────────────┤
                                                     │                (no retries)│
                                    compare_plan_versions                         │
                                    → generate_decision_report                    │
                                       ├─(every commitment met)→ request_approval ⏸ (interrupt)
                                       │                          → commit_approved_plan → record_outcome → END
                                       └─(partial)→ investigate_infeasibility ←───┘
                                                    → escalate_to_operator → END
```

| Node | What it does (deterministic) |
|---|---|
| receive_event | Loads the journaled event (tool: `load_event`). |
| validate_event | Checks the type is known and the required payload keys and the recorded effect are present. Invalid events escalate; nothing is guessed. |
| classify_event | Maps the type to a category (supply loss or gain, capacity, demand, delivery) and a severity. |
| update_operational_state | The fact was applied atomically when the event was journaled. This node only confirms the current state version includes it and never re-applies it. |
| analyze_dependencies | NetworkX impact from the event's origin node. |
| assess_impact | Baseline plan now; which affected commitments are short and by how many meals. Earlier shortfalls are reported but not blamed on this event. |
| select_recovery_strategy | No action if nothing this event affects is at risk. Otherwise tries strategies in order: full recovery → no rerouting → no substitutions. |
| generate_candidate_plan / run_cpsat_optimizer | Runs the Phase 4 optimizer with the strategy's options. Each run is persisted with idempotency key `execution:strategy:retry`. |
| validate_candidate | Accepts only `verified_*` verdicts. Otherwise retries with the next strategy, at most `MAX_RETRIES = 2` times. |
| compare_plan_versions | Per-commitment changes versus doing nothing. |
| generate_decision_report | A plain-language report built from a template (no model). |
| request_approval | Calls `propose_plan` (idempotent per execution): creates plan version vN, its change list and a PENDING approval request bound to the fingerprint, the state version, the execution and an expiry, and marks older undecided requests STALE. Then `interrupt()` pauses the graph durably. |
| commit_approved_plan | Runs after a human decides. `claim_next_execution` hands the paused execution to a worker as soon as its request is APPROVED, REJECTED, STALE or EXPIRED, and the graph resumes with `Command(resume=decision)`. Approved plans are committed through `commit_approved_plan`; any other outcome is recorded without changing operations. |
| investigate_infeasibility | Shortfalls, blocked commitments and the best verified partial plan. If that plan serves more meals than doing nothing, it still goes to a human (`request_approval`, flagged as escalated). Otherwise the agent escalates. |
| escalate_to_operator | Final state `escalated`, with reasons and the proposal run id. |
| record_outcome | Final state `completed`. |

When the agent continues autonomously, requests approval, escalates, or stops:
- It continues autonomously when nothing affected is at risk; it records the outcome and changes nothing.
- It requests approval when a verified plan meets every commitment.
- It escalates when the best verified plan is partial, the event is invalid, or no candidate verifies within the retry budget.
- It never commits without an approval. `commit_approved_plan` is reachable only through the interrupt, and the database re-verifies the approval.

Infinite loops are prevented by the retry budget and by `recursion_limit = 40`. Transient gateway errors (5xx, 429, transport) are retried per node: at most 3 attempts, with exponential backoff.

## State and tools

`AgentState` is a `TypedDict` of JSON-serialisable values only (event, classification, impact, assessment, strategy, optimization summary, comparison, report, outcome, node trail). The graph reaches the outside world only through `AgentTools`: `load_event`, `snapshot`, `optimize`, `record_step` and `commit_plan`. Tests substitute their own implementations.

## Durability

| Mechanism | Where |
|---|---|
| Checkpoints after every node (`durability="sync"`) | `SupabaseCheckpointSaver`: `agent_checkpoints` and `agent_checkpoint_writes`, written through `put_checkpoint` / `put_checkpoint_writes` RPCs. Immutable and idempotent. Read with REST selects. |
| One execution per event | `agent_executions.event_id` unique; `thread_id = event:<id>` |
| Leases | `claim_next_execution` uses `FOR UPDATE SKIP LOCKED` and reclaims running executions whose lease expired. |
| Fencing | Every claim increments `attempt`. Step, heartbeat and finish RPCs require `(worker, attempt)` to still hold the lease, so a superseded worker is refused (`LeaseLost`). |
| Heartbeat | A thread renews the lease every lease/3 seconds and refreshes a Sprites Tasks API hold (`PUT /v1/tasks/cornucopia-agent` on `/.sprite/api.sock`), so the Sprite does not pause mid-run. |
| Idempotent side effects | Optimization runs carry an idempotency key, so a node re-run after a crash returns the already-stored run. The operational fact was applied once at ingest. |
| History | `agent_execution_steps` (append-only): claimed, resumed, completed, failed, retry, interrupted per node. |

What is persisted per execution: workflow thread id, execution id, current node, the full structured state (checkpoint), checkpoint versions, last completed node, retry count, attempt, and the event correlation id.

### Recovery after a restart

1. The worker process dies; its lease stops being renewed.
2. After at most `lease_seconds` (60 s), `claim_next_execution` hands the execution to any worker with `attempt + 1` and records a `resumed` step.
3. The worker finds an existing checkpoint for the thread and calls `graph.invoke(None, config)`. LangGraph continues from the last completed node, so finished nodes are not re-run.

`tests/test_agent.py::test_crash_mid_graph_resumes_from_checkpoint_without_duplicates` kills a worker after the optimizer has persisted a run but before the checkpoint. The next worker resumes, the node re-runs, and the idempotency key returns the same run: one optimization run, and `receive_event` completed once.
