# app/research/models.py
# Phase 14 Autonomous Research Agent: shared dataclasses.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DocumentType(str, Enum):
    PATENT = "patent"
    PAPER = "paper"
    MANUAL = "manual"
    DRAWING = "drawing"
    OTHER = "other"


class EntityType(str, Enum):
    MATERIAL = "material"
    COMPONENT = "component"
    PROCESS = "process"
    PARAMETER = "parameter"
    METRIC = "metric"


@dataclass
class ResearchDocument:
    """An external knowledge source provided as text (no network fetch).

    Callers supply the already-extracted text; this keeps ingestion
    deterministic, testable, and free of live-scraping concerns.
    """
    title: str = ""
    doc_type: DocumentType = DocumentType.OTHER
    text: str = ""
    source: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    doc_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.doc_id:
            self.doc_id = uuid.uuid4().hex[:12]
        if isinstance(self.doc_type, str):
            self.doc_type = DocumentType(self.doc_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type.value,
            "source": self.source,
            "authors": self.authors,
            "year": self.year,
            "metadata": self.metadata,
        }


@dataclass
class ExtractedEntity:
    """A named engineering entity mentioned in a document."""
    name: str
    entity_type: EntityType
    mentions: int = 1
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "entity_type": self.entity_type.value,
            "mentions": self.mentions,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class ExtractedParameter:
    """A numeric parameter with a value and unit found in text."""
    name: str
    value: float
    unit: str = ""
    context: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "context": self.context,
        }


@dataclass
class KnowledgeFact:
    """A subject-predicate-object triple extracted from a document."""
    subject: str
    predicate: str
    obj: str
    source_doc_id: str = ""
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.obj,
            "source_doc_id": self.source_doc_id,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class IngestionResult:
    """Everything extracted from a single document."""
    doc_id: str = ""
    doc_type: str = ""
    title: str = ""
    entities: List[ExtractedEntity] = field(default_factory=list)
    parameters: List[ExtractedParameter] = field(default_factory=list)
    facts: List[KnowledgeFact] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "title": self.title,
            "entities": [e.to_dict() for e in self.entities],
            "parameters": [p.to_dict() for p in self.parameters],
            "facts": [f.to_dict() for f in self.facts],
            "entity_count": len(self.entities),
            "parameter_count": len(self.parameters),
            "fact_count": len(self.facts),
            "notes": self.notes,
        }
