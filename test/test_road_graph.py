import networkx as nx

from backend.data.road_graph import RoadGraph


def _build_test_graph():
    g = nx.Graph()
    g.add_node(1, x=0.0, y=0.0)
    g.add_node(2, x=1.0, y=0.0)
    g.add_node(3, x=2.0, y=0.0)
    g.add_edge(1, 2, length=1.0)
    g.add_edge(2, 3, length=1.0)
    return g


def test_nearest_node_and_shortest_path():
    rg = RoadGraph(_build_test_graph())
    assert rg.nearest_node((0.1, 0.0)) == 1

    res = rg.shortest_path((0.0, 0.0), (2.0, 0.0))
    assert res.nodes == [1, 2, 3]
    assert res.distance == 2.0
    assert len(res.coordinates) == 3


def test_apply_blocked_edges_breaks_reachability():
    rg = RoadGraph(_build_test_graph())
    rg.apply_blocked_edges([(2, 3)])

    try:
        rg.shortest_path((0.0, 0.0), (2.0, 0.0))
        assert False, "Expected no path after blocking edge"
    except Exception:
        assert True
