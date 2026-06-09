"""Tests for Autonomous Research Agent package (Phase 14)."""

import os
import tempfile

import pytest

from app.research import (
    DocumentType,
    EntityType,
    ResearchDocument,
    ExtractedEntity,
    ExtractedParameter,
    KnowledgeFact,
    IngestionResult,
    extract_entities,
    extract_parameters,
    extract_relations,
    ingest_document,
    ingest_to_store,
    KnowledgeGraph,
    ResearchAgent,
)


# ===================================================================
# Fixtures
# ===================================================================

PATENT_TEXT = (
    "A hemp decorticator comprising a stainless steel roller and a hardened "
    "steel shaft. The roller rotates at 1500 rpm with a wall thickness of 5 mm. "
    "Thicker walls reduce vibration and improve durability. The drum has a "
    "diameter of 300 mm and the bearing supports a load of 2000 n."
)

PAPER_TEXT = (
    "This study evaluates aluminium frames for conveyor systems. The frame mass "
    "was reduced to 45 kg. Increased roller radius improves throughput. The "
    "separation process achieved a yield of 88 %."
)


@pytest.fixture
def patent_doc():
    return ResearchDocument(
        title="Hemp Decorticator Patent",
        doc_type=DocumentType.PATENT,
        text=PATENT_TEXT,
        source="US1234567",
        year=2019,
    )


@pytest.fixture
def paper_doc():
    return ResearchDocument(
        title="Conveyor Frame Study",
        doc_type=DocumentType.PAPER,
        text=PAPER_TEXT,
        authors=["A. Engineer"],
        year=2021,
    )


# ===================================================================
# Document model
# ===================================================================

class TestResearchDocument:
    def test_auto_id(self):
        d = ResearchDocument(title="x", text="y")
        assert d.doc_id
        assert d.doc_type == DocumentType.OTHER

    def test_string_doc_type_coerced(self):
        d = ResearchDocument(title="x", doc_type="patent", text="y")
        assert d.doc_type == DocumentType.PATENT

    def test_to_dict(self, patent_doc):
        d = patent_doc.to_dict()
        assert d["doc_type"] == "patent"
        assert d["doc_id"]


# ===================================================================
# Entity extraction
# ===================================================================

class TestEntityExtraction:
    def test_materials(self):
        ents = extract_entities(PATENT_TEXT)
        names = {e.name for e in ents if e.entity_type == EntityType.MATERIAL}
        assert "stainless steel" in names
        assert "steel" in names

    def test_components(self):
        ents = extract_entities(PATENT_TEXT)
        names = {e.name for e in ents if e.entity_type == EntityType.COMPONENT}
        assert {"roller", "shaft", "drum", "bearing"}.issubset(names)

    def test_processes(self):
        ents = extract_entities(PATENT_TEXT)
        names = {e.name for e in ents if e.entity_type == EntityType.PROCESS}
        assert "decortication" in names

    def test_mentions_counted(self):
        ents = extract_entities(PATENT_TEXT)
        roller = next(e for e in ents if e.name == "roller")
        assert roller.mentions >= 2
        assert roller.confidence > 0.5

    def test_sorted_by_mentions(self):
        ents = extract_entities(PATENT_TEXT)
        counts = [e.mentions for e in ents]
        assert counts == sorted(counts, reverse=True)

    def test_no_entities(self):
        assert extract_entities("the quick brown fox") == []


# ===================================================================
# Parameter extraction
# ===================================================================

class TestParameterExtraction:
    def test_extracts_value_unit(self):
        params = extract_parameters(PATENT_TEXT)
        units = {p.unit for p in params}
        assert "rpm" in units
        assert "mm" in units
        assert "n" in units

    def test_named_parameter(self):
        params = extract_parameters("the wall thickness of 5 mm is used")
        p = params[0]
        assert "thickness" in p.name
        assert p.value == 5.0
        assert p.unit == "mm"

    def test_percent(self):
        params = extract_parameters("a yield of 88 %")
        assert params[0].value == 88.0
        assert params[0].unit == "%"

    def test_compound_unit(self):
        params = extract_parameters("throughput of 500 kg/hr")
        assert params[0].unit == "kg/hr"
        assert params[0].value == 500.0

    def test_no_parameters(self):
        assert extract_parameters("no numbers here") == []


# ===================================================================
# Relation extraction
# ===================================================================

class TestRelationExtraction:
    def test_extracts_relation(self):
        rels = extract_relations("Thicker walls reduce vibration.")
        assert any(pred == "reduce" and "vibration" in obj for _, pred, obj in rels)

    def test_improves_relation(self):
        rels = extract_relations("Increased roller radius improves throughput.")
        assert any(pred == "improves" for _, pred, _ in rels)

    def test_no_relations(self):
        assert extract_relations("A static description with no causal verbs.") == []


# ===================================================================
# Ingestion
# ===================================================================

class TestIngestion:
    def test_ingest_patent(self, patent_doc):
        result = ingest_document(patent_doc)
        assert isinstance(result, IngestionResult)
        assert result.entities
        assert result.parameters
        assert result.facts
        assert result.doc_type == "patent"

    def test_mentions_facts(self, patent_doc):
        result = ingest_document(patent_doc)
        mentions = [f for f in result.facts if f.predicate == "mentions"]
        assert mentions
        assert all(f.source_doc_id == patent_doc.doc_id for f in mentions)

    def test_value_facts(self, patent_doc):
        result = ingest_document(patent_doc)
        values = [f for f in result.facts if f.predicate == "has_value"]
        assert values

    def test_patent_higher_confidence_than_other(self):
        patent = ingest_document(ResearchDocument(doc_type=DocumentType.PATENT, text="a steel shaft", title="p"))
        other = ingest_document(ResearchDocument(doc_type=DocumentType.OTHER, text="a steel shaft", title="o"))
        pc = next(f.confidence for f in patent.facts if f.predicate == "mentions")
        oc = next(f.confidence for f in other.facts if f.predicate == "mentions")
        assert pc > oc

    def test_empty_text(self):
        result = ingest_document(ResearchDocument(title="empty", text=""))
        assert result.facts == []
        assert result.notes

    def test_to_dict(self, patent_doc):
        d = ingest_document(patent_doc).to_dict()
        assert d["entity_count"] > 0
        assert "facts" in d

    def test_ingest_to_store(self, patent_doc):
        from app.knowledge.knowledge_store import KnowledgeStore
        with tempfile.TemporaryDirectory() as d:
            store = KnowledgeStore(storage_path=d)
            result = ingest_to_store(patent_doc, store)
            lessons = store.get_lessons()
            assert len(lessons) == len(result.facts)
            assert lessons[0]["data"]["source"] == "research"


# ===================================================================
# Knowledge graph
# ===================================================================

class TestKnowledgeGraph:
    def test_build_from_ingestion(self, patent_doc):
        g = KnowledgeGraph()
        g.add_ingestion(ingest_document(patent_doc))
        stats = g.stats()
        assert stats["node_count"] > 0
        assert stats["edge_count"] > 0
        assert "document" in stats["nodes_by_type"]
        assert "entity" in stats["nodes_by_type"]

    def test_node_merge_on_repeat(self, patent_doc):
        g = KnowledgeGraph()
        g.add_ingestion(ingest_document(patent_doc))
        before = g.stats()["node_count"]
        # ingest the same document again; entity nodes should merge, not double
        g.add_ingestion(ingest_document(patent_doc))
        after = g.stats()["node_count"]
        # document label identical -> same id; entities identical -> merge
        assert after == before

    def test_edge_strengthen_on_repeat(self, patent_doc):
        g = KnowledgeGraph()
        g.add_ingestion(ingest_document(patent_doc))
        e_before = g.stats()["edge_count"]
        g.add_ingestion(ingest_document(patent_doc))
        assert g.stats()["edge_count"] == e_before

    def test_neighbors(self, patent_doc):
        g = KnowledgeGraph()
        g.add_ingestion(ingest_document(patent_doc))
        rel = g.neighbors("thicker walls", node_type="entity")
        # "thicker walls reduce vibration" -> thicker walls --reduce--> vibration
        assert any(r["relation"] == "reduce" for r in rel)

    def test_most_connected(self, patent_doc):
        g = KnowledgeGraph()
        g.add_ingestion(ingest_document(patent_doc))
        top = g.most_connected(top_n=5)
        assert top
        assert "degree" in top[0]

    def test_save_load_roundtrip(self, patent_doc):
        g = KnowledgeGraph()
        g.add_ingestion(ingest_document(patent_doc))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "graph.json")
            g.save(path)
            g2 = KnowledgeGraph.load(path)
            assert g2.stats()["node_count"] == g.stats()["node_count"]
            assert g2.stats()["edge_count"] == g.stats()["edge_count"]


# ===================================================================
# Research agent
# ===================================================================

class TestResearchAgent:
    def test_ingest_many(self, patent_doc, paper_doc):
        agent = ResearchAgent()
        results = agent.ingest_many([patent_doc, paper_doc])
        assert len(results) == 2
        summary = agent.summary()
        assert summary["documents_ingested"] == 2
        assert summary["total_facts"] > 0

    def test_query_entity(self, patent_doc):
        agent = ResearchAgent()
        agent.ingest(patent_doc)
        info = agent.query_entity("thicker walls")
        assert info["entity"] == "thicker walls"
        assert any(r["relation"] == "reduce" for r in info["relations"])

    def test_persist_to_store(self, patent_doc):
        from app.knowledge.knowledge_store import KnowledgeStore
        with tempfile.TemporaryDirectory() as d:
            store = KnowledgeStore(storage_path=d)
            agent = ResearchAgent(knowledge_store=store)
            agent.ingest(patent_doc, persist=True)
            assert len(store.get_lessons()) > 0

    def test_summary_structure(self, patent_doc, paper_doc):
        agent = ResearchAgent()
        agent.ingest_many([patent_doc, paper_doc])
        summary = agent.summary()
        assert set(summary.keys()) == {
            "documents_ingested", "total_entities", "total_parameters",
            "total_facts", "graph", "most_connected",
        }


# ===================================================================
# API
# ===================================================================

class TestResearchAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_ingest_endpoint(self, client):
        r = client.post("/api/research/ingest", json={
            "title": "Test Patent", "doc_type": "patent", "text": PATENT_TEXT,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["result"]["entity_count"] > 0
        assert body["result"]["fact_count"] > 0

    def test_graph_endpoint(self, client):
        r = client.post("/api/research/graph", json={
            "documents": [
                {"title": "P", "doc_type": "patent", "text": PATENT_TEXT},
                {"title": "S", "doc_type": "paper", "text": PAPER_TEXT},
            ]
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["summary"]["documents_ingested"] == 2
        assert body["graph"]["stats"]["node_count"] > 0

    def test_invalid_doc_type(self, client):
        r = client.post("/api/research/ingest", json={
            "title": "Bad", "doc_type": "not_a_type", "text": "steel shaft",
        })
        assert r.status_code == 400

    def test_empty_text_ok(self, client):
        r = client.post("/api/research/ingest", json={"title": "empty", "text": ""})
        assert r.status_code == 200
        assert r.json()["result"]["fact_count"] == 0
