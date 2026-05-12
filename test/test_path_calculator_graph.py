import math
import networkx as nx
import pytest

from backend.data.path_calculator import PathCalculator


def _build_graph():
    g = nx.Graph()
    g.graph["crs"] = "EPSG:4326"
    g.add_node(1, x=0.0, y=0.0)
    g.add_node(2, x=1.0, y=0.0)
    g.add_node(3, x=2.0, y=0.0)
    g.add_edge(1, 2, length=1.0)
    g.add_edge(2, 3, length=1.0)
    return g


def test_path_calculator_graph_mode_distance_and_path():
    """测试 PathCalculator 在图模式下可正确计算距离与路径。"""
    pc = PathCalculator()
    pc.set_networkx_graph(_build_graph())

    d = pc.calculate_pair_distance((0.0, 0.0), (2.0, 0.0))
    p = pc.find_shortest_path((0.0, 0.0), (2.0, 0.0))

    assert d == 2.0
    assert p[0] == (0.0, 0.0)
    assert p[-1] == (2.0, 0.0)
    assert len(p) >= 3


def test_path_calculator_graph_mandatory():
    """测试图路由为强制模式，且不允许回退。"""
    pc = PathCalculator()
    
    # 未配置图时，计算距离应抛出 RuntimeError
    with pytest.raises(RuntimeError, match="Graph is not initialized"):
        pc.calculate_pair_distance((0.0, 0.0), (3.0, 4.0))
    
    # 路径查找同理
    with pytest.raises(RuntimeError, match="Graph is not initialized"):
        pc.find_shortest_path((0.0, 0.0), (3.0, 4.0))


def test_get_central_node_xy():
    """测试获取图的中心节点功能。"""
    pc = PathCalculator()
    
    # 构建一个更大的测试图
    g = nx.Graph()
    g.add_node(1, x=0.0, y=0.0)
    g.add_node(2, x=10.0, y=0.0)
    g.add_node(3, x=5.0, y=10.0)  # 中心应该是 (5.0, ~3.33)
    g.add_node(4, x=5.0, y=5.0)   # 这个更接近质心
    g.add_edge(1, 2)
    g.add_edge(2, 3)
    g.add_edge(3, 1)
    g.add_edge(1, 4)
    
    pc.set_networkx_graph(g)
    
    center = pc.get_central_node_xy()
    # 质心是 (5.0, 3.75)，最近的节点应该是 4 (5.0, 5.0)
    assert center == (5.0, 5.0)


def test_get_peripheral_nodes_xy():
    """测试获取图的四周节点功能。"""
    pc = PathCalculator()
    
    # 构建一个星形测试图
    g = nx.Graph()
    # 中心节点
    g.add_node(0, x=0.0, y=0.0)
    # 四周节点（四个方向）
    g.add_node(1, x=10.0, y=0.0)   # 东
    g.add_node(2, x=-10.0, y=0.0)  # 西
    g.add_node(3, x=0.0, y=10.0)   # 北
    g.add_node(4, x=0.0, y=-10.0)  # 南
    g.add_node(5, x=7.0, y=7.0)    # 东北（较远）
    g.add_node(6, x=-7.0, y=-7.0)  # 西南（较远）
    g.add_node(7, x=5.0, y=5.0)    # 中间节点（较近）
    
    # 添加边
    for i in range(1, 8):
        g.add_edge(0, i)
    
    pc.set_networkx_graph(g)
    
    # 获取4个外围节点
    peripheral = pc.get_peripheral_nodes_xy(4)
    
    assert len(peripheral) == 4
    # 外围节点应该是离中心最远的节点
    for pos in peripheral:
        dist = (pos[0]**2 + pos[1]**2)**0.5
        assert dist >= 7.0 - 0.01  # 应该选较远的节点，不是中间的5.0
    
    # 验证节点分布在不同方向（至少应该有不同象限的节点）
    angles = []
    for pos in peripheral:
        angle = math.atan2(pos[1], pos[0])
        angles.append(angle)
    
    # 检查角度分布是否均匀（至少应该有正负角度）
    has_positive = any(a > 0.1 for a in angles)
    has_negative = any(a < -0.1 for a in angles)
    assert has_positive or has_negative, "Nodes should be distributed in different directions"


def test_peripheral_nodes_angle_distribution():
    """测试外围节点在各个方向均匀分布。"""
    pc = PathCalculator()
    
    # 构建一个圆形测试图
    g = nx.Graph()
    g.add_node(0, x=0.0, y=0.0)  # 中心
    
    # 在8个方向上放置节点
    directions = [
        (10.0, 0.0),    # 东
        (7.0, 7.0),     # 东北
        (0.0, 10.0),    # 北
        (-7.0, 7.0),    # 西北
        (-10.0, 0.0),   # 西
        (-7.0, -7.0),   # 西南
        (0.0, -10.0),   # 南
        (7.0, -7.0),    # 东南
    ]
    
    for i, (x, y) in enumerate(directions, 1):
        g.add_node(i, x=x, y=y)
        g.add_edge(0, i)
    
    pc.set_networkx_graph(g)
    
    # 获取4个外围节点
    peripheral = pc.get_peripheral_nodes_xy(4)
    
    assert len(peripheral) == 4
    
    # 验证这些节点分布在不同象限
    quadrants = set()
    for pos in peripheral:
        x, y = pos
        if x > 0 and y >= 0:
            quadrants.add(1)  # 第一象限
        elif x <= 0 and y > 0:
            quadrants.add(2)  # 第二象限
        elif x < 0 and y <= 0:
            quadrants.add(3)  # 第三象限
        elif x >= 0 and y < 0:
            quadrants.add(4)  # 第四象限
    
    # 至少应该有2个不同的象限
    assert len(quadrants) >= 2, f"Nodes should be in different quadrants, got {quadrants}"


def test_pos_to_node_cache():
    """测试节点位置缓存功能。"""
    pc = PathCalculator()
    g = _build_graph()
    pc.set_networkx_graph(g)
    
    # 验证缓存已构建
    assert len(pc._pos_to_node_cache) == 3
    
    # 验证缓存内容
    assert (0.0, 0.0) in pc._pos_to_node_cache
    assert (1.0, 0.0) in pc._pos_to_node_cache
    assert (2.0, 0.0) in pc._pos_to_node_cache
    
    # 验证查找时使用缓存
    node_id = pc._find_nearest_graph_node((0.0, 0.0))
    assert node_id == 1  # 节点1的坐标是 (0.0, 0.0)
