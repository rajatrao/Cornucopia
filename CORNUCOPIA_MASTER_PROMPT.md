CORNUCOPIA
Master Engineering Implementation Prompt
Fly.io Hacksgiving 2026

You are acting as a Principal Software Architect, Senior Python Engineer, Autonomous Agent Engineer, Optimization Engineer, Full-Stack Engineer, Product Designer, Database Architect, and Infrastructure Engineer.

Your mission is to design, implement, test, and deploy CORNUCOPIA: a persistent autonomous resource compiler running on a real Fly.io Sprite.

The application must use the official Fly.io Sprites Supabase Database Connector as its external persistence integration.

The entire human interaction experience must take place through a dedicated web application.

Do not build Slack integration, GitHub operational workflows, or external messaging interfaces.

Build a functional, demonstrable autonomous system that responds to unpredictable resource changes by analyzing operational consequences, reconstructing plans, optimizing replacements, and requesting human approval before consequential changes.

The system must work without paid LLM inference.

Implementation must follow the phases below in order.

Do not skip phases. Do not claim a phase is complete until its acceptance criteria have been verified.

1. PRODUCT IDENTITY

Product: CORNUCOPIA

Category: Autonomous Resource Compiler

Tagline:

"When resources change, the feast goes on."

Description:

CORNUCOPIA transforms unpredictable donations, ingredient inventory, preparation capacity, dietary restrictions, and delivery commitments into executable operational plans.

When operational reality changes, its autonomous agent identifies affected dependencies, evaluates consequences, computes replacement plans, and requests approval before committing consequential changes.

Its signature capability is:

REALITY RECOMPILATION.

Primary demonstration environment:

A Thanksgiving community food-rescue operation.

The underlying architecture should be extensible to other resource-allocation domains.

The product must demonstrate that persistent autonomous agents can manage unpredictable real-world operations.

2. NON-NEGOTIABLE ARCHITECTURAL PRINCIPLES
2.1 Fly.io Sprite owns the agent

The actual autonomous runtime must execute inside a Fly.io Sprite.

The Sprite must run:

FastAPI backend.
LangGraph orchestration.
Deterministic decision engine.
OR-Tools CP-SAT optimizer.
NetworkX dependency analysis.
Agent execution supervisor.
Recovery workflow.
Approval processing.
Supabase Connector adapter.

The Sprite must not be a reverse proxy for an agent hosted elsewhere.

The Next.js frontend is a separate client application.

The autonomous agent must operate independently of the frontend.

2.2 Supabase is the persistence provider

Use the official Fly.io Sprites Supabase Database Connector.

The Sprite must communicate with Supabase through the documented Connector gateway and supported REST/RPC operations.

Do not assume a direct PostgreSQL connection is provided by the Connector.

Do not expose Connector credentials to the browser.

Do not connect the browser directly to Supabase using privileged service credentials.

All operational mutations must pass through the authenticated FastAPI backend.

2.3 No mandatory paid LLM

All mandatory decision-making must be deterministic.

Do not integrate paid OpenAI, Anthropic, OpenRouter, or other inference providers into the mandatory execution path.

Do not pretend an LLM is being used.

Use:

Pydantic schemas.
Explicit event types.
Deterministic parsers.
Decision policies.
NetworkX.
OR-Tools.
LangGraph.

Optional LLM integration may be considered later, but must be disabled by default.

2.4 UI-first interaction

All human operational interaction takes place through the CORNUCOPIA web application.

The UI must support:

Creating donations.
Managing inventory.
Reporting operational changes.
Creating commitments.
Managing recipes.
Viewing recovery execution.
Reviewing proposed plans.
Approving or rejecting plans.
Running simulations.
Viewing audit history.

No Slack or GitHub interaction is required.

2.5 Safety and correctness

The system must distinguish:

A proposed plan.
A mathematically feasible plan.
An approved plan.
A committed operational plan.

Never treat optimization success as authorization.

Never silently change approved operational commitments.

All consequential changes require an authorized human approval.

3. TECHNOLOGY STACK
Backend
Python 3.12+
FastAPI
Pydantic
SQLAlchemy for domain and data modeling where appropriate
Alembic for migration generation and migration tracking
Explicit repository interfaces
REST/RPC Supabase adapter
Agent
LangGraph
Custom deterministic decision engine
Explicit tool interfaces
Durable Supabase-backed checkpoint implementation
Idempotent workflow execution
Bounded retries
Structured execution history
Optimization
Google OR-Tools CP-SAT
NetworkX
Explicit ingredient substitution rules
Unit conversion engine
Recipe yield calculations
Database
Supabase PostgreSQL
Supabase REST API
Supabase RPC
Append-only operational event journal
Transactional RPC functions
Durable agent checkpoints
Transactional outbox
Frontend
Next.js
TypeScript
Tailwind CSS
React Flow
Recharts or equivalent visualization library
Accessible component system
Responsive design
Deployment
Fly.io Sprite for actual autonomous runtime
Fly.io Sprites Supabase Database Connector
Separate Next.js hosting
Managed Supabase project
Testing
Pytest
Playwright
Ruff
MyPy where practical
TypeScript strict checking
4. SYSTEM ARCHITECTURE

Implement the following logical architecture:

USER | v NEXT.JS OPERATIONS DASHBOARD | | Authenticated HTTP requests v FLY.IO SPRITE | +-- FastAPI | +-- Agent Supervisor | +-- LangGraph Workflow | +-- Deterministic Decision Engine | +-- NetworkX Dependency Engine | +-- OR-Tools CP-SAT Optimizer | +-- Approval Engine | +-- Audit Engine | +-- Supabase Repository Adapter | v FLY CONNECTOR GATEWAY | v SUPABASE DATABASE

The Sprite is the authoritative execution environment.

The frontend must never independently make operational decisions.

The frontend displays backend-authoritative state.

All operational mutations must be validated by the backend.

5. DATABASE AND DOMAIN MODEL

Implement UUID identifiers and explicit timestamps.

All timestamps must be stored in UTC.

All quantities must have explicit units.

Implement relational integrity, appropriate constraints, and indexes.

Core entities:

Organization
Donor
Donation
Ingredient
InventoryLot
Recipe
RecipeIngredient
IngredientSubstitution
Meal
MealBatch
Commitment
Volunteer
PreparationTeam
Delivery
OperationalEvent
Dependency
OptimizationRun
OptimizationResult
PlanVersion
PlanChange
ApprovalRequest
ApprovalDecision
AgentExecution
AgentCheckpoint
SimulationScenario
OutboxMessage
AuditRecord

The primary demonstration can use one organization.

Do not overengineer multi-tenant functionality during the MVP.

Implement append-only event history.

Every important state transition must be auditable.

6. PHASED IMPLEMENTATION ROLLOUT

The implementation must proceed through nine phases.

Each phase must produce working code, tests, and a verification report.

Do not begin the next phase until the current phase passes its acceptance criteria.

PHASE 0 — REPOSITORY AND PLATFORM DISCOVERY

Objective:

Establish a technically verified implementation foundation.

Tasks:

Inspect the existing repository.
Determine whether the project already contains code.
Preserve working implementation.
Inspect current Fly.io Sprites documentation.
Inspect the official Sprites Supabase Connector documentation.
Verify actual Connector authentication.
Verify supported REST and RPC operations.
Verify credential injection and access restrictions.
Verify Sprite persistence and lifecycle behavior.
Verify networking and deployment procedures.

Do not invent:

CLI commands.
Connector environment variables.
Authentication mechanisms.
API endpoints.
Deployment capabilities.

Produce:

Architecture document.
Repository structure.
Dependency inventory.
Deployment assumptions.
Connector integration notes.
Risk register.
Phase implementation plan.

Acceptance criteria:

Current platform capabilities documented.
Connector requirements verified.
Architecture approved.
No fabricated infrastructure assumptions.
PHASE 1 — PROJECT FOUNDATION AND SUPABASE CONNECTOR

Objective:

Create the actual application foundation and establish secure persistent database access.

Tasks:

Initialize the backend.
Initialize the frontend.
Create shared API contracts.
Implement FastAPI health endpoints.
Implement configuration management.
Create Supabase Connector adapter.
Implement repository interfaces.
Implement database connectivity checks.
Implement migration generation.
Create initial database schema.
Establish frontend-to-backend communication.

IMPORTANT CONNECTOR REQUIREMENTS:

Use only the official documented Connector access pattern.

Never assume the Connector provides a direct PostgreSQL connection.

Use the documented credential-injecting gateway.

Never expose privileged Connector credentials in frontend code.

Implement the Supabase adapter behind an interface so that the application can be tested with a local mock.

Use a dedicated database schema or carefully namespaced tables where supported.

If Supabase REST cannot perform a required transactional operation, implement a PostgreSQL RPC function and invoke it through the documented Connector.

Acceptance criteria:

Backend starts.
Frontend starts.
Sprite can access Supabase through the Connector.
A test record can be inserted.
A test record can be retrieved.
Database migrations are reproducible.
No privileged secret reaches the browser.
PHASE 2 — DOMAIN MODEL AND OPERATIONAL EVENT ENGINE

Objective:

Create the operational foundation.

Implement:

Donations.
Ingredients.
Inventory lots.
Recipes.
Recipe ingredients.
Ingredient substitutions.
Meals.
Meal batches.
Commitments.
Volunteers.
Preparation capacity.
Deliveries.

Implement quantity units and conversion.

Examples:

Pounds.
Ounces.
Kilograms.
Grams.
Units.
Portions.

Conversions must be explicit and safe.

Do not assume mass and volume are interchangeable without ingredient-specific density information.

Implement operational events:

DONATION_CREATED
DONATION_CANCELLED
INVENTORY_ADJUSTED
INGREDIENT_EXPIRED
VOLUNTEER_UNAVAILABLE
DELIVERY_DELAYED
DELIVERY_CANCELLED
COMMITMENT_CHANGED
PREPARATION_CAPACITY_CHANGED

Every event must have:

UUID.
Idempotency key.
Event type.
Structured payload.
Creation timestamp.
Actor.
Processing status.
Correlation ID.

Implement immutable event journaling.

Acceptance criteria:

CRUD operations work through the UI.
Event creation works.
Event history is persistent.
Duplicate event submissions do not create duplicate effects.
Inventory calculations are validated.
Unit conversions pass tests.
PHASE 3 — DETERMINISTIC RESOURCE COMPILER

Objective:

Implement the actual resource planning engine.

Create:

Recipe requirement calculator.
Ingredient availability calculator.
Inventory allocation engine.
Preparation capacity calculator.
Delivery capacity calculator.
Ingredient substitution engine.
Dependency graph builder.
Plan feasibility validator.

Implement dependency relationships.

Examples:

Donation -> InventoryLot -> Ingredient -> Recipe -> MealBatch -> Commitment -> Delivery

NetworkX must identify affected downstream dependencies when an upstream resource changes.

Implement a baseline planning engine.

Implement deterministic plan comparison.

Acceptance criteria:

Initial operational plan can be generated.
Resource shortages are identified.
Affected dependencies are identified.
Infeasible commitments are detected.
Ingredient substitutions are validated.
All calculations have reproducible tests.
PHASE 4 — OR-TOOLS OPTIMIZATION ENGINE

Objective:

Implement mathematically valid operational recovery.

Use OR-Tools CP-SAT.

The optimizer must support:

Ingredient availability constraints.
Recipe requirements.
Dietary restrictions.
Preparation capacity.
Volunteer availability.
Meal quantity requirements.
Delivery capacity.
Ingredient substitution rules.
Existing commitment preservation.

Optimization priorities:

Never violate hard safety or dietary constraints.
Never exceed inventory availability.
Never exceed preparation capacity.
Preserve existing commitments.
Minimize changes to approved plans.
Minimize food waste.
Minimize delivery disruption.

Separate hard constraints from soft objectives.

Use lexicographic optimization or carefully documented weighted objectives.

Implement:

Solver timeout.
Feasibility reporting.
Infeasibility diagnosis.
Optimization metrics.
Candidate plan generation.
Plan validation.

Never label an unverified result as feasible.

Acceptance criteria:

Solver produces verified feasible plans.
Solver identifies infeasible scenarios.
Constraint violations are explained.
Alternative plans can be compared.
Optimization is deterministic for fixed inputs and configuration.
Performance is measured on the demonstration dataset.
PHASE 5 — LANGGRAPH AUTONOMOUS AGENT

Objective:

Implement the autonomous operational recovery agent.

The graph must include:

receive_event validate_event classify_event update_operational_state analyze_dependencies assess_impact select_recovery_strategy generate_candidate_plan run_cpsat_optimizer validate_candidate compare_plan_versions generate_decision_report request_approval commit_approved_plan record_outcome investigate_infeasibility escalate_to_operator

Implement conditional routing.

Use bounded retries.

Prevent infinite loops.

Use structured state schemas.

Use explicit tool interfaces.

The agent must determine when to:

Continue autonomously.
Generate alternative plans.
Request human approval.
Escalate.
Stop due to infeasibility.

Implement durable execution persistence.

IMPORTANT:

The standard PostgreSQL LangGraph checkpointer must not be assumed to work through the Supabase REST Connector.

Implement a custom Supabase REST/RPC-backed checkpoint saver, or another verified durable checkpoint implementation using the Connector.

Persist:

Workflow thread ID.
Execution ID.
Current node.
Structured state.
Checkpoint version.
Last completed operation.
Retry count.
Event correlation ID.

Implement idempotent recovery.

A restarted worker must be able to inspect durable execution state and resume safely.

Acceptance criteria:

Agent processes events.
Agent generates recovery proposals.
Checkpoints survive process restart.
Duplicate execution does not duplicate operational changes.
Infeasible cases escalate.
Execution history is visible in the UI.
PHASE 6 — APPROVAL AND TRANSACTIONAL COMMIT ENGINE

Objective:

Create a trustworthy human approval system.

Implement:

ApprovalRequest.
ApprovalDecision.
PlanVersion.
PlanFingerprint.
ApprovalStatus.
AuthorizedOperator.

Approval lifecycle:

PENDING APPROVED REJECTED EXPIRED STALE COMMITTED

Each approval must be bound to:

Exact plan ID.
Exact plan version.
Plan fingerprint.
Requesting execution.
Authorized operator.
Creation timestamp.
Expiration timestamp.

Reject stale approvals.

Reject duplicate approvals.

Reject unauthorized approval attempts.

Require an explicit confirmation before committing consequential changes.

Implement database-side transactional RPC operations.

A successful commit must atomically:

Verify approval validity.
Verify the plan fingerprint.
Verify the current operational version.
Apply approved operational changes.
Record the approval decision.
Record the plan commit.
Write the audit event.
Create an outbox notification.

Never partially commit a plan.

Acceptance criteria:

Approval and rejection work.
Stale approvals fail.
Unauthorized operators cannot approve.
Concurrent approvals are handled safely.
Committed plans have complete audit history.
PHASE 7 — NEXT.JS OPERATIONS COMMAND CENTER

Objective:

Build a polished operational interface that makes the autonomous system understandable.

The UI must not resemble a generic chatbot or conventional CRUD dashboard.

Design identity:

CORNUCOPIA "When resources change, the feast goes on."

Use a modern operational command center.

Required screens:

A. Command Center

Display:

Active operation.
Meals committed.
Meals currently feasible.
Inventory health.
Resource shortages.
Agent runtime status.
Active recovery executions.
Pending approvals.
Recent operational events.
B. Resource Management

Display and manage:

Donations.
Ingredient inventory.
Inventory lots.
Recipes.
Substitution rules.
Volunteers.
Preparation teams.
Delivery capacity.
C. Operational Event Center

Allow operators to:

Report donation cancellations.
Add new donations.
Report expired ingredients.
Report volunteer unavailability.
Report delivery delays.
Change commitments.
Change operational capacity.

Use validated structured event forms.

Never invent missing event information.

D. Reality Recompilation

This is the signature experience.

Display:

Incoming operational event.
Impact analysis.
Affected dependency graph.
Original operational plan.
Proposed replacement plan.
Optimization objective results.
Constraint satisfaction.
Unresolved risks.
Agent execution timeline.

Use React Flow to visualize affected dependency relationships.

Highlight changed nodes and edges.

E. Approval Center

Display:

Pending recovery plans.
Plan versions.
Original versus replacement comparisons.
Changes to commitments.
Resource allocation changes.
Constraint validation.
Approve button.
Reject button.
Simulate button.

Approval must be explicit.

F. Execution History

Display:

Operational events.
Agent executions.
Workflow nodes.
Checkpoints.
Recovery attempts.
Decisions.
Approvals.
Plan commits.
G. Simulation Laboratory

Allow operators to run predefined operational scenarios without affecting committed production state.

Provide:

Donation cancellation.
Ingredient shortage.
Volunteer shortage.
Delivery disruption.
Multiple simultaneous failures.

Simulation results must be isolated from production records.

Acceptance criteria:

All screens functional.
API integration works.
Forms validate.
Approvals work end-to-end.
Visualizations reflect real backend state.
Responsive layout.
Playwright tests pass.
PHASE 8 — PERSISTENCE, RESILIENCE AND DEPLOYMENT

Objective:

Prove that the actual autonomous agent lives on the Fly.io Sprite and survives process interruptions.

Tasks:

Create the production Sprite.
Configure the Supabase Connector.
Configure required environment settings.
Deploy FastAPI.
Deploy or start the persistent worker.
Configure health monitoring.
Configure startup recovery.
Verify Supabase access.
Verify checkpoint persistence.
Verify API authentication.
Verify agent execution independently of the frontend.

Implement:

Agent heartbeat.
Durable execution claims.
Lease expiration.
Idempotent event processing.
Transactional outbox delivery.
Retry policies.
Structured logs.
Health checks.
Graceful shutdown.

Do not rely on in-memory state surviving Sprite suspension or process restart.

A restart must reconstruct work from durable records.

Use a deployment procedure supported by current official Sprite documentation.

Acceptance criteria:

Agent executes inside the Sprite.
Frontend can access the Sprite-hosted API.
Supabase Connector works in production.
Process restart does not lose execution history.
Interrupted workflows recover safely.
No duplicate operational commits.
Health checks work.
Deployed runtime is independently verifiable.
PHASE 9 — END-TO-END TESTING AND HACKATHON DEMONSTRATION

Objective:

Deliver a compelling, independently verifiable demonstration.

Primary scenario:

Thanksgiving operation with 500 meal commitments.

Initial resources:

180 lb rice.
120 lb potatoes.
100 lb carrots.
12 volunteers.
3 delivery routes.

Introduce an operational event:

"The rice donation has been cancelled. Remove 180 pounds from available inventory. All 500 meals remain committed."

The actual optimizer must determine whether 500 meals can still be produced.

Do not hardcode the answer.

Demonstrate:

Operator submits the event through the UI.
Event is journaled in Supabase.
Sprite agent receives and processes the event.
LangGraph executes the workflow.
NetworkX identifies affected dependencies.
OR-Tools computes a replacement or reports infeasibility.
UI displays the recovery analysis.
Operator reviews the replacement plan.
Operator approves or rejects.
The backend validates approval.
Database transaction commits the plan.
UI displays the updated operational state.
Agent is interrupted and restarted.
Agent reconstructs its execution state.
Audit history proves consistency.

Create a second scenario where the resources are insufficient and the optimizer must escalate instead of inventing a solution.

FINAL DEFINITION OF DONE

CORNUCOPIA is complete only when:

The real agent runs inside a Fly.io Sprite.
The official Supabase Sprites Connector is used.
The web UI is the sole required human operational interface.
No paid LLM is required.
Operational events are durable.
Dependency analysis works.
CP-SAT optimization works.
LangGraph orchestration works.
Approvals are versioned and secure.
Database commits are transactional.
Restart recovery works.
The complete scenario is reproducible.
Tests pass.
Deployment instructions are documented.
A judge can independently verify the system.
7. IMPLEMENTATION RULES FOR THE CODING AGENT

These rules apply to every phase.

Inspect existing files before changing them.
Never overwrite working code without understanding it.
Use modular architecture.
Keep domain logic separate from infrastructure.
Keep the optimization engine independent of LangGraph.
Keep the Supabase adapter behind repository interfaces.
Use typed request and response schemas.
Implement tests alongside functionality.
Run tests after every meaningful change.
Do not use fake data in production pathways.
Clearly label demonstration data and simulations.
Do not hardcode optimization outcomes.
Do not claim an integration works without testing it.
Do not invent undocumented Fly.io capabilities.
Never expose privileged credentials.
Never accept unvalidated browser input.
Never trust client-side approval state.
Never perform consequential operations without authorization.
Never advance a phase with failing acceptance tests.
Maintain a project implementation journal.

At the completion of each phase, produce:

Files created.
Files modified.
Architecture decisions.
Implemented functionality.
Tests executed.
Test results.
Known limitations.
Remaining risks.
Acceptance checklist.
Recommendation to proceed or stop.

If a required external integration is unavailable, stop and explain the blocker. Do not silently substitute a mock for the production integration.

8. REQUIRED PROJECT DOCUMENTATION

Maintain these files:

README.md ARCHITECTURE.md IMPLEMENTATION_PLAN.md DEPLOYMENT.md CONNECTOR_SETUP.md DATABASE_SCHEMA.md AGENT_WORKFLOW.md OPTIMIZATION_ENGINE.md SECURITY.md DEMO_SCRIPT.md TESTING.md CHANGELOG.md

Include exact setup and deployment commands verified against the actual platform.

9. EXECUTION INSTRUCTION

Begin with PHASE 0.

Do not attempt to implement all phases in one response.

First inspect the repository and current Fly.io documentation.

Then provide the Phase 0 discovery report and implementation plan.

Wait for explicit approval before starting Phase 1.

For subsequent phases, implement, test, report, and wait for approval before continuing.

The objective is not to generate the maximum amount of code.

The objective is to deliver a real, resilient, autonomous resource compiler that judges can operate, inspect, interrupt, restart, and verify.

Build CORNUCOPIA to demonstrate why persistent autonomous agents belong on Fly.io Sprites.
