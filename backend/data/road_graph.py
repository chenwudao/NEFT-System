from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import math
import networkx as nx


@dataclass
class PathResult:
    nodes: List[Any]
    coordinates: List[Tuple[float, float]]
    distance: float


class RoadGraph:
    """基于 NetworkX 路网图的轻量封装，用于路由操作。"""

    def __init__(self, graph: Optional[nx.Graph] = None):
        self.graph: Optional[nx.Graph] = graph

    def set_graph(self, graph: nx.Graph):
        self.graph = graph

    def is_ready(self) -> bool:
        return self.graph is not None and self.graph.number_of_nodes() > 0

    def nearest_node(self, point: Tuple[float, float]):
        if not self.is_ready():
            raise ValueError("Road graph is not initialized")

        x, y = point
        nearest = None
        best = float("inf")

        for node_id, attrs in self.graph.nodes(data=True):
            nx_x = attrs.get("x")
            nx_y = attrs.get("y")
            if nx_x is None or nx_y is None:
                continue
            dist = math.dist((x, y), (float(nx_x), float(nx_y)))
            if dist < best:
                best = dist
                nearest = node_id

        if nearest is None:
            raise ValueError("No nearest node found")
        return nearest

    def shortest_path_nodes(self, start: Tuple[float, float], end: Tuple[float, float]) -> List[Any]:
        if not self.is_ready():
            raise ValueError("Road graph is not initialized")

        start_node = self.nearest_node(start)
        end_node = self.nearest_node(end)
        return nx.shortest_path(self.graph, start_node, end_node, weight="length")

    def shortest_path_length(self, start: Tuple[float, float], end: Tuple[float, float]) -> float:
        if not self.is_ready():
            raise ValueError("Road graph is not initialized")

        start_node = self.nearest_node(start)
        end_node = self.nearest_node(end)
        return float(nx.shortest_path_length(self.graph, start_node, end_node, weight="length"))

    def shortest_path(self, start: Tuple[float, float], end: Tuple[float, float]) -> PathResult:
        nodes = self.shortest_path_nodes(start, end)
        coords: List[Tuple[float, float]] = []
        for node in nodes:
            attrs = self.graph.nodes[node]
            coords.append((float(attrs["x"]), float(attrs["y"])))

        distance = 0.0
        for i in range(len(nodes) - 1):
            edge_data = self.graph.get_edge_data(nodes[i], nodes[i + 1], default={})
            if isinstance(edge_data, dict) and "length" in edge_data:
                distance += float(edge_data["length"])
            elif isinstance(edge_data, dict) and 0 in edge_data and "length" in edge_data[0]:
                distance += float(edge_data[0]["length"])
            else:
                distance += math.dist(coords[i], coords[i + 1])

        return PathResult(nodes=nodes, coordinates=coords, distance=distance)

    def apply_blocked_edges(self, blocked_edges: List[Tuple[Any, Any]]):
        if not self.is_ready():
            return
        for u, v in blocked_edges:
            if self.graph.has_edge(u, v):
                self.graph.remove_edge(u, v)
