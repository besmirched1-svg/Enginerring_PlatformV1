"""Dependency graph — DAG construction, topological sort, cycle detection."""

import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("engine.runtime.deps")


class DependencyGraph:
    """Directed acyclic graph of service dependencies."""

    def __init__(self, graph: Optional[Dict[str, List[str]]] = None):
        self._graph: Dict[str, List[str]] = dict(graph or {})

    def add_node(self, name: str, dependencies: Optional[List[str]] = None) -> None:
        if name not in self._graph:
            self._graph[name] = []
        if dependencies:
            existing = set(self._graph[name])
            for dep in dependencies:
                if dep not in existing:
                    self._graph[name].append(dep)

    def add_edge(self, node: str, depends_on: str) -> None:
        if node not in self._graph:
            self._graph[node] = []
        if depends_on not in self._graph[node]:
            self._graph[node].append(depends_on)

    @property
    def nodes(self) -> List[str]:
        return list(self._graph.keys())

    def dependencies(self, name: str) -> List[str]:
        return list(self._graph.get(name, []))

    def has_cycle(self) -> bool:
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def _dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for dep in self._graph.get(node, []):
                if dep not in visited:
                    if _dfs(dep):
                        return True
                elif dep in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for node in self._graph:
            if node not in visited:
                if _dfs(node):
                    return True
        return False

    def find_cycle(self) -> Optional[List[str]]:
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        parent: Dict[str, Optional[str]] = {}

        def _dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            for dep in self._graph.get(node, []):
                if dep not in visited:
                    parent[dep] = node
                    result = _dfs(dep)
                    if result:
                        return result
                elif dep in rec_stack:
                    cycle = [dep, node]
                    cur = node
                    while cur != dep:
                        cur = parent.get(cur)
                        if cur is None:
                            break
                        cycle.append(cur)
                    return cycle
            rec_stack.discard(node)
            return None

        for node in self._graph:
            if node not in visited:
                result = _dfs(node)
                if result:
                    return result
        return None

    def topological_sort(self) -> List[str]:
        if self.has_cycle():
            cycle = self.find_cycle()
            raise ValueError(f"Dependency cycle detected: {' -> '.join(cycle or ['unknown'])}")

        visited: Set[str] = set()
        result: List[str] = []

        def _dfs(node: str) -> None:
            visited.add(node)
            for dep in self._graph.get(node, []):
                if dep not in visited:
                    _dfs(dep)
            result.append(node)

        for node in self._graph:
            if node not in visited:
                _dfs(node)

        return result

    def reverse_topological_sort(self) -> List[str]:
        return list(reversed(self.topological_sort()))

    def subgraph(self, nodes: List[str]) -> "DependencyGraph":
        sub = DependencyGraph()
        node_set = set(nodes)
        for n in nodes:
            deps = [d for d in self._graph.get(n, []) if d in node_set]
            sub.add_node(n, deps)
        return sub

    def levels(self) -> List[List[str]]:
        sort = self.topological_sort()
        depth: Dict[str, int] = {}
        for node in sort:
            deps = self._graph.get(node, [])
            if not deps:
                depth[node] = 0
            else:
                depth[node] = max(depth.get(d, 0) for d in deps) + 1
        max_d = max(depth.values()) if depth else 0
        levels: List[List[str]] = [[] for _ in range(max_d + 1)]
        for node, d in depth.items():
            levels[d].append(node)
        return levels

    def to_dict(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in self._graph.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, List[str]]) -> "DependencyGraph":
        return cls(graph=data)
