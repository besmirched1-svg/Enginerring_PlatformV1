# app/knowledge/knowledge_store.py
# Knowledge Memory System for the Autonomous Engineering Intelligence Platform
# Provides append-only NDJSON storage for engineering lessons and experiences
# with reasoning capabilities for pattern learning and self-improvement.

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import statistics


class KnowledgeStore:
    """
    Append-only NDJSON storage for engineering lessons and experiences.
    Provides basic storage and retrieval capabilities.
    """
    
    def __init__(self, storage_path: str = "./knowledge_base"):
        """
        Initialize the knowledge store.
        
        Args:
            storage_path: Directory path for storing knowledge files
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Define file paths for different types of knowledge
        self.lessons_file = self.storage_path / "lessons.ndjson"
        self.experiences_file = self.storage_path / "experiences.ndjson"
        self.patterns_file = self.storage_path / "patterns.ndjson"
        self.design_outcomes_file = self.storage_path / "design_outcomes.ndjson"
        
        # Ensure all files exist
        for file_path in [self.lessons_file, self.experiences_file, 
                         self.patterns_file, self.design_outcomes_file]:
            if not file_path.exists():
                file_path.touch()
    
    def add_lesson(self, lesson: Dict[str, Any]) -> str:
        """
        Add an engineering lesson to the knowledge base.
        
        Args:
            lesson: Dictionary containing lesson information
            
        Returns:
            Unique ID of the stored lesson
        """
        lesson_id = str(uuid.uuid4())
        lesson_entry = {
            "id": lesson_id,
            "type": "lesson",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": lesson
        }
        
        self._append_to_file(self.lessons_file, lesson_entry)
        return lesson_id
    
    def add_experience(self, experience: Dict[str, Any]) -> str:
        """
        Add an engineering experience to the knowledge base.
        
        Args:
            experience: Dictionary containing experience information
            
        Returns:
            Unique ID of the stored experience
        """
        experience_id = str(uuid.uuid4())
        experience_entry = {
            "id": experience_id,
            "type": "experience",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": experience
        }
        
        self._append_to_file(self.experiences_file, experience_entry)
        return experience_id
    
    def add_pattern(self, pattern: Dict[str, Any]) -> str:
        """
        Add a discovered pattern to the knowledge base.
        
        Args:
            pattern: Dictionary containing pattern information
            
        Returns:
            Unique ID of the stored pattern
        """
        pattern_id = str(uuid.uuid4())
        pattern_entry = {
            "id": pattern_id,
            "type": "pattern",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": pattern
        }
        
        self._append_to_file(self.patterns_file, pattern_entry)
        return pattern_id
    
    def add_design_outcome(self, outcome: Dict[str, Any]) -> str:
        """
        Add a design outcome to the knowledge base.
        
        Args:
            outcome: Dictionary containing design outcome information
            
        Returns:
            Unique ID of the stored outcome
        """
        outcome_id = str(uuid.uuid4())
        outcome_entry = {
            "id": outcome_id,
            "type": "design_outcome",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": outcome
        }
        
        self._append_to_file(self.design_outcomes_file, outcome_entry)
        return outcome_id
    
    def get_lessons(self, limit: Optional[int] = None, 
                   filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve lessons from the knowledge base.
        
        Args:
            limit: Maximum number of lessons to return
            filters: Optional filters to apply
            
        Returns:
            List of lesson dictionaries
        """
        return self._read_from_file(self.lessons_file, limit, filters)
    
    def get_experiences(self, limit: Optional[int] = None,
                       filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve experiences from the knowledge base.
        
        Args:
            limit: Maximum number of experiences to return
            filters: Optional filters to apply
            
        Returns:
            List of experience dictionaries
        """
        return self._read_from_file(self.experiences_file, limit, filters)
    
    def get_patterns(self, limit: Optional[int] = None,
                    filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve patterns from the knowledge base.
        
        Args:
            limit: Maximum number of patterns to return
            filters: Optional filters to apply
            
        Returns:
            List of pattern dictionaries
        """
        return self._read_from_file(self.patterns_file, limit, filters)
    
    def get_design_outcomes(self, limit: Optional[int] = None,
                           filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve design outcomes from the knowledge base.
        
        Args:
            limit: Maximum number of outcomes to return
            filters: Optional filters to apply
            
        Returns:
            List of outcome dictionaries
        """
        return self._read_from_file(self.design_outcomes_file, limit, filters)
    
    def _append_to_file(self, file_path: Path, entry: Dict[str, Any]) -> None:
        """
        Append an entry to an NDJSON file.
        
        Args:
            file_path: Path to the NDJSON file
            entry: Dictionary to append as JSON line
        """
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    
    def _read_from_file(self, file_path: Path, 
                       limit: Optional[int] = None,
                       filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Read entries from an NDJSON file with optional filtering and limiting.
        
        Args:
            file_path: Path to the NDJSON file
            limit: Maximum number of entries to return
            filters: Optional filters to apply
            
        Returns:
            List of entry dictionaries
        """
        entries = []
        
        if not file_path.exists():
            return entries
            
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f):
                if limit and line_num >= limit:
                    break
                    
                try:
                    entry = json.loads(line.strip())
                    
                    # Apply filters if provided
                    if filters:
                        match = True
                        for key, value in filters.items():
                            if key in entry.get("data", {}):
                                if entry["data"][key] != value:
                                    match = False
                                    break
                            elif key in entry:
                                if entry[key] != value:
                                    match = False
                                    break
                            else:
                                match = False
                                break
                        
                        if not match:
                            continue
                    
                    entries.append(entry)
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue
        
        return entries


class KnowledgeReasoningEngine:
    """
    Reasoning engine that learns from historical knowledge to improve future designs.
    Provides pattern learning, outcome prediction, and heuristic generation.
    """
    
    def __init__(self, knowledge_store: KnowledgeStore):
        """
        Initialize the reasoning engine with a knowledge store.
        
        Args:
            knowledge_store: KnowledgeStore instance to reason over
        """
        self.store = knowledge_store
        self._pattern_cache = {}
        self._heuristic_cache = {}
    
    def learn_patterns_from_outcomes(self, min_occurrences: int = 3) -> List[Dict[str, Any]]:
        """
        Learn patterns from historical design outcomes.
        
        Args:
            min_occurrences: Minimum number of occurrences to consider a pattern significant
            
        Returns:
            List of discovered patterns
        """
        outcomes = self.store.get_design_outcomes()
        if len(outcomes) < min_occurrences:
            return []
        
        # Group outcomes by similar characteristics
        pattern_groups = defaultdict(list)
        
        for outcome_entry in outcomes:
            outcome = outcome_entry["data"]
            # Create a signature based on key parameters and results
            params = outcome.get("parameters", {})
            score = outcome.get("score", 0)
            
            # Discretize parameters for pattern matching
            param_signature = tuple(
                round(params.get(key, 0), 1) 
                for key in sorted(params.keys())
            )
            
            outcome_category = "success" if score >= 0.7 else "failure"
            pattern_key = (param_signature, outcome_category)
            
            pattern_groups[pattern_key].append({
                "outcome_id": outcome_entry["id"],
                "parameters": params,
                "score": score,
                "timestamp": outcome_entry["timestamp"]
            })
        
        # Identify significant patterns
        patterns = []
        for pattern_key, group in pattern_groups.items():
            if len(group) >= min_occurrences:
                param_signature, outcome_category = pattern_key
                param_names = sorted(group[0]["parameters"].keys()) if group else []
                
                # Calculate statistics for the pattern
                scores = [g["score"] for g in group]
                avg_score = statistics.mean(scores) if scores else 0
                score_stdev = statistics.stdev(scores) if len(scores) > 1 else 0
                
                pattern = {
                    "id": str(uuid.uuid4()),
                    "type": f"outcome_pattern_{outcome_category}",
                    "parameter_signature": dict(zip(param_names, param_signature)),
                    "occurrence_count": len(group),
                    "average_score": avg_score,
                    "score_std_dev": score_stdev,
                    "outcome_category": outcome_category,
                    "confidence": min(0.95, 0.5 + (len(group) - min_occurrences) * 0.1),
                    "discovered_at": datetime.utcnow().isoformat() + "Z",
                    "supporting_evidence": [g["outcome_id"] for g in group[:5]]  # Keep first 5 as evidence
                }
                
                patterns.append(pattern)
                
                # Store the pattern in the knowledge base
                self.store.add_pattern(pattern)
        
        return patterns
    
    def predict_design_outcome(self, parameters: Dict[str, float]) -> Dict[str, Any]:
        """
        Predict the likely outcome of a design based on historical patterns.
        
        Args:
            parameters: Design parameters to evaluate
            
        Returns:
            Prediction including expected score and confidence
        """
        # Learn patterns if cache is empty or stale
        if not self._pattern_cache:
            patterns = self.learn_patterns_from_outcomes()
            self._pattern_cache = {p["id"]: p for p in patterns}
        
        if not self._pattern_cache:
            # No patterns learned yet, return baseline prediction
            return {
                "predicted_score": 0.5,
                "confidence": 0.3,
                "based_on_patterns": [],
                "reasoning": "No historical patterns available for prediction"
            }
        
        # Find matching patterns
        param_signature = tuple(
            round(parameters.get(key, 0), 1) 
            for key in sorted(parameters.keys())
        )
        
        matching_patterns = []
        for pattern in self._pattern_cache.values():
            pattern_signature = tuple(
                round(pattern["parameter_signature"].get(key, 0), 1)
                for key in sorted(parameters.keys())
            )
            
            # Calculate similarity (simple exact match for now)
            if param_signature == pattern_signature:
                matching_patterns.append(pattern)
        
        if not matching_patterns:
            # No exact matches, try to find similar patterns
            # For simplicity, we'll just return a baseline with low confidence
            return {
                "predicted_score": 0.5,
                "confidence": 0.2,
                "based_on_patterns": [],
                "reasoning": "No matching patterns found; using baseline prediction"
            }
        
        # Weight predictions by pattern confidence and occurrence count
        total_weight = 0
        weighted_score = 0
        
        for pattern in matching_patterns:
            weight = pattern["confidence"] * pattern["occurrence_count"]
            total_weight += weight
            weighted_score += pattern["average_score"] * weight
        
        if total_weight > 0:
            predicted_score = weighted_score / total_weight
            confidence = min(0.9, 0.4 + len(matching_patterns) * 0.1)
        else:
            predicted_score = 0.5
            confidence = 0.3
        
        return {
            "predicted_score": predicted_score,
            "confidence": confidence,
            "based_on_patterns": [p["id"] for p in matching_patterns],
            "reasoning": f"Based on {len(matching_patterns)} matching pattern(s)"
        }
    
    def generate_improvement_heuristics(self) -> List[Dict[str, Any]]:
        """
        Generate self-improving design heuristics based on historical data.
        
        Returns:
            List of heuristics for design improvement
        """
        # Learn patterns if cache is empty
        if not self._pattern_cache:
            patterns = self.learn_patterns_from_outcomes()
            self._pattern_cache = {p["id"]: p for p in patterns}
        
        heuristics = []
        
        # Analyze successful vs failed patterns to derive heuristics
        success_patterns = [p for p in self._pattern_cache.values() 
                          if p["outcome_category"] == "success" and p["confidence"] > 0.7]
        failure_patterns = [p for p in self._pattern_cache.values() 
                          if p["outcome_category"] == "failure" and p["confidence"] > 0.7]
        
        if success_patterns:
            # Generate heuristics from successful patterns
            for pattern in success_patterns[:3]:  # Top 3 patterns
                heuristic = {
                    "id": str(uuid.uuid4()),
                    "type": "success_heuristic",
                    "description": f"Consider parameters similar to successful pattern: {pattern['parameter_signature']}",
                    "parameters_to_emulate": pattern["parameter_signature"],
                    "expected_benefit": pattern["average_score"],
                    "confidence": pattern["confidence"],
                    "based_on_pattern_id": pattern["id"],
                    "generated_at": datetime.utcnow().isoformat() + "Z"
                }
                heuristics.append(heuristic)
        
        if failure_patterns:
            # Generate heuristics from failed patterns (what to avoid)
            for pattern in failure_patterns[:3]:  # Top 3 failure patterns
                heuristic = {
                    "id": str(uuid.uuid4()),
                    "type": "failure_avoidance_heuristic",
                    "description": f"Avoid parameters similar to failed pattern: {pattern['parameter_signature']}",
                    "parameters_to_avoid": pattern["parameter_signature"],
                    "expected_benefit": 1.0 - pattern["average_score"],  # Inverse of failure score
                    "confidence": pattern["confidence"],
                    "based_on_pattern_id": pattern["id"],
                    "generated_at": datetime.utcnow().isoformat() + "Z"
                }
                heuristics.append(heuristic)
        
        # Cache heuristics
        self._heuristic_cache = {h["id"]: h for h in heuristics}
        return heuristics
    
    def get_design_recommendations(self, current_parameters: Dict[str, float]) -> Dict[str, Any]:
        """
        Get design improvement recommendations based on learned knowledge.
        
        Args:
            current_parameters: Current design parameters
            
        Returns:
            Recommendations for improving the design
        """
        # Get outcome prediction for current design
        prediction = self.predict_design_outcome(current_parameters)
        
        # Generate heuristics
        heuristics = self.generate_improvement_heuristics()
        
        # Generate specific recommendations
        recommendations = {
            "current_prediction": prediction,
            "suggested_adjustments": [],
            "reasoning": [],
            "confidence_overall": 0.5
        }
        
        if heuristics:
            # Sort heuristics by confidence and expected benefit
            sorted_heuristics = sorted(
                heuristics, 
                key=lambda h: (h["confidence"], h.get("expected_benefit", 0)), 
                reverse=True
            )
            
            # Take top recommendations
            top_heuristics = sorted_heuristics[:3]
            
            for heuristic in top_heuristics:
                if heuristic["type"] == "success_heuristic":
                    recommendations["suggested_adjustments"].append({
                        "action": "consider",
                        "parameters": heuristic["parameters_to_emulate"],
                        "reasoning": heuristic["description"],
                        "confidence": heuristic["confidence"]
                    })
                elif heuristic["type"] == "failure_avoidance_heuristic":
                    recommendations["suggested_adjustments"].append({
                        "action": "avoid",
                        "parameters": heuristic["parameters_to_avoid"],
                        "reasoning": heuristic["description"],
                        "confidence": heuristic["confidence"]
                    })
                
                recommendations["reasoning"].append(heuristic["description"])
            
            # Calculate overall confidence
            if top_heuristics:
                avg_confidence = statistics.mean([h["confidence"] for h in top_heuristics])
                recommendations["confidence_overall"] = min(0.9, 0.3 + avg_confidence * 0.6)
        
        if not recommendations["suggested_adjustments"]:
            recommendations["reasoning"].append("No specific recommendations available; maintaining current parameters")
            recommendations["confidence_overall"] = 0.4
        
        return recommendations


# Convenience functions for easy access
def get_knowledge_store(storage_path: str = "./knowledge_base") -> KnowledgeStore:
    """Get or create a knowledge store instance."""
    return KnowledgeStore(storage_path)


def get_reasoning_engine(knowledge_store: Optional[KnowledgeStore] = None) -> KnowledgeReasoningEngine:
    """Get or create a reasoning engine instance."""
    if knowledge_store is None:
        knowledge_store = get_knowledge_store()
    return KnowledgeReasoningEngine(knowledge_store)