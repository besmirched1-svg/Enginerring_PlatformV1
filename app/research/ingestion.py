# app/research/ingestion.py
# Phase 14 Autonomous Research Agent: document ingestion orchestration.

from __future__ import annotations

import logging
from typing import Any, List

from .extraction import extract_entities, extract_parameters, extract_relations
from .models import (
    DocumentType,
    IngestionResult,
    KnowledgeFact,
    ResearchDocument,
)

logger = logging.getLogger("engine.research.ingestion")

# Confidence floor applied to facts depending on source type. Patents and
# papers are treated as more authoritative than uncategorised text.
_SOURCE_CONFIDENCE = {
    DocumentType.PATENT: 0.8,
    DocumentType.PAPER: 0.75,
    DocumentType.MANUAL: 0.7,
    DocumentType.DRAWING: 0.7,
    DocumentType.OTHER: 0.5,
}


def ingest_document(doc: ResearchDocument) -> IngestionResult:
    """Extract entities, numeric parameters, and facts from one document.

    Source-agnostic: works only on ``doc.text``. Builds knowledge facts from
    extracted parameters and relational statements, tagged with the document's
    source confidence.
    """
    result = IngestionResult(
        doc_id=doc.doc_id,
        doc_type=doc.doc_type.value,
        title=doc.title,
    )

    if not doc.text or not doc.text.strip():
        result.notes.append("Document has no text; nothing extracted")
        return result

    base_conf = _SOURCE_CONFIDENCE.get(doc.doc_type, 0.5)

    result.entities = extract_entities(doc.text)
    result.parameters = extract_parameters(doc.text)

    facts: List[KnowledgeFact] = []

    # The document mentions each entity.
    label = doc.title or doc.doc_id
    for ent in result.entities:
        facts.append(KnowledgeFact(
            subject=label, predicate="mentions", obj=ent.name,
            source_doc_id=doc.doc_id,
            confidence=min(0.95, base_conf + 0.05 * (ent.mentions - 1)),
        ))

    # Each numeric parameter becomes a measurement fact.
    for p in result.parameters:
        unit = f" {p.unit}" if p.unit else ""
        facts.append(KnowledgeFact(
            subject=p.name, predicate="has_value", obj=f"{p.value}{unit}",
            source_doc_id=doc.doc_id, confidence=base_conf,
        ))

    # Relational statements become subject-predicate-object facts.
    for subj, pred, obj in extract_relations(doc.text):
        facts.append(KnowledgeFact(
            subject=subj, predicate=pred, obj=obj,
            source_doc_id=doc.doc_id, confidence=base_conf,
        ))

    result.facts = facts
    logger.info(
        "Ingested %s '%s': %d entities, %d parameters, %d facts",
        doc.doc_type.value, label, len(result.entities),
        len(result.parameters), len(result.facts),
    )
    return result


def ingest_to_store(doc: ResearchDocument, knowledge_store: Any) -> IngestionResult:
    """Ingest a document and persist its facts to a KnowledgeStore.

    Each extracted fact is stored as a lesson so the Phase 13 reasoning layer
    and the wider platform can draw on externally sourced knowledge.
    """
    result = ingest_document(doc)
    for fact in result.facts:
        knowledge_store.add_lesson({
            "source": "research",
            "doc_id": doc.doc_id,
            "doc_type": doc.doc_type.value,
            **fact.to_dict(),
        })
    logger.info("Persisted %d research facts to knowledge store", len(result.facts))
    return result
