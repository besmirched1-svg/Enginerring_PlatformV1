# app/manufacturing/__init__.py
# Manufacturing Intelligence package

from .cutlists import (
    CutPart,
    CutListConfig,
    CutListResult,
    CutListAnalyzer,
    analyze_cutlist,
)
from .weldmaps import (
    WeldJoint,
    WeldJointType,
    WeldMap,
    WeldConsumables,
    WeldAnalyzer,
    analyze_weldmap,
)
from .fabrication import (
    FabricationTask,
    FabricationTaskType,
    FabricationEstimate,
    FabricationAnalyzer,
    estimate_fabrication,
)
from .assembly import (
    AssemblyStep,
    AssemblySequence,
    AssemblyAnalyzer,
    generate_assembly_sequence,
)
from .machining import (
    MachiningOperation,
    MachiningOperationType,
    MachiningEstimate,
    MachiningAnalyzer,
    estimate_machining,
)
from .serviceability import (
    ServiceAccess,
    ServiceabilityScore,
    ServiceabilityAnalyzer,
    score_serviceability,
)
from .costing import (
    CostCategory,
    CostLineItem,
    CostBreakdown,
    CostEstimate,
    CostAnalyzer,
    estimate_build_cost,
)

__all__ = [
    # cutlists
    "CutPart",
    "CutListConfig",
    "CutListResult",
    "CutListAnalyzer",
    "analyze_cutlist",
    # weldmaps
    "WeldJoint",
    "WeldJointType",
    "WeldMap",
    "WeldConsumables",
    "WeldAnalyzer",
    "analyze_weldmap",
    # fabrication
    "FabricationTask",
    "FabricationTaskType",
    "FabricationEstimate",
    "FabricationAnalyzer",
    "estimate_fabrication",
    # assembly
    "AssemblyStep",
    "AssemblySequence",
    "AssemblyAnalyzer",
    "generate_assembly_sequence",
    # machining
    "MachiningOperation",
    "MachiningOperationType",
    "MachiningEstimate",
    "MachiningAnalyzer",
    "estimate_machining",
    # serviceability
    "ServiceAccess",
    "ServiceabilityScore",
    "ServiceabilityAnalyzer",
    "score_serviceability",
    # costing
    "CostCategory",
    "CostLineItem",
    "CostBreakdown",
    "CostEstimate",
    "CostAnalyzer",
    "estimate_build_cost",
]
