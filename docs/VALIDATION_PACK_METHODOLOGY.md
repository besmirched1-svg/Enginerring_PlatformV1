# Validation Pack Baselining Methodology

This document describes the protocol for baselining
the score sidecars (`expected/<name>.score.txt`) in
the hemp decorticator validation pack
(`tests/fixtures/drawings/`). It is the maintainer's
guide for the per-fixture calibration required by
spec §5.1 + §12.

## The §5.1 rule

> The drawing-ingested run's composite score must
> clear the manually-authored reference run's
> composite score minus 0.10.

The minus 0.10 reflects the inherent uncertainty of
the heuristic OCR pipeline. The manual reference
config is exact (typed by hand from the same
fabrication drawing); the drawing-ingested config
is approximate (extracted by the OCR + assembly
detector + graph builder chain). A 0.10 margin
acknowledges that the heuristic path will never
beat the manual path at the same drawing, but it
must come close.

**Why the test enforces this:**

The validation pack's regression test
(`tests/test_hemp_decorticator_validation_pack.py`)
reads each `expected/<name>.score.txt` sidecar and
asserts the produced revision's `evaluation.json`
`composite` is `>=` the sidecar value. A code
change that drops the composite below the threshold
fails CI, regardless of whether the change "looks
correct." This is the regression-safety net.

## The baselining protocol

For each of the 6 subsystems (hopper, conveyor,
compression_rollers, drum, spindle, frame):

### Step 1 — Construct the manual reference YAML

The manual reference config is the canonical
fabrication spec for that subsystem. Use
`workspace/processing/example_machine.yaml` as a
template:

```yaml
machine:
  name: <subsystem_name>_v1
  <subsystem_key>:
    <parameters from the fabrication drawing>
```

For example, the manual hopper config:

```yaml
machine:
  name: hopper_v1
  hopper:
    top_width: 500
    bottom_width: 150
    height: 350
    wall: 4
    material: mild_steel
```

The config must match the dimensions embedded in
the synthetic fixture PDF
(`tests/fixtures/drawings/<name>_a3.pdf`). The
build script
(`tests/fixtures/build_synthetic_fixtures.py`)
is the source of truth for those dimensions.

### Step 2 — Run through the orchestrator

Submit the manual config via the
`/api/improve/register` endpoint (or the
orchestrator's CLI), with `auto_promote=False`
(per spec §17.2a — the manual reference run
must not change the champion lineage):

```python
orchestrator.run_machine_job(
    machine_name="<subsystem_name>",
    config=manual_config,
    auto_promote=False,
)
```

### Step 3 — Read the composite score

Open the produced revision's `evaluation.json`
and read the `composite` field:

```python
import json
with open(f"outputs/revisions/<name>/<rev_id>/evaluation.json") as f:
    eval_data = json.load(f)
composite = eval_data["composite"]
```

### Step 4 — Subtract 0.10

```python
sidecar_threshold = round(composite - 0.10, 4)
```

### Step 5 — Write the sidecar

Replace the `TBD` placeholder in
`tests/fixtures/drawings/expected/<name>_a3.score.txt`
with the threshold value:

```
0.58
```

A single float on the first line. The other lines
(comments for the maintainer) can stay or be
removed — the test only reads the first line.

## Re-baselining cadence

The sidecars are a **moving baseline** per spec §12.2:

> The sidecar is a moving baseline: as the vision
> pipeline improves, the maintainer may update the
> `*.score.txt` thresholds upward. Each re-baseline
> is itself an amendment to this spec (§10).

Re-baseline triggers:

- A change to `app/core/evaluation.py` (the
  composite formula or its weights).
- A change to the OCR pipeline that improves
  extracted-graph accuracy.
- A change to the assembly detector that improves
  subsystem detection.
- A change to `app/core/orchestrator.py` that
  affects the build pipeline.

The cadence is not a fixed schedule; it is event-
driven. Each re-baseline is a separate commit with
a message of the form:

> Phase 17.4: Re-baseline validation pack after
> <reason>.

## What this is NOT

The validation pack is **not**:

- A CI test that fails on TBD sidecars. The
  regression test skips gracefully when a sidecar
  is TBD. The maintainer is the one who un-skips
  each fixture by writing a real threshold.
- A unit test. The pack is end-to-end (drawing
  upload → orchestrator → evaluation).
- A smoke test. The pack is a **regression test**
  for changes that affect the composite score.
- An automated baselining system. The sidecar
  values are maintainer-owned. The platform
  generates the PDFs and graph sidecars; the
  maintainer writes the score sidecars.

## Verification

After baselining at least one fixture, the
regression test should run that fixture end-to-end
and the other 5 should skip with the maintainer-
action message. The full platform suite should
still pass with 1263 + 1 = 1264 tests (the new
test counts as 1 even when skipping).

```bash
python -m pytest tests/test_hemp_decorticator_validation_pack.py -v
```

A passing run with at least one non-skipped
fixture confirms the baselining is wired correctly.
A failing run names the sidecar that needs
re-baselining or the code change that regressed
the composite score.
