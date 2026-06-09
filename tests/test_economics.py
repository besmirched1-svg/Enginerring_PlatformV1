"""Tests for Economic Engineering package (Phase 12)."""

import math

import pytest

from app.economics import (
    EconomicAssumptions,
    CapitalCostResult,
    OperatingCostResult,
    MaintenanceCostResult,
    LifeCycleCostResult,
    OwnershipResult,
    EconomicAnalysis,
    compute_capital_cost,
    capital_from_factory,
    compute_operating_cost,
    compute_maintenance_cost,
    compute_lifecycle_cost,
    compute_ownership,
    annuity_present_value_factor,
    capital_recovery_factor,
    analyze_economics,
    analyze_factory_economics,
)
from app.factory.models import (
    FactoryProcessGraph,
    ProcessUnit,
    ProcessUnitType,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def assumptions():
    return EconomicAssumptions(
        plant_life_years=10,
        discount_rate=0.10,
        operating_hours_per_year=6000.0,
        electricity_cost_per_kwh=0.25,
        labour_rate_per_hr=45.0,
        num_operators=2.0,
        raw_material_cost_per_kg=0.50,
    )


@pytest.fixture
def factory_graph():
    g = FactoryProcessGraph(name="econ_factory")
    feed = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="Feed",
                       max_capacity_kg_hr=5000, capital_cost=80000, power_kw=5)
    mill = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill",
                       max_capacity_kg_hr=2000, efficiency=0.92, capital_cost=250000, power_kw=75)
    sep = ProcessUnit(unit_type=ProcessUnitType.SEPARATION, label="Sep",
                      max_capacity_kg_hr=1800, efficiency=0.88, capital_cost=180000, power_kw=30)
    pkg = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Pkg",
                      max_capacity_kg_hr=1500, capital_cost=120000, power_kw=10)
    for u in [feed, mill, sep, pkg]:
        g.add_unit(u)
    s1 = g.connect(feed.unit_id, mill.unit_id)
    g.connect(mill.unit_id, sep.unit_id)
    s3 = g.connect(sep.unit_id, pkg.unit_id)
    g.feed_streams = [s1.stream_id]
    g.product_streams = [s3.stream_id]
    return g


# ===================================================================
# Capital cost
# ===================================================================

class TestCapitalCost:
    def test_basic_capital(self, assumptions):
        r = compute_capital_cost(100000, assumptions)
        assert isinstance(r, CapitalCostResult)
        assert r.equipment_cost_aud == 100000
        assert r.installation_cost_aud == pytest.approx(30000)   # 0.30
        assert r.engineering_cost_aud == pytest.approx(12000)    # 0.12
        # subtotal 142000, contingency 10% = 14200, total 156200
        assert r.total_capital_aud == pytest.approx(156200)

    def test_total_exceeds_equipment(self, assumptions):
        r = compute_capital_cost(50000, assumptions)
        assert r.total_capital_aud > r.equipment_cost_aud

    def test_zero_equipment_warns(self):
        r = compute_capital_cost(0)
        assert r.total_capital_aud == 0
        assert any("zero" in n.lower() or "negative" in n.lower() for n in r.notes)

    def test_capital_from_factory(self, factory_graph, assumptions):
        r = capital_from_factory(factory_graph, assumptions)
        # equipment = 80k+250k+180k+120k = 630k
        assert r.equipment_cost_aud == pytest.approx(630000)
        assert r.total_capital_aud > 630000
        assert len(r.by_unit_aud) == 4
        assert r.by_unit_aud["Mill"] == pytest.approx(250000)

    def test_capital_from_factory_footprint_fallback(self, assumptions):
        g = FactoryProcessGraph()
        u = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="M",
                        footprint_m2=10.0)  # no capital_cost
        g.add_unit(u)
        r = capital_from_factory(g, assumptions)
        assert r.equipment_cost_aud == pytest.approx(50000)  # 10 * 5000
        assert any("footprint" in n.lower() for n in r.notes)

    def test_to_dict(self, assumptions):
        d = compute_capital_cost(100000, assumptions).to_dict()
        assert "total_capital_aud" in d
        assert "by_unit_aud" in d


# ===================================================================
# Operating cost
# ===================================================================

class TestOperatingCost:
    def test_basic_operating(self, assumptions):
        r = compute_operating_cost(power_kw=100, feed_rate_kg_hr=1000, assumptions=assumptions)
        assert isinstance(r, OperatingCostResult)
        # energy = 100 * 6000 * 0.25 = 150000
        assert r.energy_cost_aud == pytest.approx(150000)
        # labour = 2 * 45 * 6000 = 540000
        assert r.labour_cost_aud == pytest.approx(540000)
        # raw material = 1000 * 6000 * 0.50 = 3000000
        assert r.raw_material_cost_aud == pytest.approx(3000000)
        assert r.total_annual_aud == pytest.approx(
            r.energy_cost_aud + r.labour_cost_aud + r.raw_material_cost_aud
            + r.utilities_cost_aud + r.consumables_cost_aud
        )

    def test_zero_inputs_warn(self, assumptions):
        a = EconomicAssumptions(
            operating_hours_per_year=0, num_operators=0,
            utilities_cost_per_hr=0, consumables_cost_per_hr=0,
        )
        r = compute_operating_cost(0, 0, a)
        assert r.total_annual_aud == 0
        assert r.notes

    def test_by_category(self, assumptions):
        r = compute_operating_cost(50, 500, assumptions)
        assert set(r.by_category_aud.keys()) == {
            "energy", "labour", "raw_material", "utilities", "consumables"
        }

    def test_to_dict(self, assumptions):
        d = compute_operating_cost(50, 500, assumptions).to_dict()
        assert "total_annual_aud" in d


# ===================================================================
# Maintenance cost
# ===================================================================

class TestMaintenanceCost:
    def test_scheduled_only(self, assumptions):
        r = compute_maintenance_cost(1000000, assumptions)
        assert isinstance(r, MaintenanceCostResult)
        # 4% of 1,000,000
        assert r.scheduled_aud == pytest.approx(40000)
        assert r.unscheduled_aud == 0
        assert r.total_annual_aud == pytest.approx(40000)

    def test_with_mtbf(self, assumptions):
        r = compute_maintenance_cost(
            1000000, assumptions, mtbf_hours=2000,
            mean_repair_hours=8, repair_cost_per_event_aud=1500,
            downtime_cost_per_hr_aud=250,
        )
        # failures/yr = 6000/2000 = 3
        assert r.expected_failures_per_year == pytest.approx(3.0)
        assert r.unscheduled_aud == pytest.approx(3 * 1500)
        assert r.downtime_cost_aud == pytest.approx(3 * 8 * 250)
        assert r.total_annual_aud > r.scheduled_aud

    def test_zero_mtbf_warns(self, assumptions):
        r = compute_maintenance_cost(100000, assumptions, mtbf_hours=0)
        assert r.unscheduled_aud == 0
        assert r.notes

    def test_to_dict(self, assumptions):
        d = compute_maintenance_cost(100000, assumptions).to_dict()
        assert "total_annual_aud" in d


# ===================================================================
# Life-cycle cost
# ===================================================================

class TestLifeCycleCost:
    def test_annuity_factors(self):
        # PV of 1/yr for 10 yr at 10%
        assert annuity_present_value_factor(0.10, 10) == pytest.approx(6.14457, abs=1e-4)
        # zero rate -> just the count
        assert annuity_present_value_factor(0.0, 10) == 10.0
        assert annuity_present_value_factor(0.10, 0) == 0.0

    def test_capital_recovery_factor(self):
        crf = capital_recovery_factor(0.10, 10)
        assert crf == pytest.approx(0.162745, abs=1e-5)
        # CRF is reciprocal of annuity PV factor
        assert crf == pytest.approx(1.0 / annuity_present_value_factor(0.10, 10))

    def test_lifecycle_basic(self, assumptions):
        r = compute_lifecycle_cost(
            capital_aud=1000000,
            annual_operating_aud=200000,
            annual_maintenance_aud=40000,
            annual_production_kg=1000000,
            assumptions=assumptions,
        )
        assert isinstance(r, LifeCycleCostResult)
        pv = annuity_present_value_factor(0.10, 10)
        assert r.npv_operating_aud == pytest.approx(200000 * pv)
        assert r.total_lcc_aud == pytest.approx(1000000 + (200000 + 40000) * pv)
        assert r.cost_per_kg_aud > 0

    def test_cost_per_kg(self, assumptions):
        r = compute_lifecycle_cost(1000000, 200000, 40000, 1000000, assumptions)
        # EAC = 1,000,000 * CRF + 240,000
        crf = capital_recovery_factor(0.10, 10)
        eac = 1000000 * crf + 240000
        assert r.equivalent_annual_cost_aud == pytest.approx(eac)
        assert r.cost_per_kg_aud == pytest.approx(eac / 1000000)

    def test_zero_production_warns(self, assumptions):
        r = compute_lifecycle_cost(1000000, 200000, 40000, 0, assumptions)
        assert r.cost_per_kg_aud == 0
        assert r.notes

    def test_zero_discount_rate(self):
        a = EconomicAssumptions(plant_life_years=10, discount_rate=0.0)
        r = compute_lifecycle_cost(1000000, 100000, 0, 500000, a)
        # NPV with 0% = sum undiscounted = 100000 * 10
        assert r.npv_operating_aud == pytest.approx(1000000)

    def test_to_dict(self, assumptions):
        d = compute_lifecycle_cost(1000000, 200000, 40000, 1000000, assumptions).to_dict()
        assert "cost_per_kg_aud" in d


# ===================================================================
# Ownership
# ===================================================================

class TestOwnership:
    def test_profitable_project(self, assumptions):
        lcc = compute_lifecycle_cost(1000000, 200000, 40000, 1000000, assumptions)
        r = compute_ownership(lcc, product_price_per_kg_aud=1.0, assumptions=assumptions)
        assert isinstance(r, OwnershipResult)
        # revenue = 1,000,000 kg * 1.0 = 1,000,000
        assert r.annual_revenue_aud == pytest.approx(1000000)
        assert r.annual_profit_aud > 0
        assert r.payback_period_years > 0 and math.isfinite(r.payback_period_years)
        assert r.return_on_investment_pct > 0

    def test_unprofitable_project(self, assumptions):
        lcc = compute_lifecycle_cost(1000000, 2000000, 40000, 1000000, assumptions)
        r = compute_ownership(lcc, product_price_per_kg_aud=0.10, assumptions=assumptions)
        assert r.annual_profit_aud < 0
        assert not r.profitable
        assert not math.isfinite(r.payback_period_years)
        assert r.internal_rate_of_return_pct == -1.0
        assert r.notes

    def test_npv_sign_matches_profitable(self, assumptions):
        lcc = compute_lifecycle_cost(500000, 100000, 20000, 1000000, assumptions)
        r = compute_ownership(lcc, product_price_per_kg_aud=0.50, assumptions=assumptions)
        assert r.profitable == (r.net_present_value_aud > 0)

    def test_irr_reasonable(self, assumptions):
        lcc = compute_lifecycle_cost(1000000, 100000, 0, 1000000, assumptions)
        r = compute_ownership(lcc, product_price_per_kg_aud=0.50, assumptions=assumptions)
        # profit ~ 400000/yr on 1M capital -> IRR should be solidly positive
        assert r.internal_rate_of_return_pct > 0

    def test_to_dict(self, assumptions):
        lcc = compute_lifecycle_cost(1000000, 200000, 40000, 1000000, assumptions)
        d = compute_ownership(lcc, 1.0, assumptions).to_dict()
        assert "payback_period_years" in d


# ===================================================================
# Orchestration
# ===================================================================

class TestAnalyzeEconomics:
    def test_full_analysis(self, assumptions):
        r = analyze_economics(
            equipment_cost_aud=630000,
            power_kw=120,
            feed_rate_kg_hr=1000,
            product_rate_kg_hr=800,
            assumptions=assumptions,
            product_price_per_kg_aud=1.5,
            mtbf_hours=3000,
        )
        assert isinstance(r, EconomicAnalysis)
        assert r.capital.total_capital_aud > 0
        assert r.operating.total_annual_aud > 0
        assert r.maintenance.total_annual_aud > 0
        assert r.lifecycle.cost_per_kg_aud > 0
        assert r.ownership.annual_revenue_aud > 0

    def test_to_dict(self, assumptions):
        r = analyze_economics(500000, 100, 1000, 800, assumptions, 1.0)
        d = r.to_dict()
        assert set(d.keys()) == {
            "capital", "operating", "maintenance", "lifecycle", "ownership", "assumptions"
        }


class TestFactoryEconomics:
    def test_factory_integration(self, factory_graph, assumptions):
        r = analyze_factory_economics(
            factory_graph,
            assumptions=assumptions,
            feed_rate_kg_hr=1000,
            product_price_per_kg_aud=2.0,
        )
        assert isinstance(r, EconomicAnalysis)
        # equipment cost should match the summed unit capital
        assert r.capital.equipment_cost_aud == pytest.approx(630000)
        assert r.lifecycle.annual_production_kg > 0
        assert r.lifecycle.cost_per_kg_aud > 0

    def test_factory_with_mtbf(self, factory_graph, assumptions):
        r = analyze_factory_economics(
            factory_graph, assumptions, feed_rate_kg_hr=1000, mtbf_hours=2000
        )
        assert r.maintenance.expected_failures_per_year > 0

    def test_higher_price_more_profitable(self, factory_graph, assumptions):
        low = analyze_factory_economics(factory_graph, assumptions, 1000, product_price_per_kg_aud=0.5)
        high = analyze_factory_economics(factory_graph, assumptions, 1000, product_price_per_kg_aud=5.0)
        assert high.ownership.annual_profit_aud > low.ownership.annual_profit_aud


# ===================================================================
# API
# ===================================================================

class TestEconomicsAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_analyze_endpoint(self, client):
        r = client.post("/api/economics/analyze", json={
            "equipment_cost_aud": 630000, "power_kw": 120,
            "feed_rate_kg_hr": 1000, "product_rate_kg_hr": 800,
            "product_price_per_kg_aud": 1.5, "mtbf_hours": 3000,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["economics"]["lifecycle"]["cost_per_kg_aud"] > 0
        assert body["economics"]["capital"]["total_capital_aud"] > 0

    def test_factory_endpoint(self, client):
        r = client.post("/api/economics/factory", json={
            "feed_rate_kg_hr": 1000, "product_price_per_kg_aud": 2.0,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["economics"]["ownership"]["annual_revenue_aud"] > 0

    def test_custom_assumptions(self, client):
        r = client.post("/api/economics/analyze", json={
            "equipment_cost_aud": 500000, "power_kw": 100,
            "feed_rate_kg_hr": 1000, "product_rate_kg_hr": 800,
            "assumptions": {"plant_life_years": 15, "discount_rate": 0.12},
        })
        assert r.status_code == 200
        body = r.json()
        assert body["economics"]["lifecycle"]["plant_life_years"] == 15
        # price defaults to 0 -> unprofitable -> payback must serialize as null, not inf
        assert body["economics"]["ownership"]["payback_period_years"] is None
