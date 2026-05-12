#!/usr/bin/env python3
"""
生成并可视化 OSM 路网图
======================

用法:
    python scripts/generate_graph.py --output graphs/osm_graph.png
    python scripts/generate_graph.py --output graphs/osm_graph.png --place "Panyu District, Guangzhou"
    python scripts/generate_graph.py --export-json graphs/osm_graph.json

该脚本支持：
1. 下载 OSM 真实路网
2. 可视化图结构
3. 导出统计信息（节点、边、坐标）
4. 导出 JSON 供前端使用
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, Optional
import logging
import math

# 将项目根目录加入搜索路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class GraphGenerator:
    """生成并管理路网图。"""

    def __init__(self):
        self.graph = None
        self.graph_wgs84 = None
        self.graph_type = None
        self.stats = {}

    @staticmethod
    def _highway_as_text(highway_value) -> str:
        """统一 highway 字段格式为字符串。"""
        if isinstance(highway_value, list):
            return str(highway_value[0]) if highway_value else "unknown"
        return str(highway_value) if highway_value is not None else "unknown"

    @staticmethod
    def _wgs84_to_gcj02(lon: float, lat: float) -> tuple:
        """WGS84 转 GCJ-02（中国境内）。"""
        # 中国境外不偏移
        if lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271:
            return lon, lat

        a = 6378245.0
        ee = 0.00669342162296594323

        def transform_lat(x, y):
            ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
            ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
            ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
            ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
            return ret

        def transform_lon(x, y):
            ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
            ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
            ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
            ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
            return ret

        dlat = transform_lat(lon - 105.0, lat - 35.0)
        dlon = transform_lon(lon - 105.0, lat - 35.0)
        radlat = lat / 180.0 * math.pi
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        return lon + dlon, lat + dlat

    def create_osm_graph(self, place_name: str = None, network_type: str = "drive", 
                          main_roads_only: bool = False):
        """根据行政区边界下载并创建 OSM 路网图。
        
        Args:
            place_name: 地区名称
            network_type: 路网类型
            main_roads_only: 是否只保留主干路（高速、快速路、主干道）
        """
        try:
            import osmnx as ox
            import networkx as nx
        except ImportError:
            logger.error("未安装 osmnx。请先执行: pip install osmnx")
            sys.exit(1)
        
        if place_name is None:
            place_name = "番禺区, 广州市, 广东省, 中国"
        
        logger.info(f"正在按行政区边界获取 '{place_name}' 的 OSM 路网（network_type={network_type}）...")
        if main_roads_only:
            logger.info("【主干路模式】仅保留高速公路、快速路、主干道")
        logger.info("该步骤可能耗时 30-90 秒...")
        
        try:
            ox.settings.use_cache = True

            # 先解析行政边界，再按 polygon 抓取，避免地名歧义
            gdf = ox.geocode_to_gdf(place_name)
            if gdf.empty:
                raise RuntimeError(f"无法解析行政区边界: {place_name}")

            # 选面积最大的面作为目标区域（处理多面要素场景）
            gdf_metric = gdf.to_crs("EPSG:3857").copy()
            gdf_metric["_area"] = gdf_metric.geometry.area
            largest_idx = gdf_metric["_area"].idxmax()
            polygon = gdf.loc[largest_idx].geometry

            # 主干路类型定义
            if main_roads_only:
                # 只保留高等级道路
                custom_filter = '["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"]'
                G = ox.graph_from_polygon(
                    polygon,
                    network_type=network_type,
                    simplify=True,
                    retain_all=False,  # 只保留符合条件的边
                    truncate_by_edge=True,
                    custom_filter=custom_filter
                )
            else:
                G = ox.graph_from_polygon(
                    polygon,
                    network_type=network_type,
                    simplify=True,
                    retain_all=True,
                    truncate_by_edge=True
                )

            # 仅保留最大弱连通分量，得到可分析的主路网拓扑
            if G.number_of_nodes() > 0:
                largest_wcc = max(nx.weakly_connected_components(G), key=len)
                G = G.subgraph(largest_wcc).copy()

            self.graph_wgs84 = G

            # 投影到 UTM 坐标，便于距离分析与绘图
            G = ox.project_graph(G)
            
            self.graph = G
            self.graph_type = "OSM_MainRoads" if main_roads_only else "OSM"
            self._compute_stats()
            
            reduction_info = "（主干路精简版）" if main_roads_only else ""
            logger.info(f"✓ OSM 路网下载完成{reduction_info}：{self.stats['num_nodes']} 个节点，{self.stats['num_edges']} 条边")
            return G
        except Exception as e:
            logger.error(f"下载 OSM 路网失败: {e}")
            sys.exit(1)

    def _compute_stats(self):
        """计算图统计信息。"""
        if self.graph is None:
            return
        
        # 提取节点坐标
        coords_x = []
        coords_y = []
        for node, attrs in self.graph.nodes(data=True):
            x = attrs.get("x")
            y = attrs.get("y")
            if x is not None and y is not None:
                coords_x.append(float(x))
                coords_y.append(float(y))
        
        # 计算边长度统计
        edge_lengths = []
        for u, v, attrs in self.graph.edges(data=True):
            length = attrs.get("length", 0)
            if length:
                edge_lengths.append(float(length))
        
        self.stats = {
            "type": self.graph_type,
            "num_nodes": self.graph.number_of_nodes(),
            "num_edges": self.graph.number_of_edges(),
            "coord_x_min": min(coords_x) if coords_x else 0,
            "coord_x_max": max(coords_x) if coords_x else 0,
            "coord_y_min": min(coords_y) if coords_y else 0,
            "coord_y_max": max(coords_y) if coords_y else 0,
            "coord_x_range": (max(coords_x) - min(coords_x)) if coords_x else 0,
            "coord_y_range": (max(coords_y) - min(coords_y)) if coords_y else 0,
            "edge_length_min": min(edge_lengths) if edge_lengths else 0,
            "edge_length_max": max(edge_lengths) if edge_lengths else 0,
            "edge_length_avg": sum(edge_lengths) / len(edge_lengths) if edge_lengths else 0,
        }
        
        logger.info(f"图统计信息:\n{json.dumps(self.stats, indent=2)}")

    def visualize_for_backend_analysis(self, output_path: Optional[str] = None, figsize: tuple = (14, 10)):
        """生成更适合后端算法分析的综合拓扑图。"""
        if self.graph is None:
            logger.error("当前没有可视化图，请先生成图。")
            return

        try:
            import matplotlib.pyplot as plt
            import networkx as nx
        except ImportError:
            logger.error("未安装 matplotlib 或 networkx")
            return

        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        logger.info("正在生成后端分析版拓扑图...")
        fig, ax = plt.subplots(figsize=figsize)

        pos = {
            node: (float(attrs.get("x", 0.0)), float(attrs.get("y", 0.0)))
            for node, attrs in self.graph.nodes(data=True)
        }

        # 先画全量路网骨架
        nx.draw_networkx_edges(
            self.graph,
            pos,
            width=0.25,
            alpha=0.35,
            edge_color="#6b7280",
            arrows=False,
            ax=ax
        )

        # 再叠加主干路层，突出算法分析常用的高等级道路
        highway_main = {"motorway", "trunk", "primary", "secondary", "tertiary"}
        main_edges = []
        for u, v, data in self.graph.edges(data=True):
            h = self._highway_as_text(data.get("highway"))
            if h in highway_main:
                main_edges.append((u, v))

        if main_edges:
            nx.draw_networkx_edges(
                self.graph,
                pos,
                edgelist=main_edges,
                width=0.8,
                alpha=0.85,
                edge_color="#ef4444",
                arrows=False,
                ax=ax
            )

        ax.set_title(
            f"番禺区 OSM 交通网络拓扑（后端分析版）\n"
            f"节点: {self.stats['num_nodes']}  边: {self.stats['num_edges']}  主干路边: {len(main_edges)}"
        )
        ax.set_xlabel(f"X: [{self.stats['coord_x_min']:.0f}, {self.stats['coord_x_max']:.0f}]")
        ax.set_ylabel(f"Y: [{self.stats['coord_y_min']:.0f}, {self.stats['coord_y_max']:.0f}]")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.2)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=180, bbox_inches='tight')
            logger.info(f"✓ 后端分析图已保存到: {output_path}")
        else:
            plt.show()

        plt.close()

    def visualize(self, output_path: Optional[str] = None, figsize: tuple = (12, 10)):
        """可视化图结构。"""
        if self.graph is None:
            logger.error("当前没有可视化图，请先生成图。")
            return
        
        try:
            import matplotlib.pyplot as plt
            import networkx as nx
        except ImportError:
            logger.error("未安装 matplotlib 或 networkx")
            return

        # 尝试设置中文字体，减少中文标题缺字告警
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        
        logger.info(f"正在可视化 {self.graph_type} 图...")
        
        # 创建画布
        fig, ax = plt.subplots(figsize=figsize)
        
        # 提取节点位置
        pos = {}
        for node, attrs in self.graph.nodes(data=True):
            x = attrs.get("x", 0)
            y = attrs.get("y", 0)
            pos[node] = (float(x), float(y))
        
        # 绘制图结构（大图自动简化渲染，避免标签遮挡）
        node_count = self.graph.number_of_nodes()
        if node_count > 500:
            # 大图使用“拓扑视图”：不画节点，仅画道路连线
            nx.draw_networkx_edges(self.graph, pos, width=0.35, alpha=0.55, edge_color="#4b5563", arrows=False, ax=ax)
            logger.info("节点数量较大（%s），已切换为拓扑视图（仅道路连线）", node_count)
        else:
            nx.draw_networkx_nodes(self.graph, pos, node_size=100, node_color='lightblue', ax=ax)
            nx.draw_networkx_edges(self.graph, pos, width=0.5, alpha=0.5, arrows=False, ax=ax)
            nx.draw_networkx_labels(self.graph, pos, font_size=6, ax=ax)
        
        # 标题与坐标轴标签
        ax.set_title(f"{self.graph_type} 路网图\n节点: {self.stats['num_nodes']}，边: {self.stats['num_edges']}")
        ax.set_xlabel(f"X: [{self.stats['coord_x_min']:.0f}, {self.stats['coord_x_max']:.0f}]")
        ax.set_ylabel(f"Y: [{self.stats['coord_y_min']:.0f}, {self.stats['coord_y_max']:.0f}]")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.3)
        
        # 保存或显示
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            logger.info(f"✓ 图可视化已保存到: {output_path}")
        else:
            plt.show()
        
        plt.close()

    def export_json(self, output_path: str):
        """将图导出为前端可用的 JSON。"""
        if self.graph is None:
            logger.error("当前没有可导出的图")
            return
        
        # 组装节点数据
        nodes = []
        for node, attrs in self.graph.nodes(data=True):
            nodes.append({
                "id": int(node),
                "x": float(attrs.get("x", 0)),
                "y": float(attrs.get("y", 0)),
                "name": attrs.get("name", f"node_{node}")
            })
        
        # 组装边数据
        edges = []
        seen = set()
        for u, v, attrs in self.graph.edges(data=True):
            edge_key = tuple(sorted([u, v]))
            if edge_key not in seen:
                edges.append({
                    "from": int(u),
                    "to": int(v),
                    "length": float(attrs.get("length", 0)),
                    "name": f"{u}-{v}"
                })
                seen.add(edge_key)
        
        # 写出 JSON
        export_data = {
            "metadata": {
                "type": self.graph_type,
                "num_nodes": self.stats['num_nodes'],
                "num_edges": self.stats['num_edges'],
                "bounds": {
                    "x_min": self.stats['coord_x_min'],
                    "x_max": self.stats['coord_x_max'],
                    "y_min": self.stats['coord_y_min'],
                    "y_max": self.stats['coord_y_max'],
                }
            },
            "nodes": nodes,
            "edges": edges
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"✓ 图已导出为 JSON: {output_path}")

    def export_stats_txt(self, output_path: str):
        """将统计信息导出为文本文件。"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write(f"{self.graph_type} 路网分析报告\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("基础统计\n")
            f.write("-" * 60 + "\n")
            f.write(f"图类型:               {self.stats['type']}\n")
            f.write(f"节点数量:             {self.stats['num_nodes']}\n")
            f.write(f"边数量:               {self.stats['num_edges']}\n\n")
            
            f.write("坐标范围\n")
            f.write("-" * 60 + "\n")
            f.write(f"X 范围: [{self.stats['coord_x_min']:.2f}, {self.stats['coord_x_max']:.2f}] (跨度: {self.stats['coord_x_range']:.2f})\n")
            f.write(f"Y 范围: [{self.stats['coord_y_min']:.2f}, {self.stats['coord_y_max']:.2f}] (跨度: {self.stats['coord_y_range']:.2f})\n\n")
            
            f.write("边长度统计\n")
            f.write("-" * 60 + "\n")
            f.write(f"最小长度:             {self.stats['edge_length_min']:.2f}\n")
            f.write(f"最大长度:             {self.stats['edge_length_max']:.2f}\n")
            f.write(f"平均长度:             {self.stats['edge_length_avg']:.2f}\n\n")
            
            f.write("测试建议\n")
            f.write("-" * 60 + "\n")
            f.write("✓ 适用: 生产验证、性能基准测试\n")
            f.write("✓ 更贴近真实: 拓扑复杂、距离真实\n")
            f.write("  建议: 用于最终性能报告\n")
        
        logger.info(f"✓ 统计信息已导出到: {output_path}")

    def export_pickle(self, output_path: str):
        """导出图为 pickle 文件，供后端直接加载使用。"""
        if self.graph is None:
            logger.error("当前没有可导出的图")
            return
        
        import pickle
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 保存图和元数据
        export_data = {
            "graph": self.graph,
            "graph_wgs84": self.graph_wgs84,
            "graph_type": self.graph_type,
            "stats": self.stats
        }
        
        with open(output_path, 'wb') as f:
            pickle.dump(export_data, f)
        
        logger.info(f"✓ 图已导出为 pickle: {output_path}")

    def export_geojson(self, output_path: str, coord_system: str = "wgs84"):
        """导出线要素 GeoJSON，供前端地图/Canvas 叠加。"""
        if self.graph_wgs84 is None:
            logger.error("当前没有可导出的 WGS84 图")
            return

        features = []
        for u, v, data in self.graph_wgs84.edges(data=True):
            u_attr = self.graph_wgs84.nodes[u]
            v_attr = self.graph_wgs84.nodes[v]
            lon1, lat1 = float(u_attr.get("x", 0.0)), float(u_attr.get("y", 0.0))
            lon2, lat2 = float(v_attr.get("x", 0.0)), float(v_attr.get("y", 0.0))

            if coord_system.lower() == "gcj02":
                lon1, lat1 = self._wgs84_to_gcj02(lon1, lat1)
                lon2, lat2 = self._wgs84_to_gcj02(lon2, lat2)

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon1, lat1], [lon2, lat2]]
                },
                "properties": {
                    "u": int(u) if isinstance(u, int) else str(u),
                    "v": int(v) if isinstance(v, int) else str(v),
                    "length": float(data.get("length", 0.0)),
                    "highway": self._highway_as_text(data.get("highway")),
                    "coord_system": coord_system.lower()
                }
            })

        out = {
            "type": "FeatureCollection",
            "name": "panyu_osm_roads",
            "features": features
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        logger.info("✓ GeoJSON 已导出到: %s（坐标系: %s）", output_path, coord_system)


def main():
    parser = argparse.ArgumentParser(
                description="为 NEFT 系统生成并可视化路网图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
        # 下载并可视化 OSM 路网
    python scripts/generate_graph.py --place "Panyu District, Guangzhou" --visualize --output results/osm_graph.png

        # 导出 OSM 路网 JSON 和统计信息
    python scripts/generate_graph.py --export-json results/osm_graph.json --export-stats results/osm_stats.txt

        # 生成主干路精简版（推荐用于算法测试）
    python scripts/generate_graph.py --main-roads --visualize --output results/osm_main_roads.png
        """)

    parser.add_argument('--place', type=str, default='Panyu District, Guangzhou, Guangdong, China',
                                             help='OSM 地区名称')
    parser.add_argument('--network-type', type=str, default='drive',
                       choices=['drive', 'walk', 'bike', 'all'],
                                             help='OSM 路网类型')
    parser.add_argument('--main-roads', action='store_true',
                       help='仅保留主干路（高速、快速路、主干道），大幅减少节点和边数量')
    parser.add_argument('--output', type=str, help='可视化输出路径（PNG）')
    parser.add_argument('--analysis-view', action='store_true', help='输出后端分析版综合拓扑图')
    parser.add_argument('--export-json', type=str, help='导出图为 JSON')
    parser.add_argument('--export-geojson', type=str, help='导出道路 GeoJSON（用于前端叠加）')
    parser.add_argument('--geojson-coord', type=str, default='wgs84', choices=['wgs84', 'gcj02'],
                       help='GeoJSON 坐标系（高德建议使用 gcj02）')
    parser.add_argument('--export-stats', type=str, help='导出统计信息文本')
    parser.add_argument('--export-pickle', type=str, help='导出图为 pickle 文件（供后端直接加载）')
    parser.add_argument('--visualize', action='store_true', help='显示图可视化')
    parser.add_argument('--figsize', type=int, nargs=2, default=[12, 10],
                       help='可视化图尺寸（宽 高）')
    
    args = parser.parse_args()
    
    # 创建图生成器
    gen = GraphGenerator()

    # 生成 OSM 路网图（可选择主干路模式）
    gen.create_osm_graph(place_name=args.place, network_type=args.network_type, 
                         main_roads_only=args.main_roads)
    
    # 可视化
    if args.visualize or args.output:
        if args.analysis_view:
            gen.visualize_for_backend_analysis(output_path=args.output, figsize=tuple(args.figsize))
        else:
            gen.visualize(output_path=args.output, figsize=tuple(args.figsize))
    
    # 导出 JSON
    if args.export_json:
        gen.export_json(args.export_json)

    # 导出 GeoJSON（用于高德/Canvas 叠加）
    if args.export_geojson:
        gen.export_geojson(args.export_geojson, coord_system=args.geojson_coord)
    
    # 导出统计信息
    if args.export_stats:
        gen.export_stats_txt(args.export_stats)
    
    # 导出 pickle（供后端直接加载）
    if args.export_pickle:
        gen.export_pickle(args.export_pickle)
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("✓ 路网生成完成！")
    print("=" * 60)
    print(f"类型: {gen.graph_type}")
    print(f"节点数: {gen.stats['num_nodes']}")
    print(f"边数: {gen.stats['num_edges']}")
    if args.output:
        print(f"可视化文件: {args.output}")
    if args.export_json:
        print(f"JSON 导出: {args.export_json}")
    if args.export_pickle:
        print(f"Pickle 导出: {args.export_pickle}")
    if args.export_stats:
        print(f"统计导出: {args.export_stats}")


if __name__ == "__main__":
    main()
