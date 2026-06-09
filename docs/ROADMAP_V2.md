# Engineering Platform Roadmap V2 — Second Generation

**Starting point**: v1.4.0 — Original roadmap complete, closed-loop autonomous engineering achieved.

**Version scheme**: v1.5.x+ for second-generation phases, v2.0.0 for production platform.

---

## Phase 8 — Engineering Experiment Laboratory (Current — v1.5.0)

**Goal**: Automatically explore thousands of design permutations and generate engineering research reports.

**Why**: All the physics, manufacturing, and digital twin modules exist. Phase 8 makes them work together to answer "what if?" questions at scale.

- [x] ExperimentDefinition model (parameter ranges, constraints, objectives)
- [x] Design generator (Latin Hypercube / Sobol / Grid / Random sampling)
- [x] Flat-to-nested config mapping (bridges optimizer params to Director pipeline)
- [x] ExperimentRunner: generate N variants → evaluate all objectives → Pareto rank
- [x] Pareto front builder (dominance-based ranking)
- [x] Research report generator (HTML + text summary, champion, statistics)
- [x] REST API: POST define, POST run, GET status, GET result
- [x] Background job execution with status polling
- [x] 14 integration tests

---

## Phase 9 — Multi-Objective Evolution

**Goal**: Replace single-score optimization with simultaneous Pareto optimization across fibre recovery, quality, power, cost, weight, maintenance, and reliability.

**Why**: Trading off recovery vs. cost vs. reliability is the real engineering decision.

- [ ] Wire NSGA-II optimizer as primary improvement controller (replaces single-score mutation)
- [ ] EngineerDirector supports multi-objective goals
- [ ] Champion selection uses Pareto rank + knee analysis, not composite score alone
- [ ] Interactive trade-off visualization data

---

## Phase 10 — Autonomous Engineering Department

**Goal**: Multiple specialized agents negotiate design decisions as an engineering committee.

**Why**: Real engineering involves trade-offs between disciplines — the system should deliberate, not just optimize.

- [ ] Agent negotiation protocol (Designer proposes, Physics/Manufacturing/Cost vote)
- [ ] Mediation strategies: majority, weighted, veto-based
- [ ] Design iteration with agent feedback loop
- [ ] Archived negotiation transcripts for audit

---

## Phase 11 — Factory Intelligence

**Goal**: Optimize complete processing facilities, not just individual machines.

**Why**: A decorticator that works in isolation may bottleneck the plant.

- [ ] Multi-machine process graph (receiving → decorticator → cleaner → dryer → baler → storage)
- [ ] Factory-level mass/energy balance
- [ ] Bottleneck detection and mitigation
- [ ] Factory-wide Pareto optimization
- [ ] Factory layout and material flow analysis

---

## Phase 12 — Economic Engineering

**Goal**: Every design outputs capital cost, operating cost, maintenance cost, energy cost, 10-year ownership cost, and cost per kg of output.

**Why**: Engineering decisions are ultimately economic decisions.

- [ ] Capital cost model (materials, fabrication, assembly, transport, installation)
- [ ] Operating cost model (labour, energy, consumables)
- [ ] Maintenance cost model (wear parts, scheduled service, downtime)
- [ ] Life-cycle cost aggregation
- [ ] Cost per kg / cost per hour output metrics

---

## Phase 13 — Knowledge Reasoning

**Goal**: Move from knowledge storage to knowledge-based design decisions.

**Why**: The KnowledgeStore has historical design data — the system should learn from it.

- [ ] Historical pattern mining (which parameter changes improved which objectives)
- [ ] Rule extraction from champion lineage
- [ ] Design recommendation engine ("this geometry tends to improve recovery by 8%")
- [ ] Confidence-scored suggestions

---

## Phase 14 — Autonomous Research Agent

**Goal**: Ingest patents, engineering papers, technical manuals, and historical drawings into the knowledge graph.

**Why**: External engineering knowledge is the largest untapped resource.

- [ ] Document ingestion pipeline (PDF, patent XML, plaintext)
- [ ] Engineering entity extraction (parameters, materials, geometries, methods)
- [ ] Knowledge graph integration
- [ ] Cross-reference with experimental results

---

## Phase 15 — Autonomous Manufacturing & Deployment

**Goal**: Close the loop from digital design to physical machine and back.

**Why**: The ultimate feedback is a real machine running in the field.

- [ ] Manufacturing output (cut lists, weld maps, CNC programs, assembly instructions)
- [ ] Quality assurance integration (CMM inspection points, weld inspection)
- [ ] Commissioning and field telemetry
- [ ] Full self-improving ecosystem: Live Telemetry → Digital Twin → Knowledge → Redesign → Manufacture → Deploy
