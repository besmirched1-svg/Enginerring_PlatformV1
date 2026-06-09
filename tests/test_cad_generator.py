"""Tests for app/cad/generator.py — SCAD template generation."""
import pytest
from pathlib import Path
from app.cad.generator import (
    generate_roller_scad,
    generate_hopper_scad,
    generate_frame_scad,
    generate_spindle_scad,
    generate_drum_scad,
    generate_skid_frame_scad,
    generate_compression_roller_scad,
    generate_assembly_scad,
)


class TestLegacyGenerators:
    def test_roller_scad_written(self):
        path = generate_roller_scad({"diameter": 200, "width": 500, "shaft": 45})
        assert path.exists()
        content = path.read_text()
        assert "200" in content
        assert "500" in content
        assert "cylinder" in content

    def test_hopper_scad_written(self):
        path = generate_hopper_scad({"top_width": 400, "bottom_width": 120, "height": 300, "wall": 4})
        assert path.exists()
        content = path.read_text()
        assert "hopper" in content

    def test_frame_scad_written(self):
        path = generate_frame_scad({"length": 1200, "width": 600, "height": 800, "profile": 40})
        assert path.exists()
        content = path.read_text()
        assert "frame" in content


class TestIndustrialGenerators:
    def test_spindle_scad_written(self):
        path = generate_spindle_scad({
            "shaft_length": 4000, "shaft_od": 260, "flight_od": 600,
            "flight_pitch": 400, "flight_thickness": 25, "flight_turns": 10,
        })
        assert path.exists()
        content = path.read_text()
        assert "helical_spindle" in content
        assert "4000" in content

    def test_drum_scad_written(self):
        path = generate_drum_scad({
            "drum_id": 1500, "drum_length": 4000, "wall_thickness": 8,
            "perforation_diameter": 4, "perforation_pitch": 0,
        })
        assert path.exists()
        content = path.read_text()
        assert "trommel_drum" in content
        assert "1500" in content

    def test_skid_frame_scad_written(self):
        path = generate_skid_frame_scad({
            "rail_length": 5000, "rail_a": 250, "rail_b": 150, "rail_t": 10,
            "skid_width": 1800, "cross_a": 150, "cross_b": 100, "cross_t": 8,
            "cross_count": 5,
        })
        assert path.exists()
        content = path.read_text()
        assert "skid_frame" in content

    def test_compression_roller_scad_written(self):
        path = generate_compression_roller_scad({"diameter": 200, "width": 4000})
        assert path.exists()
        content = path.read_text()
        assert "compression_roller" in content


class TestAssemblyGeneration:
    def test_legacy_assembly_generated(self):
        machine = {
            "name": "test_legacy",
            "roller": {"diameter": 180, "width": 450, "shaft": 40},
            "hopper": {"top_width": 400, "bottom_width": 120, "height": 300, "wall": 4},
            "frame": {"length": 1200, "width": 600, "height": 800, "profile": 40},
        }
        result = generate_assembly_scad(machine)
        assert "assembly" in result
        assert result["assembly"].exists()
        content = result["assembly"].read_text()
        assert "test_legacy" in content

    def test_industrial_assembly_generated(self):
        machine = {
            "name": "HTDS-P2-test",
            "spindle": {
                "shaft_length": 4000, "shaft_od": 260, "flight_od": 600,
                "flight_pitch": 400, "flight_thickness": 25, "flight_turns": 10,
            },
            "drum": {
                "drum_id": 1500, "drum_length": 4000, "wall_thickness": 8,
                "perforation_diameter": 4, "perforation_pitch": 0,
            },
            "frame": {
                "rail_length": 5000, "rail_a": 250, "rail_b": 150, "rail_t": 10,
                "skid_width": 1800, "cross_a": 150, "cross_b": 100, "cross_t": 8,
                "cross_count": 5,
            },
        }
        result = generate_assembly_scad(machine)
        assert result["assembly"].exists()
        content = result["assembly"].read_text()
        assert "HTDS-P2-test" in content
        assert "helical_spindle" in content
        assert "trommel_drum" in content

    def test_assembly_components_dict_returned(self):
        machine = {
            "name": "test",
            "roller": {"diameter": 180, "width": 450, "shaft": 40},
        }
        result = generate_assembly_scad(machine)
        assert "components" in result
        assert isinstance(result["components"], dict)

    def test_partial_industrial_assembly(self):
        """Assembly with only drum (no spindle) should not crash."""
        machine = {
            "name": "drum_only",
            "drum": {
                "drum_id": 1500, "drum_length": 4000, "wall_thickness": 8,
                "perforation_diameter": 4, "perforation_pitch": 0,
            },
        }
        result = generate_assembly_scad(machine)
        assert result["assembly"].exists()
