# app/research/__init__.py
# Phase 14 Autonomous Research Agent: learn from external engineering knowledge.

from .agent import ResearchAgent
from .extraction import (
    COMPONENT_LEXICON,
    MATERIAL_LEXICON,
    PROCESS_LEXICON,
    extract_entities,
    extract_parameters,
    extract_relations,
)
from .ingestion import ingest_document, ingest_to_store
from .knowledge_graph import KnowledgeEdge, KnowledgeGraph, KnowledgeNode
from .models import (
    DocumentType,
    EntityType,
    ExtractedEntity,
    ExtractedParameter,
    IngestionResult,
    KnowledgeFact,
    ResearchDocument,
)

__all__ = [
    # models
    "DocumentType",
    "EntityType",
    "ResearchDocument",
    "ExtractedEntity",
    "ExtractedParameter",
    "KnowledgeFact",
    "IngestionResult",
    # extraction
    "extract_entities",
    "extract_parameters",
    "extract_relations",
    "MATERIAL_LEXICON",
    "COMPONENT_LEXICON",
    "PROCESS_LEXICON",
    # ingestion
    "ingest_document",
    "ingest_to_store",
    # knowledge graph
    "KnowledgeGraph",
    "KnowledgeNode",
    "KnowledgeEdge",
    # agent
    "ResearchAgent",
]
