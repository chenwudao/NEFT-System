import pytest
import asyncio
from unittest.mock import Mock
from backend.interface.websocket_handler import WebSocketHandler
from backend.data.data_manager import DataManager
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.decision.decision_manager import DecisionManager
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus

@pytest.fixture
def data_manager():
    dm = DataManager()
    dm.set_warehouse_position(Position(x=0, y=0))
    return dm

@pytest.fixture
def algorithm_manager(data_manager):
    return AlgorithmManager(data_manager.path_calculator)

@pytest.fixture
def decision_manager(data_manager, algorithm_manager):
    return DecisionManager(data_manager, algorithm_manager)

@pytest.fixture
def websocket_handler(data_manager, decision_manager):
    return WebSocketHandler(data_manager, decision_manager)

def test_websocket_handler_initialization(websocket_handler, data_manager, decision_manager):
    """测试WebSocket处理器初始化"""
    assert websocket_handler is not None
    assert websocket_handler.data_manager == data_manager
    assert websocket_handler.decision_manager == decision_manager
    assert len(websocket_handler.active_connections) == 0

@pytest.mark.asyncio
async def test_connect_disconnect(websocket_handler):
    """测试WebSocket连接和断开"""
    from unittest.mock import AsyncMock
    # 创建模拟WebSocket
    mock_websocket = Mock()
    mock_websocket.accept = AsyncMock()
    
    # 测试连接
    await websocket_handler.connect(mock_websocket)
    assert len(websocket_handler.active_connections) == 1
    assert mock_websocket in websocket_handler.active_connections
    
    # 测试断开
    websocket_handler.disconnect(mock_websocket)
    assert len(websocket_handler.active_connections) == 0
    assert mock_websocket not in websocket_handler.active_connections

@pytest.mark.asyncio
async def test_broadcast_message(websocket_handler):
    """测试广播消息"""
    from unittest.mock import AsyncMock
    # 创建模拟WebSocket
    mock_websocket1 = Mock()
    mock_websocket2 = Mock()
    
    # 模拟异步方法
    mock_websocket1.accept = AsyncMock()
    mock_websocket2.accept = AsyncMock()
    mock_websocket1.send_json = AsyncMock()
    mock_websocket2.send_json = AsyncMock()
    
    # 连接WebSocket
    await websocket_handler.connect(mock_websocket1)
    await websocket_handler.connect(mock_websocket2)
    
    # 测试广播消息（使用已有的 broadcast_state 方法）
    await websocket_handler.broadcast_state()
    
    # 验证消息发送
    assert mock_websocket1.send_json.called
    assert mock_websocket2.send_json.called
    
    # 清理
    websocket_handler.disconnect(mock_websocket1)
    websocket_handler.disconnect(mock_websocket2)

@pytest.mark.asyncio
async def test_broadcast_task_update(websocket_handler, data_manager):
    """测试任务更新广播"""
    from unittest.mock import AsyncMock
    # 创建模拟WebSocket
    mock_websocket = Mock()
    mock_websocket.accept = AsyncMock()
    mock_websocket.send_json = AsyncMock()
    
    # 连接WebSocket
    await websocket_handler.connect(mock_websocket)
    
    # 创建测试任务
    task = Task(
        id=1, position=Position(x=10, y=10), weight=10, create_time=1000, 
        deadline=2000, priority=1, status=TaskStatus.PENDING
    )
    
    # 测试任务更新广播
    await websocket_handler.broadcast_task_update(task)
    
    # 验证消息发送
    assert mock_websocket.send_json.called
    # 清理
    websocket_handler.disconnect(mock_websocket)

@pytest.mark.asyncio
async def test_broadcast_vehicle_update(websocket_handler, data_manager):
    """测试车辆更新广播"""
    from unittest.mock import AsyncMock
    # 创建模拟WebSocket
    mock_websocket = Mock()
    mock_websocket.accept = AsyncMock()
    mock_websocket.send_json = AsyncMock()
    
    # 连接WebSocket
    await websocket_handler.connect(mock_websocket)
    
    # 创建测试车辆
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100.0, max_battery=100.0,
        current_load=0, max_load=100, unit_energy_consumption=0.1, status=VehicleStatus.IDLE
    )
    
    # 测试车辆更新广播
    await websocket_handler.broadcast_vehicle_update(vehicle)
    
    # 验证消息发送
    assert mock_websocket.send_json.called
    # 清理
    websocket_handler.disconnect(mock_websocket)
