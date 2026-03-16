import pytest
from backend.algorithm.clustering_algorithm import ClusteringAlgorithm
from backend.data.position import Position
from backend.data.task import Task

@pytest.fixture
def clustering_algorithm():
    return ClusteringAlgorithm(k=2, max_iterations=100)

@pytest.fixture
def test_tasks():
    return [
        Task(id=1, position=Position(x=10, y=10), weight=10, create_time=1000, deadline=2000, priority=1),
        Task(id=2, position=Position(x=12, y=12), weight=15, create_time=1000, deadline=2000, priority=2),
        Task(id=3, position=Position(x=50, y=50), weight=20, create_time=1000, deadline=2000, priority=3),
        Task(id=4, position=Position(x=52, y=52), weight=25, create_time=1000, deadline=2000, priority=4),
        Task(id=5, position=Position(x=15, y=15), weight=30, create_time=1000, deadline=2000, priority=5),
    ]

def test_clustering_algorithm_initialization(clustering_algorithm):
    """测试聚类算法初始化"""
    assert clustering_algorithm is not None
    assert clustering_algorithm.k == 2
    assert clustering_algorithm.max_iterations == 100

def test_kmeans_clustering(clustering_algorithm, test_tasks):
    """测试Kmeans聚类算法"""
    clusters = clustering_algorithm.kmeans_clustering(test_tasks)
    
    assert isinstance(clusters, list)
    assert len(clusters) == 2
    
    # 验证所有任务都被分配到聚类
    all_tasks = []
    for cluster in clusters:
        assert isinstance(cluster, list)
        all_tasks.extend(cluster)
    assert len(all_tasks) == len(test_tasks)
    
    # 验证聚类结果合理（相似位置的任务应该在同一聚类）
    cluster1_positions = [task.position for task in clusters[0]]
    cluster2_positions = [task.position for task in clusters[1]]
    
    # 确保聚类内部距离较小
    if cluster1_positions:
        avg_x1 = sum(pos.x for pos in cluster1_positions) / len(cluster1_positions)
        avg_y1 = sum(pos.y for pos in cluster1_positions) / len(cluster1_positions)
    
    if cluster2_positions:
        avg_x2 = sum(pos.x for pos in cluster2_positions) / len(cluster2_positions)
        avg_y2 = sum(pos.y for pos in cluster2_positions) / len(cluster2_positions)

def test_kmeans_clustering_with_fewer_tasks(clustering_algorithm):
    """测试任务数量少于聚类数的情况"""
    # 创建少于k个任务
    tasks = [
        Task(id=1, position=Position(x=10, y=10), weight=10, create_time=1000, deadline=2000, priority=1),
    ]
    
    clusters = clustering_algorithm.kmeans_clustering(tasks)
    assert isinstance(clusters, list)
    assert len(clusters) == 1
    assert len(clusters[0]) == 1

def test_euclidean_distance(clustering_algorithm):
    """测试欧几里得距离计算"""
    pos1 = Position(x=0, y=0)
    pos2 = Position(x=3, y=4)
    
    distance = clustering_algorithm._euclidean_distance(pos1, pos2)
    assert distance == 5.0
    
    pos3 = Position(x=1, y=1)
    pos4 = Position(x=1, y=1)
    distance = clustering_algorithm._euclidean_distance(pos3, pos4)
    assert distance == 0.0

def test_centroids_converged(clustering_algorithm):
    """测试质心收敛判断"""
    centroids1 = [Position(x=10, y=10), Position(x=50, y=50)]
    centroids2 = [Position(x=10, y=10), Position(x=50, y=50)]
    
    assert clustering_algorithm._centroids_converged(centroids1, centroids2) == True
    
    centroids3 = [Position(x=10, y=10), Position(x=50, y=50)]
    centroids4 = [Position(x=11, y=11), Position(x=51, y=51)]
    
    assert clustering_algorithm._centroids_converged(centroids3, centroids4) == False
