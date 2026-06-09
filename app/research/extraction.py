# app/research/extraction.py
# Phase 14 Autonomous Research Agent: deterministic text extraction.
#
# Lexicon + regex based, no external NLP dependencies. Operates purely on text
# supplied by the caller (no network access).

from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

from .models import EntityType, ExtractedEntity, ExtractedParameter

logger = logging.getLogger("engine.research.extraction")

# Engineering lexicons. Keys are canonical names; values are match aliases.
MATERIAL_LEXICON: Dict[str, List[str]] = {
    "steel": ["steel"],
    "stainless steel": ["stainless steel", "stainless"],
    "aluminium": ["aluminium", "aluminum"],
    "titanium": ["titanium"],
    "cast iron": ["cast iron"],
    "carbon fibre": ["carbon fibre", "carbon fiber"],
    "bronze": ["bronze"],
    "brass": ["brass"],
    "nylon": ["nylon"],
    "ptfe": ["ptfe", "teflon"],
    "rubber": ["rubber"],
    "polymer": ["polymer", "plastic"],
    "hemp": ["hemp"],
}

COMPONENT_LEXICON: Dict[str, List[str]] = {
    "shaft": ["shaft"],
    "bearing": ["bearing"],
    "roller": ["roller"],
    "gear": ["gear"],
    "frame": ["frame", "chassis"],
    "motor": ["motor"],
    "drum": ["drum"],
    "screen": ["screen", "sieve"],
    "blade": ["blade"],
    "hopper": ["hopper"],
    "conveyor": ["conveyor"],
    "coupling": ["coupling"],
    "seal": ["seal", "gasket"],
    "housing": ["housing", "enclosure"],
    "flange": ["flange"],
    "pulley": ["pulley", "sheave"],
    "rotor": ["rotor"],
}

PROCESS_LEXICON: Dict[str, List[str]] = {
    "milling": ["milling", "mill"],
    "welding": ["welding", "weld"],
    "machining": ["machining", "machined"],
    "casting": ["casting", "cast"],
    "forging": ["forging", "forged"],
    "extrusion": ["extrusion", "extruded"],
    "decortication": ["decortication", "decorticate", "decorticator"],
    "separation": ["separation", "separating"],
    "drying": ["drying", "dried"],
    "grinding": ["grinding", "grind"],
    "threshing": ["threshing", "thresh"],
    "screening": ["screening"],
}

_LEXICONS: List[Tuple[EntityType, Dict[str, List[str]]]] = [
    (EntityType.MATERIAL, MATERIAL_LEXICON),
    (EntityType.COMPONENT, COMPONENT_LEXICON),
    (EntityType.PROCESS, PROCESS_LEXICON),
]

# Recognised units (lower-cased). Order matters: match longer units first.
_UNITS = [
    "kg/hr", "kg/h", "mm/s", "m/s", "rpm", "kwh", "kw", "hp", "mpa", "gpa",
    "bar", "hz", "mm", "cm", "nm", "kg", "rev", "deg", "%", "c", "n", "m", "g",
]
_UNIT_PATTERN = "|".join(re.escape(u) for u in _UNITS)

# number followed by an optional space and a unit. A negative lookahead (not
# \b) bounds the unit, so symbol units like "%" match and "c" does not fire
# inside "cubic".
_PARAM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + _UNIT_PATTERN + r")(?![A-Za-z])",
    re.IGNORECASE,
)

_STOPWORDS = {
    "a", "an", "the", "of", "to", "with", "for", "and", "or", "at", "in", "on",
    "is", "are", "be", "by", "from", "this", "that", "which", "has", "have",
    "approximately", "about", "up", "around", "least", "most", "than",
}


def extract_entities(text: str) -> List[ExtractedEntity]:
    """Find engineering entities (materials, components, processes) in text.

    Counts mentions and assigns a confidence that grows with mention count.
    """
    lowered = text.lower()
    entities: List[ExtractedEntity] = []
    for entity_type, lexicon in _LEXICONS:
        for canonical, aliases in lexicon.items():
            count = 0
            for alias in aliases:
                count += len(re.findall(r"\b" + re.escape(alias) + r"\b", lowered))
            if count > 0:
                entities.append(ExtractedEntity(
                    name=canonical,
                    entity_type=entity_type,
                    mentions=count,
                    confidence=min(0.95, 0.5 + 0.1 * count),
                ))
    entities.sort(key=lambda e: e.mentions, reverse=True)
    return entities


def _parameter_name(prefix: str) -> str:
    """Derive a parameter name from the words preceding a numeric value."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]*", prefix.lower())
    kept = [w for w in words if w not in _STOPWORDS]
    name = " ".join(kept[-3:]) if kept else ""
    return name.strip()


def extract_parameters(text: str, prefix_window: int = 40) -> List[ExtractedParameter]:
    """Extract numeric parameters (value + unit) with an inferred name.

    For each "<number> <unit>" match, the preceding words (up to
    ``prefix_window`` characters) become the parameter name, e.g.
    "wall thickness of 5 mm" -> ("wall thickness", 5.0, "mm").
    """
    params: List[ExtractedParameter] = []
    for m in _PARAM_RE.finditer(text):
        value = float(m.group(1))
        unit = m.group(2).lower()
        start = max(0, m.start() - prefix_window)
        prefix = text[start:m.start()]
        name = _parameter_name(prefix)
        if not name:
            name = "value"
        context = text[start:m.end()].strip()
        params.append(ExtractedParameter(
            name=name, value=value, unit=unit, context=context,
        ))
    return params


# Causal/relational verbs worth capturing as subject-predicate-object facts.
_RELATION_VERBS = [
    "increases", "reduces", "decreases", "improves", "prevents", "requires",
    "enables", "increase", "reduce", "improve", "prevent", "require", "enable",
    "minimises", "minimizes", "maximises", "maximizes", "eliminates",
]
_REL_PATTERN = "|".join(re.escape(v) for v in _RELATION_VERBS)
_RELATION_RE = re.compile(
    r"([A-Za-z][A-Za-z\- ]{2,40}?)\s+(" + _REL_PATTERN + r")\s+([A-Za-z][A-Za-z\- ]{2,40}?)"
    r"(?=[\.,;:]|\s+(?:and|which|that|to)\b|$)",
    re.IGNORECASE,
)


def _clean_phrase(phrase: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]*", phrase.lower())
             if w not in _STOPWORDS]
    return " ".join(words[-4:]).strip()


def extract_relations(text: str) -> List[Tuple[str, str, str]]:
    """Extract (subject, predicate, object) triples from causal statements.

    Matches patterns like "thicker walls reduce vibration" -> ("walls",
    "reduce", "vibration"). Heuristic and conservative: trims to the salient
    trailing words of each phrase and skips fragments that clean to nothing.
    """
    relations: List[Tuple[str, str, str]] = []
    for m in _RELATION_RE.finditer(text):
        subj = _clean_phrase(m.group(1))
        pred = m.group(2).lower()
        obj = _clean_phrase(m.group(3))
        if subj and obj:
            relations.append((subj, pred, obj))
    return relations
