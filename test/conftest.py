import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

@pytest.fixture(autouse=True)
def mock_initialize_routing_graph(monkeypatch):
    """全局跳过所有测试中 DataManager 对番禺数百兆 OSM 的真实读取构造。
    自动注入一个覆盖正负坐标的 Mock 网格图，确保 PathCalculator 有图可用。"""
    import networkx as nx
    from backend.data.data_manager import DataManager

    def mocked_init(self):
        # 创建 21x21 Dense Mock 图 (范围 -1000 到 1000，间距 100.0)
        # 这样测试中的任务位置（如距离150的圆周）都能在图上找到
        G = nx.MultiDiGraph()
        offset = 10  # 中心偏移
        for i in range(21):
            for j in range(21):
                node_id = i * 21 + j
                # 坐标范围：-1000 到 1000
                G.add_node(node_id, x=(i - offset) * 100.0, y=(j - offset) * 100.0)
        for i in range(21):
            for j in range(21):
                u = i * 21 + j
                if i < 20:
                    v = (i + 1) * 21 + j
                    G.add_edge(u, v, 0, length=100.0)
                    G.add_edge(v, u, 0, length=100.0)
                if j < 20:
                    v = i * 21 + (j + 1)
                    G.add_edge(u, v, 0, length=100.0)
                    G.add_edge(v, u, 0, length=100.0)
        
        self.path_calculator.set_networkx_graph(G)
        import logging
        logging.info("Testing Mode: Injected 21x21 Dense Mock Graph (range: -1000 to 1000).")

    monkeypatch.setattr(DataManager, "_initialize_routing_graph_if_enabled", mocked_init)
