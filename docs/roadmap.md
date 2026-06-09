# Engineering Platform Roadmap

## Phase 1 — Foundation
- [x] Core event bus and orchestration
- [x] OpenSCAD generation and STL compilation
- [x] Basic evaluation pipeline
- [x] Redis-backed improvement loop

## Phase 2 — CAD Drawings & Graph Compilation
- [x] PDF/PNG drawing ingestion (vision pipeline)
- [x] MachineGraph compilation from YAML
- [x] Graph decompilation back to YAML
- [x] Process simulation engine (steady-state)

## Phase 3 — Domain Knowledge & Hemp Evaluation
- [x] Hemp-specific performance evaluation
- [x] Fibre recovery, quality, throughput, wear models
- [x] Hemp process conditions modeling

## Phase 4 — Genetic Optimisation & Design Memory
- [x] Mutation engine (parameter perturbation, signal-guided)
- [x] Promotion/champion tracking
- [x] DesignMemoryStore (NDJSON append-only persistence)
- [x] Knowledge query and lesson retrieval

## Phase 5 — Autonomous Engineer Director
- [x] EngineerDirector pipeline orchestrator
- [x] Director REST API (run, status, result)
- [x] Multi-Agent Swarm (parallel design exploration)
- [x] Background job execution with status polling

## Phase 6 — Real-Time Telemetry
- [x] Telemetry session management (create, ingest, close)
- [x] Deviation detection (actual vs. predicted comparison)
- [x] Feedback trigger generation
- [x] Telemetry REST API (session, ingest, analyze, deviations, feedback)
- [x] Socket.IO real-time event broadcasting
- [x] Event-driven telemetry lifecycle (ingested, session_created, etc.)

## Phase 7 — Hardware Feedback Loop
- [x] TelemetryIngestor wired to DigitalTwin for predicted values
- [x] DeviationAnalyzer persists deviations in KnowledgeStore
- [x] FeedbackTrigger fires ImprovementController and persists triggers
- [x] ImprovementController.run_improvement_cycle() method
- [x] Full loop REST endpoint: POST /api/telemetry/feedback-loop/{session_id}
- [x] Full pipeline integration test
- [x] Backward compatible — all existing optional parameters preserved

---

**Original roadmap complete — v1.4.0 marks the end of the first-generation platform.**
**See ROADMAP_V2.md for the second-generation roadmap (Phases 8+).**
