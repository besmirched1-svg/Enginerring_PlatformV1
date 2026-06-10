# User Guide

This guide is for **operators, engineers, and designers** who want
to use the platform to design, simulate, and evaluate industrial
machines. It assumes the platform is already running (see
[README.md](../README.md) for installation).

> **Audience.** You design or evaluate machines. You want to know:
> "What can I ask the platform to do? How do I read the results?
> What do the scores mean?"

---

## 1. The core loop

Every interaction with the platform follows the same shape:

```
   config  →  SCAD  →  STL  →  PNG  →  BOM  →  Evaluation
                ↓
        revision directory
                ↓
        promotion decision
```

A *config* is a JSON dict describing the machine's geometry
(wall thickness, frame dimensions, roller diameter, etc.). The
platform runs the config through the chain, archives every
artifact under a content-addressed revision directory, and
emits an event on the event bus for downstream subscribers.

A new revision is promoted to **champion** if its composite
score exceeds the previous champion by the configured margin
(`max(champion * 1.10, champion + 0.05)` — see
`app/core/promotion.py`).

---

## 2. The dashboard

Open `http://127.0.0.1:8000/` in a browser. You'll see:

- A list of machines with their current champion
- The evolutionary lineage of each machine
- Real-time build events over WebSocket
- A button to register a new candidate

The dashboard is read-only by default; new candidates are
submitted through the API (see §4 below).

---

## 3. The platform's vocabulary

| Term | Meaning |
|------|---------|
| **Machine** | A named design (e.g. `hemp_decorticator_v1`). Has a champion revision. |
| **Revision** | A specific build of a machine, identified by `rev_{8 hex chars}`. |
| **Chain** | A sequence of revisions proposed as improvements to a base. |
| **Champion** | The current best revision for a machine. Promoted when a new revision outscores it. |
| **Composite** | A 0.0–1.0 score combining structural validity, manufacturability, material efficiency, and performance heuristics. |
| **Plant** | A factory graph: a list of `ProcessUnit`s with material streams between them. |
| **Director** | The closed-loop controller. Per-machine: `app/director/`. Per-plant: `app/factory_director/`. |
| **DynamicConstraint** | A piece of feedback the director emits; the next run reads it as a bound on the search. |

---

## 4. Generate a machine

### The minimum config

Every config needs a frame:

```json
{
  "frame": {"length": 1500, "width": 800, "height": 1000, "profile": 50}
}
```

A frame alone produces a valid revision. The other fields tune
the design.

### A full config

```json
{
  "wall_thickness": 4.0,
  "clearance": 0.6,
  "roller_radius": 35.0,
  "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
  "roller": {"diameter": 200, "width": 500, "shaft": 50},
  "hopper": {"top_width": 400, "bottom_width": 120, "height": 300, "wall": 4},
  "spindle": {"shaft_length": 4000, "shaft_od": 260, "flight_od": 600,
              "flight_thickness": 25, "flight_turns": 10},
  "drum":   {"flat_pattern_width": 4000, "flat_pattern_length": 4712,
             "wall_thickness": 8, "drum_id": 1500,
             "perforation_diameter": 4, "perforation_pitch_layout": 12,
             "perforation_zone_fraction": 0.60, "lifter_count": 12,
             "misc_assembly_kg": 340},
  "compression_rollers": {"diameter": 200, "width": 4000}
}
```

Anything you omit gets the platform default. The defaults are
tuned for the HTDS-P2 baseline but a real design should specify
the parts that matter.

### Submit

```bash
curl -X POST http://127.0.0.1:8000/api/improve/register \
  -H "Content-Type: application/json" \
  -d @my_config.json
```

Response (truncated):

```json
{
  "status": "processed",
  "details": {
    "revision_id": "rev_8a3f2b1c",
    "directory": "outputs/revisions/my_machine/rev_8a3f2b1c",
    "score": 0.84,
    "promoted": true,
    "evaluation": {
      "composite": 0.84,
      "needs_improvement": false,
      "metrics": {
        "structural_validity": {"score": 0.91, "issues": []},
        "manufacturability":  {"score": 0.88, "issues": []},
        "material_efficiency": {"score": 0.74, "issues": []},
        "performance_heuristics": {"score": 0.83, "issues": []}
      }
    }
  }
}
```

`promoted: true` means this revision is now the champion. To
trigger another improvement attempt with a slightly different
config, submit again; the platform will chain them.

### Download the STL

```bash
curl -o rev_8a3f2b1c.stl http://127.0.0.1:8000/api/improve/download/my_machine/rev_8a3f2b1c
```

The downloaded file is a binary STL mesh.

---

## 5. Read the artifacts

A revision directory looks like:

```
outputs/revisions/my_machine/rev_8a3f2b1c/
├── manifest.json
├── model.scad
├── output.stl
├── preview.png
├── bom.csv
└── evaluation.json
```

### `manifest.json`

Chain-of-custody record. Records the config, the parent revision
(if this is a chain improvement), the chain ID, and the
promotion status.

### `model.scad`

The OpenSCAD source. Open it in OpenSCAD to inspect or edit.
The platform's templates are parametric; the same file is
human-editable.

### `output.stl`

The rendered mesh. This is the file you would send to a CNC,
slicer, or 3D printer. Binary STL format.

### `preview.png`

An OpenGL snapshot of the rendered model. Useful for design
review without opening OpenSCAD.

### `bom.csv`

The Bill of Materials. Columns:

| Column | Meaning |
|--------|---------|
| `Component Name` | `Frame`, `Roller`, `Spindle`, `Drum`, `Hopper`, `CompressionRoller` |
| `Material Spec` | `en24t`, `mild_steel`, `stainless_304`, `hardox_500`, `aluminum_6061` |
| `Est. Weight (kg)` | Per-component mass from the parametric volume formula |
| `Est. Cost (AUD)` | Material cost at the configured rate |

The file ends with a `TOTAL INDUSTRIAL ASSY METRICS` row giving
the total weight and cost.

### `evaluation.json`

The composite scoring report:

```json
{
  "composite": 0.84,
  "needs_improvement": false,
  "metrics": {
    "structural_validity": {"score": 0.91, "issues": []},
    "manufacturability":  {"score": 0.88, "issues": []},
    "material_efficiency": {"score": 0.74, "issues": []},
    "performance_heuristics": {"score": 0.83, "issues": []}
  }
}
```

Each sub-score is 0.0–1.0. `composite` is a weighted average
(stability × 0.4 + material × 0.4 + performance × 0.2 by default
in `_calculate_live_metrics`).

---

## 6. Interpret the scores

| Score | Meaning |
|-------|---------|
| 0.0–0.3 | Likely unbuildable. Check the `issues` array for which sub-dimension failed. |
| 0.3–0.6 | Buildable but not great. Look at material_efficiency — high wall thickness on a small roller wastes material. |
| 0.6–0.8 | Good design. Promotion likely if the previous champion was worse. |
| 0.8–1.0 | Strong design. Likely to be the new champion. |

**A high score does not mean a manufacturable design.** The
evaluator is a heuristic; it does not do FEA. Use it for
relative comparison, not absolute validation.

---

## 7. Run a plant simulation

A *plant* is a graph of process units connected by material
streams. The factory layer runs mass balance, energy balance,
and bottleneck analysis over the graph.

```bash
curl -X POST http://127.0.0.1:8000/api/factory/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "feed_rate_kg_hr": 1500,
    "units": [
      {"unit_id": "mill_a", "unit_type": "milling",
       "max_capacity_kg_hr": 800, "efficiency": 0.95},
      {"unit_id": "mill_b", "unit_type": "milling",
       "max_capacity_kg_hr": 700, "efficiency": 0.90}
    ],
    "streams": [
      {"source": "feed", "target": "mill_a", "mass_flow_kg_hr": 1500},
      {"source": "mill_a", "target": "mill_b", "mass_flow_kg_hr": 1500},
      {"source": "mill_b", "target": "product", "mass_flow_kg_hr": 1500}
    ]
  }'
```

The response includes:

- `mass_balance.product_rate_kg_hr` — what actually comes out
- `mass_balance.system_yield` — yield (0.0–1.0)
- `energy_balance.total_power_kw`
- `bottleneck.bottleneck_unit_id` — the limiting unit
- `bottleneck.theoretical_max_kg_hr` — the line's max rate
- `bottleneck.takt_time_sec` — seconds per unit at full rate
- `bottleneck.oee` — overall equipment effectiveness

---

## 8. Run predictive maintenance

Predict a bearing or shaft's remaining life:

```bash
curl -X POST http://127.0.0.1:8000/api/factory/predict-maintenance \
  -H "Content-Type: application/json" \
  -d '{
    "planning_horizon_hours": 8760,
    "bearings": [
      {
        "machine_id": "mill_a", "component": "drive_end",
        "bore_diameter": 50, "outer_diameter": 90, "width": 20,
        "dynamic_load_rating": 35000, "static_load_rating": 25000,
        "limiting_speed": 7500,
        "radial_load": 5000, "axial_load": 1000,
        "speed": 1500, "elapsed_operating_hours": 600
      }
    ],
    "shafts": []
  }'
```

The response includes a list of maintenance actions sorted by
`due_in_hours`. Each action has a `severity` field
(`low` / `medium` / `high` / `critical`).

The severity bands are:

| Severity | Bearing consumption | Shaft damage |
|----------|--------------------|--------------|
| low | < 60% | < 0.40 |
| medium | 60–80% | 0.40–0.80 |
| high | 80–95% | 0.80–0.95 |
| critical | ≥ 95% | ≥ 0.95 |

---

## 9. Run the factory director

The factory director ties simulation + PM + bottleneck relief
into a single plant-level decision. Use it when you want the
platform to propose a relief action for a bottleneck.

```bash
curl -X POST http://127.0.0.1:8000/api/factory/director/run \
  -H "Content-Type: application/json" \
  -d '{
    "name": "hemp_line_1",
    "target_throughput_kg_hr": 1500,
    "feed_rate_kg_hr": 1500,
    "planning_horizon_hours": 8760,
    "prefer_maintenance": true,
    "bearings": [...],
    "shafts": [...]
  }'
```

The response includes:

- `bottleneck_reliefs` — list of proposed actions
- `dynamic_constraints` — the same reliefs encoded as
  `DynamicConstraint`s the per-machine director picks up

The policy table:

| If | Then propose |
|----|--------------|
| `prefer_maintenance=true` AND a maintenance action exists for the bottleneck unit | `schedule_maintenance` |
| Utilization ≥ 95% | `add_parallel_unit` |
| Otherwise | `raise_capacity` (25% bump) |

---

## 10. Common workflows

### "I want to compare two configs"

1. Submit config A. Note the `revision_id`.
2. Submit config B. Note the `revision_id`.
3. Compare `evaluation.json` from each. The one with the higher
   composite wins; the platform will already have promoted it.

### "I want to find the optimal wall thickness"

The swarm endpoint runs a population-based optimizer. The
default is 5 generations × 5 candidates. You can change this:

```bash
curl -X POST http://127.0.0.1:8000/api/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Optimize wall_thickness and roller_radius for hemp_decorticator_v1",
    "max_generations": 10,
    "population_size": 8
  }'
```

The endpoint returns a `session_id` immediately. The swarm
runs in the background; watch the dashboard for new revisions.

### "I want to deploy a new build to production"

The platform does not deploy to physical hardware — it produces
the artifacts. You take the STL (`/api/improve/download/{m}/{rev}`)
and feed it to your slicer / CNC / 3D printer of choice. The
BOM (`outputs/revisions/{m}/{rev}/bom.csv`) is procurement-ready
for the parts the platform models.

---

## 11. Troubleshooting

### "My revision has no output.stl"

Check `/api/health`. If `openscad` check fails, the renderer
falls back to a 12-byte "FALLBACK STL" placeholder. Install
OpenSCAD or set `OPENSCAD_BIN`.

### "My PNG is missing"

Same as above — PNG rendering needs OpenGL. On a headless
server (Docker, CI), the platform uses Xvfb. On your dev
machine, OpenSCAD needs an X server or `xvfb-run`.

### "My evaluation.json is missing"

This is a v1.0+ feature. If you're on a pre-16.5 build, the
evaluation was only in memory. Upgrade.

### "The director says no relief"

The director only proposes a relief when there's a bottleneck.
If your plant runs below 80% utilization, the platform has
nothing to fix.

### "Tests are failing"

Run `python -m pytest tests/ -q`. 932 should pass. The
exception is pre-existing skips. If you see a real failure,
file a bug with the failing test name.

---

## 12. Where to go next

- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — pipeline internals,
  conventions, extension points.
- [ARCHITECTURE.md](ARCHITECTURE.md) — layer rules, dependency
  graph, factory/director boundary.
- [releases/RELEASE_NOTES_v1.0.md](releases/RELEASE_NOTES_v1.0.md) —
  what is in this release and what is not.
- [releases/DOCKER_PARITY.md](releases/DOCKER_PARITY.md) — Docker
  vs Local behavior matrix.
