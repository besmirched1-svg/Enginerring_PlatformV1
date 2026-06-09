# app/research/knowledge_graph.py
# Phase 14 Autonomous Research Agent: knowledge graph.

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import IngestionResult

logger = logging.getLogger("engine.research.knowledge_graph")


@dataclass
class KnowledgeNode:
    node_id: str
    label: str
    node_type: str                      # "document" | "entity" | "parameter" | "value"
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "node_type": self.node_type,
            "attributes": self.attributes,
        }


@dataclass
class KnowledgeEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "weight": round(self.weight, 4),
            "confidence": round(self.confidence, 4),
        }


class KnowledgeGraph:
    """In-memory engineering knowledge graph built from ingested documents.

    Nodes are documents, entities, parameters, and values; edges capture
    relations such as MENTIONS and HAS_VALUE plus extracted causal relations.
    Node ids are deterministic (type-prefixed slug), so repeated ingestion of
    the same entity merges rather than duplicates.
    """

    def __init__(self):
        self.nodes: Dict[str, KnowledgeNode] = {}
        self.edges: List[KnowledgeEdge] = []
        self._edge_keys: set = set()

    @staticmethod
    def _node_id(node_type: str, label: str) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")
        return f"{node_type}:{slug}"

    def add_node(self, label: str, node_type: str, **attributes: Any) -> str:
        node_id = self._node_id(node_type, label)
        existing = self.nodes.get(node_id)
        if existing is None:
            self.nodes[node_id] = KnowledgeNode(
                node_id=node_id, label=label, node_type=node_type,
                attributes=dict(attributes),
            )
        else:
            # merge: accumulate a mention counter, keep latest attributes
            existing.attributes.update(attributes)
            existing.attributes["merged_count"] = existing.attributes.get("merged_count", 1) + 1
        return node_id

    def add_edge(self, source_id: str, target_id: str, relation: str,
                 weight: float = 1.0, confidence: float = 0.5) -> None:
        key = (source_id, target_id, relation)
        if key in self._edge_keys:
            # strengthen an existing edge instead of duplicating
            for e in self.edges:
                if (e.source, e.target, e.relation) == key:
                    e.weight += weight
                    e.confidence = max(e.confidence, confidence)
                    return
        self._edge_keys.add(key)
        self.edges.append(KnowledgeEdge(
            source=source_id, target=target_id, relation=relation,
            weight=weight, confidence=confidence,
        ))

    def add_ingestion(self, result: IngestionResult) -> None:
        """Add the nodes and edges from one document's ingestion result."""
        doc_label = result.title or result.doc_id
        doc_id = self.add_node(doc_label, "document", doc_type=result.doc_type)

        for ent in result.entities:
            ent_id = self.add_node(ent.name, "entity", entity_type=ent.entity_type.value)
            self.add_edge(doc_id, ent_id, "mentions",
                          weight=ent.mentions, confidence=ent.confidence)

        for p in result.parameters:
            param_id = self.add_node(p.name, "parameter")
            unit = f" {p.unit}" if p.unit else ""
            val_id = self.add_node(f"{p.value}{unit}", "value")
            self.add_edge(doc_id, param_id, "reports")
            self.add_edge(param_id, val_id, "has_value")

        for fact in result.facts:
            if fact.predicate in ("mentions", "has_value"):
                continue  # already represented above
            s_id = self.add_node(fact.subject, "entity")
            o_id = self.add_node(fact.obj, "entity")
            self.add_edge(s_id, o_id, fact.predicate, confidence=fact.confidence)

    def neighbors(self, label: str, node_type: str = "entity") -> List[Dict[str, Any]]:
        """Return outgoing relations from a node identified by label."""
        node_id = self._node_id(node_type, label)
        out = []
        for e in self.edges:
            if e.source == node_id:
                tgt = self.nodes.get(e.target)
                out.append({
                    "relation": e.relation,
                    "target": tgt.label if tgt else e.target,
                    "target_type": tgt.node_type if tgt else "",
                    "weight": e.weight,
                    "confidence": e.confidence,
                })
        return out

    def most_connected(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """Entities ranked by total edge degree (in + out)."""
        degree: Dict[str, float] = defaultdict(float)
        for e in self.edges:
            degree[e.source] += e.weight
            degree[e.target] += e.weight
        ranked = sorted(degree.items(), key=lambda kv: kv[1], reverse=True)
        results = []
        for node_id, deg in ranked[:top_n]:
            node = self.nodes.get(node_id)
            if node:
                results.append({
                    "label": node.label,
                    "node_type": node.node_type,
                    "degree": round(deg, 2),
                })
        return results

    def stats(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = defaultdict(int)
        for n in self.nodes.values():
            by_type[n.node_type] += 1
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes_by_type": dict(by_type),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "stats": self.stats(),
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Saved knowledge graph to %s (%d nodes, %d edges)",
                    path, len(self.nodes), len(self.edges))

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        graph = cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for n in data.get("nodes", []):
            node = KnowledgeNode(
                node_id=n["node_id"], label=n["label"],
                node_type=n["node_type"], attributes=n.get("attributes", {}),
            )
            graph.nodes[node.node_id] = node
        for e in data.get("edges", []):
            graph.add_edge(e["source"], e["target"], e["relation"],
                           weight=e.get("weight", 1.0), confidence=e.get("confidence", 0.5))
        return graph
