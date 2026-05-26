# app/core/schemas.py
#
# Pydantic v1 validation schemas for machine configs.
# Used at every external input boundary:
#   - FastAPI request bodies (app/api/routes.py)
#   - YAML ingestion (app/importers/yaml_importer.py)
#
# Bumping to Pydantic v2 requires a coupled bump of fastapi (>=0.100).
# That migration is intentionally deferred to a separate change.

from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, validator


# ---------------------------------------------------------------------------
# Legacy small-machine schemas
# ---------------------------------------------------------------------------

class RollerConfig(BaseModel):
    diameter: int = Field(180, gt=0)
    width: int = Field(450, gt=0)
    shaft: int = Field(40, gt=0)
    material: Optional[str] = "steel"


class HopperConfig(BaseModel):
    top_width: int = Field(400, gt=0)
    bottom_width: int = Field(120, gt=0)
    height: int = Field(300, gt=0)
    wall: int = Field(4, gt=0)
    material: Optional[str] = "stainless_304"


class LegacyFrameConfig(BaseModel):
    length: int = Field(1200, gt=0)
    width: int = Field(600, gt=0)
    height: int = Field(800, gt=0)
    profile: int = Field(40, gt=0)
    material: Optional[str] = "mild_steel"


# ---------------------------------------------------------------------------
# HTDS-P2 industrial schemas
# ---------------------------------------------------------------------------

class SpindleConfig(BaseModel):
    shaft_length: int = Field(4000, gt=0)
    shaft_od: int = Field(260, gt=0)
    flight_od: int = Field(600, gt=0)
    flight_pitch: int = Field(400, gt=0)
    flight_thickness: int = Field(25, gt=0)
    flight_turns: int = Field(10, gt=0)
    material: Optional[str] = "en24t"

    @validator("flight_od")
    def flight_od_exceeds_shaft(cls, v, values):
        shaft = values.get("shaft_od")
        if shaft is not None and v <= shaft:
            raise ValueError(f"flight_od ({v}) must exceed shaft_od ({shaft})")
        return v


class DrumConfig(BaseModel):
    drum_id: int = Field(1500, gt=0)
    drum_length: int = Field(4000, gt=0)
    wall_thickness: int = Field(8, gt=0)
    perforation_diameter: int = Field(4, ge=0)
    perforation_pitch: int = Field(0, ge=0)
    flat_pattern_width: Optional[int] = Field(4000, gt=0)
    flat_pattern_length: Optional[int] = Field(4712, gt=0)
    perforation_pitch_layout: Optional[int] = Field(12, gt=0)
    perforation_zone_fraction: Optional[float] = Field(0.60, ge=0.0, le=1.0)
    lifter_count: Optional[int] = Field(12, ge=0)
    misc_assembly_kg: Optional[float] = Field(340.0, ge=0.0)
    material: Optional[str] = "stainless_304"


class SkidFrameConfig(BaseModel):
    rail_length: int = Field(5000, gt=0)
    rail_a: int = Field(250, gt=0)
    rail_b: int = Field(150, gt=0)
    rail_t: int = Field(10, gt=0)
    skid_width: int = Field(1800, gt=0)
    cross_a: int = Field(150, gt=0)
    cross_b: int = Field(100, gt=0)
    cross_t: int = Field(8, gt=0)
    cross_count: int = Field(5, gt=0)
    rail_count: Optional[int] = Field(2, gt=0)
    material: Optional[str] = "mild_steel"

    @validator("skid_width")
    def skid_must_clear_rails(cls, v, values):
        rail_b = values.get("rail_b")
        if rail_b is not None and v <= 2 * rail_b:
            raise ValueError(
                f"skid_width ({v}) must exceed 2 * rail_b ({2 * rail_b}) "
                "for cross members to fit between the rails"
            )
        return v


class CompressionRollerConfig(BaseModel):
    diameter: int = Field(200, gt=0)
    width: int = Field(4000, gt=0)
    compression_gap: int = Field(20, ge=0, le=80)
    alignment_tolerance: float = Field(0.0, ge=0.0)
    material: Optional[str] = "hardox_500"


# ---------------------------------------------------------------------------
# Top-level machine config
#
# `frame` accepts either SkidFrameConfig (industrial) or LegacyFrameConfig
# (small machines). We discriminate by which keys the dict carries.
# ---------------------------------------------------------------------------

def _coerce_frame(value: Any) -> Optional[Dict[str, Any]]:
    """Validate frame against industrial then legacy schema; return dict."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"frame must be a mapping, got {type(value).__name__}")

    industrial_keys = {"rail_length", "rail_a", "rail_b", "skid_width", "cross_a"}
    if industrial_keys & value.keys():
        return SkidFrameConfig(**value).dict()
    return LegacyFrameConfig(**value).dict()


class MachineConfig(BaseModel):
    name: str = "machine"

    # Industrial subsystems (HTDS-P2)
    spindle: Optional[SpindleConfig] = None
    drum: Optional[DrumConfig] = None
    compression_rollers: Optional[CompressionRollerConfig] = None

    # Frame is dual-schema; we keep it as a raw dict after validation so the
    # downstream BOM/SCAD generators can dispatch on key presence.
    frame: Optional[Dict[str, Any]] = None

    # Legacy small-machine subsystems
    roller: Optional[RollerConfig] = None
    hopper: Optional[HopperConfig] = None

    class Config:
        extra = "forbid"  # reject unknown top-level keys to catch typos early

    @validator("frame", pre=True)
    def _validate_frame(cls, v):
        return _coerce_frame(v)

    @validator("hopper", "roller", "spindle", "drum", "compression_rollers", always=True)
    def _at_least_one_subsystem(cls, v, values, field):
        # We can't fully enforce "at least one subsystem present" in a per-
        # field validator, so the actual check lives in `root_validator`.
        return v

    @classmethod
    def from_normalized_dict(cls, data: Dict[str, Any]) -> "MachineConfig":
        """
        Convenience constructor: accepts the YAML-normalized shape (which may
        carry explicit ``None`` placeholders for missing subsystems) and
        strips them before validation.
        """
        cleaned = {k: v for k, v in data.items() if v is not None}
        return cls(**cleaned)
