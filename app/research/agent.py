# app/research/agent.py
# Phase 14 Autonomous Research Agent: orchestrator.

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .ingestion import ingest_document, ingest_to_store
from .knowledge_graph import KnowledgeGraph
from .models import IngestionResult, ResearchDocument

logger = logging.getLogger("engine.research.agent")


class ResearchAgent:
    """Ingests external engineering knowledge and maintains a knowledge graph.

    The agent is source-agnostic: documents are supplied as text. It extracts
    entities, parameters, and facts, accumulates them into a knowledge graph,
    and can optionally persist facts to a KnowledgeStore for the reasoning
    layer to consume.
    """

    def __init__(self, knowledge_store: Optional[Any] = None):
        self.graph = KnowledgeGraph()
        self.knowledge_store = knowledge_store
        self.ingested: List[IngestionResult] = []

    def ingest(self, doc: ResearchDocument, persist: bool = False) -> IngestionResult:
        """Ingest one document, update the graph, optionally persist facts."""
        if persist and self.knowledge_store is not None:
            result = ingest_to_store(doc, self.knowledge_store)
        else:
            result = ingest_document(doc)
        self.graph.add_ingestion(result)
        self.ingested.append(result)
        return result

    def ingest_many(
        self, docs: List[ResearchDocument], persist: bool = False
    ) -> List[IngestionResult]:
        return [self.ingest(d, persist=persist) for d in docs]

    def query_entity(self, entity: str) -> Dict[str, Any]:
        """Return what is known about an entity from the graph."""
        return {
            "entity": entity,
            "relations": self.graph.neighbors(entity, node_type="entity"),
        }

    def summary(self) -> Dict[str, Any]:
        """Aggregate view of everything ingested so far."""
        total_entities = sum(len(r.entities) for r in self.ingested)
        total_params = sum(len(r.parameters) for r in self.ingested)
        total_facts = sum(len(r.facts) for r in self.ingested)
        return {
            "documents_ingested": len(self.ingested),
            "total_entities": total_entities,
            "total_parameters": total_params,
            "total_facts": total_facts,
            "graph": self.graph.stats(),
            "most_connected": self.graph.most_connected(top_n=10),
        }
