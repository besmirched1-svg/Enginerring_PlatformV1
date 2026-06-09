from app.manufacturing.cutlists import (
    CutPart,
    CutListConfig,
    CutListAnalyzer,
    analyze_cutlist,
    PartShape,
    CutProcess,
)
from app.manufacturing.weldmaps import (
    WeldJoint,
    WeldJointType,
    WeldAnalyzer,
    analyze_weldmap,
)
from app.manufacturing.fabrication import (
    FabricationTask,
    FabricationTaskType,
    FabricationAnalyzer,
    estimate_fabrication,
)
from app.manufacturing.assembly import (
    AssemblyStep,
    AssemblyMethod,
    AssemblyAnalyzer,
    generate_assembly_sequence,
)
from app.manufacturing.machining import (
    MachiningOperation,
    MachiningOperationType,
    MachiningAnalyzer,
    estimate_machining,
)
from app.manufacturing.serviceability import (
    ServiceAccess,
    ServiceabilityAnalyzer,
    score_serviceability,
    AccessType,
    DifficultyLevel,
)
from app.manufacturing.costing import (
    CostLineItem,
    CostCategory,
    CostAnalyzer,
    estimate_build_cost,
)


# ---------------------------------------------------------------------------
# cutlists tests
# ---------------------------------------------------------------------------

def test_cutlist_empty_parts():
    result = analyze_cutlist([])
    assert result.total_parts == 0
    assert result.passed is False  # zero utilisation


def test_cutlist_single_part():
    parts = [CutPart(
        part_id="p1",
        shape=PartShape.RECTANGLE,
        length_mm=500.0,
        width_mm=300.0,
        thickness_mm=6.0,
        quantity=1,
    )]
    result = analyze_cutlist(parts)
    assert result.total_parts == 1
    assert result.sheets_required >= 1
    assert result.total_cut_length_mm > 0
    assert result.total_mass_kg > 0


def test_cutlist_round_parts():
    parts = [CutPart(
        part_id="disc",
        shape=PartShape.CIRCLE,
        length_mm=200.0,
        thickness_mm=10.0,
        quantity=4,
    )]
    result = analyze_cutlist(parts)
    assert result.total_parts == 4
    assert result.total_cut_length_mm > 0


def test_cutlist_low_utilisation():
    parts = [CutPart(
        part_id="tiny",
        shape=PartShape.RECTANGLE,
        length_mm=50.0,
        width_mm=30.0,
        thickness_mm=6.0,
        quantity=1,
    )]
    result = analyze_cutlist(parts)
    assert result.material_utilisation < 20.0
    assert result.passed is False


# ---------------------------------------------------------------------------
# weldmaps tests
# ---------------------------------------------------------------------------

def test_weldmap_empty():
    result = analyze_weldmap([])
    assert result.total_weld_length_mm == 0
    assert result.passed is False


def test_weldmap_fillet_joints():
    joints = [WeldJoint(
        joint_id="w1",
        joint_type=WeldJointType.FILLET,
        weld_length_mm=200.0,
        throat_thickness_mm=5.0,
        quantity=2,
    )]
    result = analyze_weldmap(joints)
    assert result.total_weld_length_mm == 400.0
    assert result.total_deposit_mass_kg > 0
    assert result.total_weld_time_minutes > 0


def test_weldmap_butt_joints():
    joints = [WeldJoint(
        joint_id="w2",
        joint_type=WeldJointType.BUTT,
        weld_length_mm=500.0,
        throat_thickness_mm=8.0,
        root_gap_mm=3.0,
        quantity=1,
    )]
    result = analyze_weldmap(joints)
    assert result.total_weld_length_mm == 500.0
    assert result.consumables.electrode_mass_kg > 0


# ---------------------------------------------------------------------------
# fabrication tests
# ---------------------------------------------------------------------------

def test_fabrication_empty():
    result = estimate_fabrication([])
    assert result.total_hours == 0
    assert result.passed is False


def test_fabrication_single_task():
    tasks = [FabricationTask(
        task_id="cut",
        task_type=FabricationTaskType.CUTTING,
        quantity=2,
        unit_time_minutes=10.0,
    )]
    result = estimate_fabrication(tasks)
    assert result.total_run_hours > 0
    assert result.effective_hours > result.total_hours
    assert result.labour_cost_aud > 0


def test_fabrication_complexity():
    simple = [FabricationTask(
        task_id="a", task_type=FabricationTaskType.WELDING,
        quantity=1, unit_time_minutes=10.0, complexity_factor=1.0,
    )]
    complex = [FabricationTask(
        task_id="b", task_type=FabricationTaskType.WELDING,
        quantity=1, unit_time_minutes=10.0, complexity_factor=2.0,
    )]
    r1 = estimate_fabrication(simple)
    r2 = estimate_fabrication(complex)
    assert r2.total_run_hours > r1.total_run_hours


# ---------------------------------------------------------------------------
# assembly tests
# ---------------------------------------------------------------------------

def test_assembly_empty():
    result = generate_assembly_sequence([])
    assert result.total_steps == 0
    assert result.passed is False


def test_assembly_simple_sequence():
    steps = [
        AssemblyStep(step_id="a", estimated_time_minutes=10.0),
        AssemblyStep(step_id="b", estimated_time_minutes=5.0, dependencies=["a"]),
    ]
    result = generate_assembly_sequence(steps)
    assert result.total_steps == 2
    assert result.total_time_minutes == 15.0
    assert result.steps[0].step_id == "a"
    assert result.steps[1].step_id == "b"


def test_assembly_topological_order():
    steps = [
        AssemblyStep(step_id="c", estimated_time_minutes=5.0, dependencies=["a"]),
        AssemblyStep(step_id="a", estimated_time_minutes=10.0),
        AssemblyStep(step_id="b", estimated_time_minutes=8.0, dependencies=["a"]),
    ]
    result = generate_assembly_sequence(steps)
    ids = [s.step_id for s in result.steps]
    assert ids.index("a") < ids.index("b")
    assert ids.index("a") < ids.index("c")


def test_assembly_critical_path():
    steps = [
        AssemblyStep(step_id="a", estimated_time_minutes=10.0),
        AssemblyStep(step_id="b", estimated_time_minutes=20.0, dependencies=["a"]),
        AssemblyStep(step_id="c", estimated_time_minutes=5.0, dependencies=["b"]),
    ]
    result = generate_assembly_sequence(steps)
    assert result.critical_path_minutes == 35.0  # 10 + 20 + 5


# ---------------------------------------------------------------------------
# machining tests
# ---------------------------------------------------------------------------

def test_machining_empty():
    result = estimate_machining([])
    assert result.total_time_hours == 0
    assert result.passed is False


def test_machining_turning():
    ops = [MachiningOperation(
        op_id="turn",
        operation_type=MachiningOperationType.TURNING,
        cut_length_mm=200.0,
        cut_diameter_mm=50.0,
        depth_of_cut_mm=2.0,
        quantity=1,
    )]
    result = estimate_machining(ops)
    assert result.total_machining_time_minutes > 0
    assert result.machining_cost_aud > 0


def test_machining_drilling():
    ops = [MachiningOperation(
        op_id="drill",
        operation_type=MachiningOperationType.DRILLING,
        cut_length_mm=15.0,
        cut_diameter_mm=10.0,
        quantity=12,
    )]
    result = estimate_machining(ops)
    assert result.total_machining_time_minutes > 0


# ---------------------------------------------------------------------------
# serviceability tests
# ---------------------------------------------------------------------------

def test_serviceability_empty():
    result = score_serviceability([])
    assert result.passed is False
    assert len(result.notes) > 0


def test_serviceability_good_access():
    points = [ServiceAccess(
        component_id="grease",
        access_type=AccessType.LUBRICATION,
        estimated_time_minutes=5.0,
        difficulty=DifficultyLevel.EASY,
        frequency_days=30,
    )]
    result = score_serviceability(points)
    assert result.serviceability_index >= 80.0
    assert result.passed is True


def test_serviceability_poor_access():
    points = [ServiceAccess(
        component_id="bearing",
        access_type=AccessType.REPLACEMENT,
        estimated_time_minutes=120.0,
        requires_dismantling=True,
        dismantling_time_minutes=60.0,
        difficulty=DifficultyLevel.VERY_DIFFICULT,
        frequency_days=365,
    )]
    result = score_serviceability(points)
    assert result.serviceability_index < 50.0
    assert result.passed is False


# ---------------------------------------------------------------------------
# costing tests
# ---------------------------------------------------------------------------

def test_cost_estimate_default():
    result = estimate_build_cost(
        material_cost_aud=1000.0,
        fabrication_cost_aud=500.0,
        machining_cost_aud=300.0,
        assembly_cost_aud=200.0,
        consumables_cost_aud=50.0,
        estimated_mass_kg=100.0,
    )
    assert result.total_direct_cost_aud == 2050.0
    assert result.total_build_cost_aud > result.total_direct_cost_aud
    assert result.cost_per_kg_aud > 0
    assert result.passed is True


def test_cost_estimate_zero():
    result = estimate_build_cost()
    assert result.total_direct_cost_aud == 0.0
    assert result.passed is False


def test_cost_line_items():
    items = [
        CostLineItem(CostCategory.MATERIAL, "steel", 2.0, "sheet", 500.0),
        CostLineItem(CostCategory.FASTENERS, "bolts", 50.0, "each", 0.50),
    ]
    analyzer = CostAnalyzer()
    result = analyzer.estimate(line_items=items, estimated_mass_kg=200.0)
    assert result.total_direct_cost_aud == 1025.0  # 2*500 + 50*0.5
    assert result.total_build_cost_aud > 1025.0
