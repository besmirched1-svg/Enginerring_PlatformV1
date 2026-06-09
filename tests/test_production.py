"""Tests for Autonomous Manufacturing & Deployment package (Phase 15)."""

import pytest

from app.production import (
    GCodeProgram,
    CutListDocument,
    WeldMapDocument,
    QASeverity,
    QAInspectionPlan,
    CommissioningPlan,
    FieldTelemetrySchema,
    ProductionPackage,
    generate_drilling_program,
    generate_profile_program,
    rectangle_points,
    build_cutlist_document,
    build_weldmap_document,
    build_qa_plan,
    build_commissioning_plan,
    build_telemetry_schema,
    build_production_package,
)
from app.manufacturing import (
    CutPart,
    analyze_cutlist,
    WeldJoint,
    WeldJointType,
    analyze_weldmap,
)
from app.manufacturing.cutlists import PartShape


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def cut_result():
    parts = [
        CutPart(part_id="side_panel", shape=PartShape.RECTANGLE,
                length_mm=800, width_mm=400, thickness_mm=6, quantity=2),
        CutPart(part_id="end_plate", shape=PartShape.RECTANGLE,
                length_mm=400, width_mm=400, thickness_mm=10, quantity=2),
    ]
    return analyze_cutlist(parts)


@pytest.fixture
def weld_map():
    joints = [
        WeldJoint(joint_id="seam_1", joint_type=WeldJointType.FILLET,
                  weld_length_mm=800, throat_thickness_mm=5,
                  plate_thickness_mm_1=6, plate_thickness_mm_2=6, passes=1),
        WeldJoint(joint_id="seam_2", joint_type=WeldJointType.BUTT,
                  weld_length_mm=400, throat_thickness_mm=8,
                  plate_thickness_mm_1=12, plate_thickness_mm_2=12, passes=3),
    ]
    return analyze_weldmap(joints)


# ===================================================================
# CNC
# ===================================================================

class TestCNC:
    def test_drilling_program(self):
        prog = generate_drilling_program([(10, 10), (50, 10), (50, 40)], depth_mm=8)
        assert isinstance(prog, GCodeProgram)
        text = prog.to_text()
        assert "G21" in text and "G90" in text
        assert "G81" in text            # canned drill cycle
        assert "G80" in text            # cancel
        assert "M30" in text            # program end
        # 3 holes -> one G81 line + two repeat lines
        assert text.count("drill hole") == 3

    def test_drilling_depth_negative(self):
        prog = generate_drilling_program([(0, 0)], depth_mm=5)
        assert "Z-5" in prog.to_text()

    def test_empty_holes(self):
        prog = generate_drilling_program([], depth_mm=5)
        assert "no holes" in prog.to_text()

    def test_profile_program_passes(self):
        pts = rectangle_points(100, 50)
        prog = generate_profile_program(pts, cut_depth_mm=6, depth_per_pass_mm=2)
        text = prog.to_text()
        # 6 mm / 2 mm = 3 passes
        assert text.count("plunge pass") == 3
        assert "M30" in text

    def test_profile_closed_returns_to_start(self):
        pts = rectangle_points(100, 50)
        prog = generate_profile_program(pts, cut_depth_mm=2, depth_per_pass_mm=2, closed=True)
        # closed loop: each pass visits 4 edges (3 other corners + back to start)
        text = prog.to_text()
        assert text.count("G01 X") >= 4

    def test_profile_too_few_points(self):
        prog = generate_profile_program([(0, 0)], cut_depth_mm=5)
        assert "at least 2 points" in prog.to_text()

    def test_rectangle_points(self):
        pts = rectangle_points(100, 50, origin=(10, 20))
        assert pts[0] == (10, 20)
        assert pts[2] == (110, 70)
        assert len(pts) == 4

    def test_to_dict(self):
        d = generate_drilling_program([(0, 0)], depth_mm=5).to_dict()
        assert d["operation"] == "drilling"
        assert "gcode" in d


# ===================================================================
# Documents
# ===================================================================

class TestDocuments:
    def test_cutlist_document(self, cut_result):
        doc = build_cutlist_document(cut_result, process="laser")
        assert isinstance(doc, CutListDocument)
        assert len(doc.rows) == 2
        assert doc.process == "laser"
        assert doc.total_parts >= 2

    def test_cutlist_csv(self, cut_result):
        csv = build_cutlist_document(cut_result).to_csv()
        assert "part_id" in csv.splitlines()[0]
        assert "side_panel" in csv

    def test_weldmap_document(self, weld_map):
        doc = build_weldmap_document(weld_map)
        assert isinstance(doc, WeldMapDocument)
        assert len(doc.rows) == 2
        assert doc.total_weld_length_mm > 0

    def test_weldmap_csv(self, weld_map):
        csv = build_weldmap_document(weld_map).to_csv()
        assert "joint_id" in csv
        assert "seam_1" in csv

    def test_empty_csv(self):
        assert CutListDocument().to_csv() == ""


# ===================================================================
# QA
# ===================================================================

class TestQA:
    def test_qa_plan(self, cut_result, weld_map):
        plan = build_qa_plan(cut_list=cut_result, weld_map=weld_map)
        assert isinstance(plan, QAInspectionPlan)
        assert plan.checks
        methods = {c.method for c in plan.checks}
        assert "dimensional" in methods
        assert "visual" in methods

    def test_multipass_weld_gets_ndt(self, weld_map):
        # seam_2 has 3 passes and 12 mm plate -> should trigger NDT
        plan = build_qa_plan(weld_map=weld_map)
        ndt = [c for c in plan.checks if c.method == "ndt"]
        assert ndt
        assert ndt[0].severity == QASeverity.CRITICAL

    def test_dimensional_checks_have_tolerance(self, cut_result):
        plan = build_qa_plan(cut_list=cut_result, dimensional_tolerance_mm=0.3)
        dims = [c for c in plan.checks if c.method == "dimensional"]
        assert dims
        assert all(c.tolerance == 0.3 for c in dims)

    def test_unique_check_ids(self, cut_result, weld_map):
        plan = build_qa_plan(cut_list=cut_result, weld_map=weld_map)
        ids = [c.check_id for c in plan.checks]
        assert len(ids) == len(set(ids))

    def test_empty_inputs_still_has_standard_checks(self):
        plan = build_qa_plan()
        assert len(plan.checks) >= 3


# ===================================================================
# Commissioning
# ===================================================================

class TestCommissioning:
    def test_plan(self):
        plan = build_commissioning_plan("Decorticator", rated_rpm=1500, rated_throughput_kg_hr=1000)
        assert isinstance(plan, CommissioningPlan)
        assert plan.steps
        # steps numbered sequentially
        assert [s.step_no for s in plan.steps] == list(range(1, len(plan.steps) + 1))

    def test_hold_points(self):
        plan = build_commissioning_plan("M")
        holds = [s for s in plan.steps if s.hold_point]
        assert holds

    def test_rated_values_add_steps(self):
        with_rated = build_commissioning_plan("M", rated_rpm=1500, rated_throughput_kg_hr=1000)
        without = build_commissioning_plan("M")
        assert len(with_rated.steps) > len(without.steps)


# ===================================================================
# Field telemetry
# ===================================================================

class TestFieldTelemetry:
    def test_schema(self):
        schema = build_telemetry_schema(
            machine_name="Decorticator", rated_rpm=1500,
            rated_power_kw=75, rated_throughput_kg_hr=1000,
        )
        assert isinstance(schema, FieldTelemetrySchema)
        names = {c.name for c in schema.channels}
        assert {"vibration_rms", "bearing_temperature", "shaft_speed",
                "motor_power", "throughput"}.issubset(names)

    def test_speed_alarm_bands(self):
        schema = build_telemetry_schema(rated_rpm=1000)
        speed = next(c for c in schema.channels if c.name == "shaft_speed")
        assert speed.alarm_low == pytest.approx(800)
        assert speed.alarm_high == pytest.approx(1200)

    def test_minimal_schema(self):
        schema = build_telemetry_schema(machine_name="x")
        # vibration + temperature always present
        assert len(schema.channels) == 2


# ===================================================================
# Production package
# ===================================================================

class TestProductionPackage:
    def test_full_package(self, cut_result, weld_map):
        prog = generate_drilling_program([(0, 0), (100, 0)], depth_mm=6)
        pkg = build_production_package(
            machine_name="Decorticator",
            cut_list_result=cut_result,
            weld_map=weld_map,
            cnc_programs=[prog],
            rated_rpm=1500, rated_power_kw=75, rated_throughput_kg_hr=1000,
        )
        assert isinstance(pkg, ProductionPackage)
        assert pkg.cut_list is not None
        assert pkg.weld_map is not None
        assert len(pkg.cnc_programs) == 1
        assert pkg.qa_plan.checks
        assert pkg.commissioning.steps
        assert pkg.telemetry.channels

    def test_package_to_dict(self, cut_result):
        pkg = build_production_package(machine_name="M", cut_list_result=cut_result)
        d = pkg.to_dict()
        assert d["machine_name"] == "M"
        assert d["cut_list"] is not None
        assert d["weld_map"] is None

    def test_minimal_package(self):
        pkg = build_production_package(machine_name="bare")
        # still produces QA, commissioning, telemetry
        assert pkg.qa_plan is not None
        assert pkg.commissioning is not None
        assert pkg.telemetry is not None
