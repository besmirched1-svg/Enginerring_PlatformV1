# app/core/schemas.py  — Pydantic v2 validated machine configs.
from __future__ import annotations
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, field_validator, model_validator


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


class SpindleConfig(BaseModel):
    shaft_length: int = Field(4000, gt=0)
    shaft_od: int = Field(260, gt=0)
    flight_od: int = Field(600, gt=0)
    flight_pitch: int = Field(400, gt=0)
    flight_thickness: int = Field(25, gt=0)
    flight_turns: int = Field(10, gt=0)
    material: Optional[str] = "en24t"

    @field_validator("flight_od")
    @classmethod
    def flight_od_exceeds_shaft(cls, v: int, info: Any) -> int:
        shaft = (info.data or {}).get("shaft_od")
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

    @field_validator("skid_width")
    @classmethod
    def skid_must_clear_rails(cls, v: int, info: Any) -> int:
        rail_b = (info.data or {}).get("rail_b")
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


def _coerce_frame(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"frame must be a mapping, got {type(value).__name__}")
    industrial_keys = {"rail_length", "rail_a", "rail_b", "skid_width", "cross_a"}
    if industrial_keys & value.keys():
        return SkidFrameConfig(**value).model_dump()
    return LegacyFrameConfig(**value).model_dump()


class MachineConfig(BaseModel):
    name: str = "machine"
    spindle: Optional[SpindleConfig] = None
    drum: Optional[DrumConfig] = None
    compression_rollers: Optional[CompressionRollerConfig] = None
    frame: Optional[Dict[str, Any]] = None
    roller: Optional[RollerConfig] = None
    hopper: Optional[HopperConfig] = None

    model_config = {"extra": "forbid"}

    @field_validator("frame", mode="before")
    @classmethod
    def _validate_frame(cls, v: Any) -> Any:
        return _coerce_frame(v)

    @classmethod
    def from_normalized_dict(cls, data: Dict[str, Any]) -> "MachineConfig":
        cleaned = {k: v for k, v in data.items() if v is not None}
        return cls(**cleaned)
