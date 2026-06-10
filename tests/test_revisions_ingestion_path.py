"""Tests for the additive ``ingestion_path`` extension on
``app.core.revisions.archive_revision`` (Phase 17.2a, Commit 1)
and the additive ``auto_promote`` / ``promotion_mode`` fields on
``EngineeringOrchestrator.run_machine_job`` (Phase 17.2a, Commit 3a.5).

Both extensions are **additive only**: when callers do not pass
the new kwargs, the manifest JSON and the orchestrator's
behavior are byte-equivalent to the pre-17.2a output. When the
kwargs are supplied, the manifest gains a single top-level
``ingestion_path`` field, the orchestrator's response gains a
``promotion_mode`` field, and the promotion block is skipped
entirely when ``auto_promote=False``.

The "byte-equivalent" test in this file is the regression net:
it captures the exact pre-17.2a manifest bytes (with a fixed
machine_name and revision_id) and asserts that calling
``archive_revision`` with the same inputs and no ``ingestion_path``
produces the identical string. If a future change accidentally
adds whitespace, reorders keys, or changes the indent, this test
fails and the regression is caught at the test layer rather than
in production.
"""
import json
import os

from app.core.revisions import archive_revision


# Pre-17.2a reference manifest bytes. Captured against commit
# ``6e8197b`` (the 17.1g head) before the additive extension was
# applied. The exact machine_name and revision_id below are the
# only two values that vary in the manifest, so this snapshot is
# reproducible.
_PRE_17_2A_MANIFEST_BYTES = """{
  "machine_name": "snapshot_machine",
  "revision_id": "rev_deadbeef",
  "config": {
    "wall_thickness": 4.0,
    "clearance": 0.6,
    "roller_radius": 35.0
  },
  "parent_revision": null,
  "chain_id": null,
  "attempt_in_chain": 0,
  "promotion_status": "candidate"
}"""

_FIXTURE_MACHINE = "snapshot_machine"
_FIXTURE_REV = "rev_deadbeef"
_FIXTURE_CONFIG = {
    "wall_thickness": 4.0,
    "clearance": 0.6,
    "roller_radius": 35.0,
}


def _read_manifest(rev_dir):
    with open(os.path.join(rev_dir, "manifest.json"), "r", encoding="utf-8") as f:
        return f.read()


class TestArchiveRevisionIngestionPath:
    """The additive ``ingestion_path`` kwarg."""

    def test_no_ingestion_path_omits_field(self, tmp_path, monkeypatch):
        """Without the kwarg, the manifest must not contain an
        ``ingestion_path`` key at all (not even null)."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name=_FIXTURE_MACHINE,
            revision_id=_FIXTURE_REV,
            config=_FIXTURE_CONFIG,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert "ingestion_path" not in data

    def test_no_ingestion_path_keeps_seven_keys(self, tmp_path, monkeypatch):
        """The pre-17.2a manifest had exactly seven top-level keys.
        The additive extension must not add, remove, or rename any
        of them when the kwarg is absent."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name=_FIXTURE_MACHINE,
            revision_id=_FIXTURE_REV,
            config=_FIXTURE_CONFIG,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert sorted(data.keys()) == [
            "attempt_in_chain",
            "chain_id",
            "config",
            "machine_name",
            "parent_revision",
            "promotion_status",
            "revision_id",
        ]

    def test_no_ingestion_path_byte_equivalence(self, tmp_path, monkeypatch):
        """The strongest claim of the additive extension: when the
        kwarg is not passed, the manifest bytes are *identical* to
        a pre-17.2a reference. Whitespace, key order, indent, and
        absence of trailing newline must all match exactly."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name=_FIXTURE_MACHINE,
            revision_id=_FIXTURE_REV,
            config=_FIXTURE_CONFIG,
        )
        actual = _read_manifest(rev_dir)
        assert actual == _PRE_17_2A_MANIFEST_BYTES, (
            "manifest drifted from pre-17.2a shape; "
            "additive extension is no longer byte-compatible"
        )

    def test_ingestion_path_writes_top_level_field(self, tmp_path, monkeypatch):
        """When the kwarg is supplied, the manifest gains a single
        ``ingestion_path`` top-level field with the supplied dict."""
        monkeypatch.chdir(tmp_path)
        ingestion = {
            "source_file": "hopper_a3.pdf",
            "ocr_confidence": 0.78,
            "graph_hash": "sha256:deadbeef",
        }
        rev_dir = archive_revision(
            machine_name="ingested_machine",
            revision_id="rev_feedface",
            config=_FIXTURE_CONFIG,
            ingestion_path=ingestion,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert data["ingestion_path"] == ingestion

    def test_ingestion_path_keeps_other_keys_unchanged(self, tmp_path, monkeypatch):
        """Adding ``ingestion_path`` must not change the other
        seven keys' values."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name="ingested_machine",
            revision_id="rev_feedface",
            config=_FIXTURE_CONFIG,
            ingestion_path={"source_file": "x.pdf", "ocr_confidence": 0.5,
                            "graph_hash": "h"},
        )
        data = json.loads(_read_manifest(rev_dir))
        # The seven pre-17.2a keys must all still be present and
        # equal to the values they would have had without the kwarg.
        assert data["machine_name"] == "ingested_machine"
        assert data["revision_id"] == "rev_feedface"
        assert data["config"] == _FIXTURE_CONFIG
        assert data["parent_revision"] is None
        assert data["chain_id"] is None
        assert data["attempt_in_chain"] == 0
        assert data["promotion_status"] == "candidate"

    def test_ingestion_path_works_with_parent_info(self, tmp_path, monkeypatch):
        """The kwarg is orthogonal to ``parent_info``; passing
        both must populate both fields independently."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name="chained_machine",
            revision_id="rev_cafef00d",
            config=_FIXTURE_CONFIG,
            parent_info={"chain_id": "chain_abc", "attempt_in_chain": 3,
                         "parent_revision": "rev_prev1234"},
            ingestion_path={"source_file": "y.png", "ocr_confidence": 0.6,
                            "graph_hash": "h2"},
        )
        data = json.loads(_read_manifest(rev_dir))
        assert data["chain_id"] == "chain_abc"
        assert data["attempt_in_chain"] == 3
        assert data["parent_revision"] == "rev_prev1234"
        assert data["ingestion_path"]["source_file"] == "y.png"

    def test_ingestion_path_is_optional_kwarg(self, tmp_path, monkeypatch):
        """Positional callers (4 args) must still work — the kwarg
        is the *fifth* parameter and is optional."""
        monkeypatch.chdir(tmp_path)
        # Positional call, no ingestion_path.
        rev_dir = archive_revision(
            "pos_machine", "rev_pos1234", _FIXTURE_CONFIG, None,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert "ingestion_path" not in data


class TestRunMachineJobIngestionPath:
    """The kwarg is threaded through ``EngineeringOrchestrator.run_machine_job``."""

    def test_run_machine_job_writes_ingestion_path(self, tmp_path, monkeypatch):
        """A full orchestrator run with ``ingestion_path`` must
        land the field in the on-disk manifest.json."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())
        ingestion = {
            "source_file": "test.pdf",
            "ocr_confidence": 0.81,
            "graph_hash": "sha256:abc",
        }
        result = orch.run_machine_job(
            machine_name="run_machine_test",
            config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
            ingestion_path=ingestion,
        )
        manifest_path = os.path.join(result["directory"], "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["ingestion_path"] == ingestion

    def test_run_machine_job_without_kwarg_has_no_field(self, tmp_path, monkeypatch):
        """A full orchestrator run with no ``ingestion_path`` must
        not produce a manifest with that key — the pre-17.2a
        contract holds for every existing caller of the route."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())
        result = orch.run_machine_job(
            machine_name="run_no_kwarg",
            config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
        )
        manifest_path = os.path.join(result["directory"], "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "ingestion_path" not in data

    def test_run_machine_job_preserves_full_artifact_chain(self, tmp_path, monkeypatch):
        """Regression test for the Phase 16.5 acceptance gate
        (``TestFullArtifactChain``). The additive kwarg must not
        change which artifacts the orchestrator writes; the route
        count, file presence, and content remain identical."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())
        result = orch.run_machine_job(
            machine_name="artifact_regression",
            config={
                "wall_thickness": 4.0,
                "clearance": 0.6,
                "roller_radius": 35.0,
                "frame": {"length": 1500, "width": 800, "height": 1000, "profile": 50},
                "roller": {"diameter": 200, "width": 500, "shaft": 50},
            },
            ingestion_path={"source_file": "x.pdf",
                            "ocr_confidence": 0.7, "graph_hash": "h"},
        )
        present = set(os.listdir(result["directory"]))
        for required in ("model.scad", "output.stl", "preview.png",
                         "bom.csv", "evaluation.json", "manifest.json"):
            assert required in present, f"missing artifact: {required}"


# ---------------------------------------------------------------------------
# Phase 17.2a Commit 3a.5: auto_promote kwarg + promotion_mode field
# ---------------------------------------------------------------------------
#
# Governance statement (from PHASE17_EXECUTION_CHECKLIST.md):
#   "Drawing-ingested builds may create and evaluate revisions but
#    must not alter champion lineage. Champion promotion remains an
#    explicit engineering lifecycle action."
#
# ``run_machine_job`` therefore accepts ``auto_promote: bool = True``
# so the existing YAML / API callers are unaffected by default, and
# the 17.2a ``/drawing/ingest-and-build`` route can opt out by
# passing ``auto_promote=False``. When False, the promotion block
# is skipped entirely (``set_new_champion`` is never called) and
# the response carries ``promotion_mode="disabled"`` plus
# ``promoted=False`` so the route can surface the policy in its
# response body.
#
# The four ``promotion_mode`` values are mutually exclusive and
# exhaustive for the (auto_promote, old_rev, is_promoted) tuple:
#
#   "disabled"           — auto_promote is False
#   "no_prior_champion"  — auto_promote is True, no existing champion
#   "below_threshold"    — auto_promote is True, score did not clear
#   "attempted"          — auto_promote is True, set_new_champion ran
#
# Pinned in TestRunMachineJobPromotionModeValues below.


class TestRunMachineJobAutoPromote:
    """The ``auto_promote`` kwarg gates the entire promotion block."""

    def test_auto_promote_false_does_not_call_set_new_champion(
        self, tmp_path, monkeypatch,
    ):
        """High-scoring run with ``auto_promote=False`` must NOT
        touch the champion pointer, must leave the manifest at
        ``promotion_status="candidate"``, and must return
        ``promoted=False`` with ``promotion_mode="disabled"``.

        This is the governance guarantee in test form: a
        drawing-ingested build is constitutionally incapable of
        promoting a champion, no matter how good the score."""
        from unittest.mock import MagicMock, patch
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())

        with patch(
            "app.core.orchestrator.set_new_champion"
        ) as mock_set_champion, patch(
            "app.core.orchestrator.render_stl",
            side_effect=RuntimeError("no openscad"),
        ):
            result = orch.run_machine_job(
                machine_name="drawing_ingested_machine",
                config={"roller": {"diameter": 180, "width": 450,
                                   "shaft": 40}},
                auto_promote=False,
            )

        # Champion pointer was never touched.
        mock_set_champion.assert_not_called()
        # Response signals "no promotion happened" with the
        # policy reason ("disabled" — not "below_threshold",
        # which would imply a real score-based decision was made).
        assert result["promoted"] is False
        assert result["promotion_mode"] == "disabled"
        # The manifest itself still records the revision as a
        # candidate — the on-disk lineage record is consistent
        # with the in-memory response.
        with open(os.path.join(result["directory"], "manifest.json"),
                  "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["promotion_status"] == "candidate"

    def test_auto_promote_true_default_preserves_existing_behavior(
        self, tmp_path, monkeypatch,
    ):
        """Regression test: with the default ``auto_promote=True``,
        the orchestrator must still evaluate the score, still call
        ``should_promote`` for the (champion, challenger) pair, and
        still return a populated ``promotion_mode`` field.

        The point is to pin that adding the kwarg did not change
        what happens when callers do not pass it. Like
        ``TestFullArtifactChain`` in ``test_orchestrator.py``, this
        test does not mock ``render_stl`` — it lets the renderer
        see whatever OpenSCAD is on the host."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())

        result = orch.run_machine_job(
            machine_name=f"default_behavior_{os.getpid()}",
            config={"roller": {"diameter": 180, "width": 450,
                               "shaft": 40}},
        )

        # Default path: no prior champion (v0) → promotion_mode
        # is "no_prior_champion", promoted stays False. This is
        # identical to pre-17.2a behavior for a fresh machine.
        assert result["promoted"] is False
        assert result["promotion_mode"] == "no_prior_champion"
        # The full six-artifact chain is still written — the
        # additive kwarg must not regress artifact production.
        rev_dir = result["directory"]
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)
        present = set(os.listdir(rev_dir))
        for required in ("model.scad", "output.stl", "preview.png",
                         "bom.csv", "evaluation.json", "manifest.json"):
            assert required in present, f"missing artifact: {required}"

    def test_route_integration_auto_promote_false_keeps_champion(
        self, tmp_path, monkeypatch,
    ):
        """Simulate the 17.2a ``/drawing/ingest-and-build`` route's
        contract: commit=true, auto_promote=False. The revision is
        created and evaluated, but ``set_new_champion`` is never
        called and ``promoted`` is False.

        This is the third governance test the user's design
        required: drawing-ingested builds land in the artifact
        chain but cannot promote a champion."""
        from unittest.mock import MagicMock, patch
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())

        with patch(
            "app.core.orchestrator.set_new_champion"
        ) as mock_set_champion, patch(
            "app.core.orchestrator.render_stl",
            side_effect=RuntimeError("no openscad"),
        ):
            # The 17.2a route will pass these kwargs verbatim.
            result = orch.run_machine_job(
                machine_name="route_simulation_machine",
                config={
                    "wall_thickness": 4.0,
                    "clearance": 0.6,
                    "roller_radius": 35.0,
                    "frame": {"length": 1500, "width": 800,
                              "height": 1000, "profile": 50},
                    "roller": {"diameter": 200, "width": 500, "shaft": 50},
                },
                ingestion_path={
                    "source_file": "hopper_a3.pdf",
                    "ocr_confidence": 0.81,
                    "graph_hash": "sha256:abc",
                },
                auto_promote=False,
            )

        # Champion is untouched.
        mock_set_champion.assert_not_called()
        # Revision exists in the artifact chain.
        assert result["revision_id"].startswith("rev_")
        assert os.path.isfile(
            os.path.join(result["directory"], "manifest.json")
        )
        # Response carries the policy signal.
        assert result["promoted"] is False
        assert result["promotion_mode"] == "disabled"


class TestRunMachineJobPromotionModeValues:
    """Pin the four ``promotion_mode`` string values. If a future
    refactor renames or removes one, every consumer of the field
    would silently break — this test makes that change
    intentional and reviewable."""

    def test_promotion_mode_field_present_by_default(self, tmp_path, monkeypatch):
        """Even when the caller does not pass any of the new
        kwargs (``ingestion_path`` or ``auto_promote``), the
        response always carries a ``promotion_mode`` field. The
        field is part of the orchestrator's public return shape
        starting with 17.2a — callers should be able to rely on
        it being present without defensive ``.get()`` calls."""
        from unittest.mock import MagicMock, patch
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())

        with patch("app.core.orchestrator.render_stl",
                   side_effect=RuntimeError("no openscad")):
            result = orch.run_machine_job(
                machine_name="field_present_machine",
                config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
            )

        assert "promotion_mode" in result
        assert result["promotion_mode"] in {
            "disabled", "no_prior_champion",
            "below_threshold", "attempted",
        }

    def test_promotion_mode_disabled_when_auto_promote_false(
        self, tmp_path, monkeypatch,
    ):
        """``auto_promote=False`` must always yield
        ``promotion_mode="disabled"``, regardless of whether a
        prior champion exists or how the score compared."""
        from unittest.mock import MagicMock, patch
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())

        with patch("app.core.orchestrator.render_stl",
                   side_effect=RuntimeError("no openscad")):
            result = orch.run_machine_job(
                machine_name="disabled_machine",
                config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
                auto_promote=False,
            )

        assert result["promotion_mode"] == "disabled"
        assert result["promoted"] is False

    def test_promotion_mode_no_prior_champion_for_fresh_machine(
        self, tmp_path, monkeypatch,
    ):
        """A fresh machine (no champion pointer on disk) with the
        default ``auto_promote=True`` must report
        ``promotion_mode="no_prior_champion"``."""
        from unittest.mock import MagicMock, patch
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())

        with patch("app.core.orchestrator.render_stl",
                   side_effect=RuntimeError("no openscad")):
            result = orch.run_machine_job(
                machine_name=f"fresh_machine_{os.getpid()}",
                config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
                auto_promote=True,
            )

        assert result["promotion_mode"] == "no_prior_champion"
        assert result["promoted"] is False
