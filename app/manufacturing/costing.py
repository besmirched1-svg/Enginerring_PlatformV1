# app/manufacturing/costing.py
# Build cost estimation: aggregates material, fabrication, machining, assembly costs

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger("engine.manufacturing.costing")


class CostCategory(str, Enum):
    """Categories of build cost."""
    MATERIAL = "material"
    FABRICATION_LABOUR = "fabrication_labour"
    MACHINING = "machining"
    ASSEMBLY = "assembly"
    WELDING_CONSUMABLES = "welding_consumables"
    FASTENERS = "fasteners"
    FINISHING = "finishing"
    INSPECTION = "inspection"
    FREIGHT = "freight"
    CONTINGENCY = "contingency"
    OVERHEAD = "overhead"
    PROFIT = "profit"


@dataclass
class CostLineItem:
    """A single line item in the cost breakdown."""
    category: CostCategory = CostCategory.MATERIAL
    description: str = ""
    quantity: float = 1.0
    unit: str = "each"
    unit_cost_aud: float = 0.0
    total_cost_aud: float = 0.0


@dataclass
class CostBreakdown:
    """Categorised cost breakdown."""
    line_items: List[CostLineItem] = field(default_factory=list)
    subtotal_by_category: dict = field(default_factory=dict)
    total_direct_cost_aud: float = 0.0
    contingency_pct: float = 10.0
    overhead_pct: float = 15.0
    profit_pct: float = 10.0
    contingency_amount_aud: float = 0.0
    overhead_amount_aud: float = 0.0
    profit_amount_aud: float = 0.0
    total_build_cost_aud: float = 0.0
    notes: List[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class CostEstimate:
    """Complete cost estimate with breakdown."""
    breakdown: Optional[CostBreakdown] = None
    material_cost_aud: float = 0.0
    fabrication_cost_aud: float = 0.0
    machining_cost_aud: float = 0.0
    assembly_cost_aud: float = 0.0
    consumables_cost_aud: float = 0.0
    total_direct_cost_aud: float = 0.0
    total_build_cost_aud: float = 0.0
    cost_per_kg_aud: float = 0.0
    estimated_mass_kg: float = 0.0
    notes: List[str] = field(default_factory=list)
    passed: bool = True


class CostAnalyzer:
    """Aggregates all cost inputs into a complete build cost estimate."""

    def __init__(
        self,
        contingency_pct: float = 10.0,
        overhead_pct: float = 15.0,
        profit_pct: float = 10.0,
    ):
        self.contingency_pct = contingency_pct
        self.overhead_pct = overhead_pct
        self.profit_pct = profit_pct

    def estimate(
        self,
        line_items: Optional[List[CostLineItem]] = None,
        material_cost_aud: float = 0.0,
        fabrication_cost_aud: float = 0.0,
        machining_cost_aud: float = 0.0,
        assembly_cost_aud: float = 0.0,
        consumables_cost_aud: float = 0.0,
        estimated_mass_kg: float = 0.0,
    ) -> CostEstimate:
        logger.info("Starting build cost estimation")

        if line_items:
            breakdown = self._build_breakdown(line_items)
            total_direct = breakdown.total_direct_cost_aud
            mat = breakdown.subtotal_by_category.get(CostCategory.MATERIAL, 0.0)
            fab = breakdown.subtotal_by_category.get(CostCategory.FABRICATION_LABOUR, 0.0)
            mach = breakdown.subtotal_by_category.get(CostCategory.MACHINING, 0.0)
            assy = breakdown.subtotal_by_category.get(CostCategory.ASSEMBLY, 0.0)
            cons = (
                breakdown.subtotal_by_category.get(CostCategory.WELDING_CONSUMABLES, 0.0)
                + breakdown.subtotal_by_category.get(CostCategory.FASTENERS, 0.0)
            )
        else:
            total_direct = (
                material_cost_aud
                + fabrication_cost_aud
                + machining_cost_aud
                + assembly_cost_aud
                + consumables_cost_aud
            )
            mat = material_cost_aud
            fab = fabrication_cost_aud
            mach = machining_cost_aud
            assy = assembly_cost_aud
            cons = consumables_cost_aud
            breakdown = None

        contingency = total_direct * self.contingency_pct / 100.0
        overhead = (total_direct + contingency) * self.overhead_pct / 100.0
        profit = (total_direct + contingency + overhead) * self.profit_pct / 100.0
        total_build = total_direct + contingency + overhead + profit

        cost_per_kg = (total_build / estimated_mass_kg) if estimated_mass_kg > 0 else 0.0

        notes = []
        if total_build <= 0:
            notes.append("Total build cost is zero - check inputs")
        if cost_per_kg > 100.0:
            notes.append(f"High cost per kg (AUD ${cost_per_kg:.2f})")

        passed = total_build > 0

        logger.info(
            "Cost estimate: direct AUD $%.2f, total AUD $%.2f",
            total_direct,
            total_build,
        )

        return CostEstimate(
            breakdown=breakdown,
            material_cost_aud=mat,
            fabrication_cost_aud=fab,
            machining_cost_aud=mach,
            assembly_cost_aud=assy,
            consumables_cost_aud=cons,
            total_direct_cost_aud=total_direct,
            total_build_cost_aud=total_build,
            cost_per_kg_aud=cost_per_kg,
            estimated_mass_kg=estimated_mass_kg,
            notes=notes,
            passed=passed,
        )

    def _build_breakdown(
        self, line_items: List[CostLineItem]
    ) -> CostBreakdown:
        by_cat: dict = {}
        total = 0.0

        for item in line_items:
            if item.total_cost_aud <= 0 and item.unit_cost_aud > 0:
                item.total_cost_aud = item.quantity * item.unit_cost_aud
            total += item.total_cost_aud
            cat = item.category.value
            by_cat[item.category] = by_cat.get(item.category, 0.0) + item.total_cost_aud

        cont = total * self.contingency_pct / 100.0
        oh = (total + cont) * self.overhead_pct / 100.0
        prof = (total + cont + oh) * self.profit_pct / 100.0
        grand = total + cont + oh + prof

        logger.debug(
            "Cost breakdown: direct=%.2f, cont=%.2f, oh=%.2f, profit=%.2f, total=%.2f",
            total,
            cont,
            oh,
            prof,
            grand,
        )

        return CostBreakdown(
            line_items=line_items,
            subtotal_by_category=by_cat,
            total_direct_cost_aud=total,
            contingency_pct=self.contingency_pct,
            overhead_pct=self.overhead_pct,
            profit_pct=self.profit_pct,
            contingency_amount_aud=cont,
            overhead_amount_aud=oh,
            profit_amount_aud=prof,
            total_build_cost_aud=grand,
            passed=total > 0,
        )


def estimate_build_cost(
    material_cost_aud: float = 0.0,
    fabrication_cost_aud: float = 0.0,
    machining_cost_aud: float = 0.0,
    assembly_cost_aud: float = 0.0,
    consumables_cost_aud: float = 0.0,
    estimated_mass_kg: float = 0.0,
    contingency_pct: float = 10.0,
    overhead_pct: float = 15.0,
    profit_pct: float = 10.0,
) -> CostEstimate:
    analyzer = CostAnalyzer(
        contingency_pct=contingency_pct,
        overhead_pct=overhead_pct,
        profit_pct=profit_pct,
    )
    return analyzer.estimate(
        material_cost_aud=material_cost_aud,
        fabrication_cost_aud=fabrication_cost_aud,
        machining_cost_aud=machining_cost_aud,
        assembly_cost_aud=assembly_cost_aud,
        consumables_cost_aud=consumables_cost_aud,
        estimated_mass_kg=estimated_mass_kg,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Build Cost Estimation")
    print("=" * 60)

    result = estimate_build_cost(
        material_cost_aud=4500.00,
        fabrication_cost_aud=3400.00,
        machining_cost_aud=2800.00,
        assembly_cost_aud=1200.00,
        consumables_cost_aud=350.00,
        estimated_mass_kg=850.0,
    )

    print(f"  Material Cost:             AUD ${result.material_cost_aud:>10.2f}")
    print(f"  Fabrication Labour:        AUD ${result.fabrication_cost_aud:>10.2f}")
    print(f"  Machining:                 AUD ${result.machining_cost_aud:>10.2f}")
    print(f"  Assembly:                  AUD ${result.assembly_cost_aud:>10.2f}")
    print(f"  Consumables:               AUD ${result.consumables_cost_aud:>10.2f}")
    print(f"  {'-' * 40}")
    print(f"  Total Direct Cost:         AUD ${result.total_direct_cost_aud:>10.2f}")
    print(f"  Total Build Cost:          AUD ${result.total_build_cost_aud:>10.2f}")
    print(f"  Cost per kg:               AUD ${result.cost_per_kg_aud:>10.2f}")
    print(f"  Estimated Mass:            {result.estimated_mass_kg:.1f} kg")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")

    print()
    print("  With Line-Item Breakdown:")
    items = [
        CostLineItem(CostCategory.MATERIAL, "Steel plate 6mm", 2.0, "sheet", 350.0),
        CostLineItem(CostCategory.MATERIAL, "Steel plate 10mm", 1.0, "sheet", 520.0),
        CostLineItem(CostCategory.MATERIAL, "Structural tube", 6.0, "m", 45.0),
        CostLineItem(CostCategory.FASTENERS, "M12 bolts", 48.0, "each", 0.85),
        CostLineItem(CostCategory.FASTENERS, "M16 bolts", 24.0, "each", 1.20),
        CostLineItem(CostCategory.FINISHING, "Paint system", 1.0, "lot", 650.0),
        CostLineItem(CostCategory.FABRICATION_LABOUR, "Cutting labour", 1.0, "lot", 800.0),
        CostLineItem(CostCategory.FABRICATION_LABOUR, "Welding labour", 1.0, "lot", 1600.0),
        CostLineItem(CostCategory.MACHINING, "CNC turning", 4.0, "hr", 90.0),
        CostLineItem(CostCategory.MACHINING, "CNC milling", 6.0, "hr", 95.0),
    ]

    analyzer = CostAnalyzer()
    detailed = analyzer.estimate(line_items=items, estimated_mass_kg=850.0)
    bd = detailed.breakdown
    print(f"    Direct Cost:             AUD ${bd.total_direct_cost_aud:>10.2f}")
    print(f"    Contingency ({bd.contingency_pct:.0f}%):          AUD ${bd.contingency_amount_aud:>10.2f}")
    print(f"    Overhead ({bd.overhead_pct:.0f}%):              AUD ${bd.overhead_amount_aud:>10.2f}")
    print(f"    Profit ({bd.profit_pct:.0f}%):                AUD ${bd.profit_amount_aud:>10.2f}")
    print(f"    {'-' * 40}")
    print(f"    Total Build Cost:         AUD ${bd.total_build_cost_aud:>10.2f}")
