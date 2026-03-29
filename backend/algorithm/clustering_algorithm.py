from typing import List
import random
import math
from backend.data.task import Task, Position
from backend.data.path_calculator import PathCalculator

class ClusteringAlgorithm:
    def __init__(self, k: int = 3, max_iterations: int = 100, path_calculator: PathCalculator = None):
        self.k = k
        self.max_iterations = max_iterations
        self.path_calculator = path_calculator

    def kmeans_clustering(self, tasks: List[Task]) -> List[List[Task]]:
        if len(tasks) < self.k:
            return [[task] for task in tasks]

        centroids = self._initialize_centroids(tasks)

        for _ in range(self.max_iterations):
            clusters = self._assign_tasks_to_clusters(tasks, centroids)
            new_centroids = self._update_centroids(clusters)

            if self._centroids_converged(centroids, new_centroids):
                break

            centroids = new_centroids

        return clusters

    def _initialize_centroids(self, tasks: List[Task]) -> List[Position]:
        return [random.choice(tasks).position for _ in range(self.k)]

    def _assign_tasks_to_clusters(self, tasks: List[Task], 
                                  centroids: List[Position]) -> List[List[Task]]:
        clusters = [[] for _ in range(self.k)]

        for task in tasks:
            min_distance = float('inf')
            closest_cluster = 0

            for i, centroid in enumerate(centroids):
                distance = self._distance(task.position, centroid)
                if distance < min_distance:
                    min_distance = distance
                    closest_cluster = i

            clusters[closest_cluster].append(task)

        return clusters

    def _update_centroids(self, clusters: List[List[Task]]) -> List[Position]:
        centroids = []

        for cluster in clusters:
            if cluster:
                avg_x = sum(task.position.x for task in cluster) / len(cluster)
                avg_y = sum(task.position.y for task in cluster) / len(cluster)
                centroids.append(Position(x=avg_x, y=avg_y))
            else:
                centroids.append(Position(x=0, y=0))

        return centroids

    def _centroids_converged(self, old_centroids: List[Position], 
                            new_centroids: List[Position], tolerance: float = 0.001) -> bool:
        for old, new in zip(old_centroids, new_centroids):
            distance = self._distance(old, new)
            if distance > tolerance:
                return False
        return True

    def _distance(self, pos1: Position, pos2: Position) -> float:
        if not self.path_calculator:
            raise RuntimeError("PathCalculator is required for graph-based clustering.")
        return self.path_calculator.calculate_pair_distance((pos1.x, pos1.y), (pos2.x, pos2.y))

    def region_partition(self, tasks: List[Task], num_regions: int = 4) -> List[List[Task]]:
        if len(tasks) == 0:
            return []

        positions = [(task.position.x, task.position.y) for task in tasks]
        min_x = min(pos[0] for pos in positions)
        max_x = max(pos[0] for pos in positions)
        min_y = min(pos[1] for pos in positions)
        max_y = max(pos[1] for pos in positions)

        regions = [[] for _ in range(num_regions)]

        for task in tasks:
            region_index = self._get_region_index(task.position, min_x, max_x, min_y, max_y, num_regions)
            regions[region_index].append(task)

        return regions

    def _get_region_index(self, position: Position, min_x: float, max_x: float,
                         min_y: float, max_y: float, num_regions: int) -> int:
        x_ratio = (position.x - min_x) / (max_x - min_x) if max_x > min_x else 0
        y_ratio = (position.y - min_y) / (max_y - min_y) if max_y > min_y else 0

        grid_size = int(math.sqrt(num_regions))
        x_region = int(x_ratio * grid_size)
        y_region = int(y_ratio * grid_size)

        x_region = min(x_region, grid_size - 1)
        y_region = min(y_region, grid_size - 1)

        return y_region * grid_size + x_region
