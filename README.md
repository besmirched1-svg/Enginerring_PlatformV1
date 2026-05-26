# OpenSCAD Autonomous Engineering Intelligence Platform

This platform implements an autonomous, self-improving engineering loop capable of designing mechanical systems, evaluating structural/material performance, and safely iterating configurations over time.

## 🧬 System Architecture

```
User Prompt → AI Planner → Engineering Orchestrator
                                 ↓
   [Redis Queue] ← Improvement Loop ← Evaluation Engine
```

### ⚙️ Core Subsystems
1. **Mutation Engine (`app/core/mutation.py`)**: Pure function mapping mechanical issues into isolated configuration modifications with hard boundary limits.
2. **Promotion Engine (`app/core/promotion.py`)**: Evaluates challenger metrics against active champions via closed-form strict margins: `max(champion * 1.10, champion + 0.05)`.
3. **Chain Tracker (`app/core/improvement_chain.py`)**: Enforces an absolute execution ceiling (`max_attempts=3`) natively inside Redis transaction states.
4. **Revision Control (`app/core/revisions.py`)**: Manages backward-compatible historical manifest artifacts and structural optimization lineages.
5. **Background Controller (`app/core/improvement_controller.py`)**: Asynchronous daemon process interacting with pub/sub event channels to coordinate evaluation cycles.

## 🚨 Incident Response & Safety Controls

### 1. Global Kill Switch
To disable autonomous iterative loops across distributed containers completely, set the following environment parameter:
```bash
IMPROVEMENT_LOOP_ENABLED=false
```

### 2. Manual Operator Abort
To instantly cease an active multi-generation optimization track via network command structures, dispatch an emergency override query to the FastAPI API gateway:
```http
POST /improve/abort/{chain_id}?reason=Manual+intervention
```

### 3. State Status Monitoring
To monitor historical generation trends, composite champion ratings, and active mutation efforts:
```http
GET /improve/status/{machine_name}
```
