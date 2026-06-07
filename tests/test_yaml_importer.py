"""Tests for app/importers/yaml_importer.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.importers.yaml_importer import (
    _normalize,
    _validate,
    InvalidMachineConfigError,
)


class TestNormalize:
    def test_wrapped_machine_key(self):
        data = {"machine": {"name": "test", "roller": {"diameter": 180}}}
        result = _normalize(data)
        assert result["name"] == "test"

    def test_flat_roller_becomes_nested(self):
        data = {"diameter": 180, "width": 450, "shaft": 40}
        result = _normalize(data)
        assert "roller" in result
        assert result["roller"]["diameter"] == 180

    def test_industrial_keys_at_root(self):
        data = {"spindle": {"shaft_od": 260, "flight_od": 600}, "name": "P2"}
        result = _normalize(data)
        assert "spindle" in result
        assert result["name"] == "P2"

    def test_non_dict_raises(self):
        with pytest.raises(InvalidMachineConfigError):
            _normalize("not a dict")

    def test_name_defaults_to_machine(self):
        result = _normalize({"roller": {"diameter": 180}})
        assert result["name"] == "machine"


class TestValidate:
    def test_valid_roller_config(self):
        machine = {"name": "test", "roller": {"diameter": 180, "width": 450, "shaft": 40}}
        result = _validate(machine)
        assert isinstance(result, dict)

    def test_invalid_config_raises(self):
        machine = {"name": "test", "spindle": {"shaft_od": 300, "flight_od": 100}}
        with pytest.raises(InvalidMachineConfigError):
            _validate(machine)

    def test_result_excludes_none_values(self):
        machine = {"name": "test", "roller": {"diameter": 180, "width": 450, "shaft": 40}}
        result = _validate(machine)
        assert None not in result.values()


class TestImportYaml:
    """Integration tests using tmp files — orchestrator is mocked."""

    def _write_yaml(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test.yaml"
        p.write_text(content, encoding="utf-8")
        return p

    def test_valid_roller_yaml(self, tmp_path):
        yaml_content = "roller:\n  diameter: 180\n  width: 450\n  shaft: 40\n"
        p = self._write_yaml(tmp_path, yaml_content)
        mock_result = {"revision_id": "rev_abc", "score": 0.7, "promoted": False}
        with patch("app.core.orchestrator.EngineeringOrchestrator") as MockOrch:
            instance = MockOrch.return_value
            instance.run_machine_job.return_value = mock_result
            from app.importers.yaml_importer import import_yaml
            result = import_yaml(p)
        assert result["revision_id"] == "rev_abc"

    def test_malformed_yaml_raises(self, tmp_path):
        p = self._write_yaml(tmp_path, "key: [unclosed")
        from app.importers.yaml_importer import import_yaml
        with pytest.raises(InvalidMachineConfigError, match="Malformed YAML"):
            import_yaml(p)

    def test_invalid_schema_raises(self, tmp_path):
        # flight_od < shaft_od — schema violation
        yaml_content = "spindle:\n  shaft_od: 300\n  flight_od: 100\n"
        p = self._write_yaml(tmp_path, yaml_content)
        from app.importers.yaml_importer import import_yaml
        with pytest.raises(InvalidMachineConfigError):
            import_yaml(p)
