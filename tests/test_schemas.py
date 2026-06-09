"""Tests for app/core/schemas.py — Pydantic v2 machine config validation."""
import pytest
from pydantic import ValidationError
from app.core.schemas import (
    MachineConfig,
    SpindleConfig,
    DrumConfig,
    SkidFrameConfig,
    CompressionRollerConfig,
    RollerConfig,
    HopperConfig,
)


class TestSpindleConfig:
    def test_valid_defaults(self):
        s = SpindleConfig()
        assert s.flight_od > s.shaft_od

    def test_flight_od_must_exceed_shaft_od(self):
        with pytest.raises(ValidationError):
            SpindleConfig(shaft_od=300, flight_od=200)

    def test_flight_od_equal_shaft_od_rejected(self):
        with pytest.raises(ValidationError):
            SpindleConfig(shaft_od=260, flight_od=260)


class TestSkidFrameConfig:
    def test_valid_defaults(self):
        f = SkidFrameConfig()
        assert f.skid_width > 2 * f.rail_b

    def test_skid_width_too_narrow_rejected(self):
        with pytest.raises(ValidationError):
            SkidFrameConfig(rail_b=150, skid_width=200)  # 200 <= 2*150


class TestCompressionRollerConfig:
    def test_gap_upper_bound_enforced(self):
        with pytest.raises(ValidationError):
            CompressionRollerConfig(compression_gap=81)

    def test_gap_lower_bound_enforced(self):
        with pytest.raises(ValidationError):
            CompressionRollerConfig(compression_gap=-1)

    def test_valid_gap_accepted(self):
        c = CompressionRollerConfig(compression_gap=20)
        assert c.compression_gap == 20


class TestMachineConfig:
    def test_empty_config_valid(self):
        m = MachineConfig()
        assert m.name == "machine"

    def test_extra_keys_rejected(self):
        with pytest.raises(ValidationError):
            MachineConfig(unknown_key="bad")

    def test_industrial_frame_coerced(self):
        m = MachineConfig(frame={
            "rail_length": 5000, "rail_a": 250, "rail_b": 150,
            "rail_t": 10, "skid_width": 1800, "cross_a": 150,
            "cross_b": 100, "cross_t": 8, "cross_count": 5,
        })
        assert m.frame is not None
        assert "rail_length" in m.frame

    def test_legacy_frame_coerced(self):
        m = MachineConfig(frame={
            "length": 1200, "width": 600, "height": 800, "profile": 40
        })
        assert m.frame is not None
        assert "length" in m.frame

    def test_from_normalized_dict_strips_none(self):
        data = {"name": "test", "spindle": None, "drum": None}
        m = MachineConfig.from_normalized_dict(data)
        assert m.name == "test"
        assert m.spindle is None

    def test_full_industrial_config(self):
        m = MachineConfig(
            name="HTDS-P2",
            spindle={"shaft_od": 260, "flight_od": 600},
            drum={"drum_id": 1500, "drum_length": 4000, "wall_thickness": 8,
                  "perforation_diameter": 4, "perforation_pitch": 0},
            compression_rollers={"compression_gap": 20},
        )
        assert m.name == "HTDS-P2"
        assert m.spindle.shaft_od == 260
        assert m.drum.drum_id == 1500
