import pytest
from backend.data.charging_station import ChargingStation
from backend.data.vehicle import Vehicle, VehicleStatus

def test_charging_station_capacity_and_queue():
    # 容量为3的充电站
    station = ChargingStation(
        id=1, 
        position=None, 
        capacity=3,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=1.0
    )
    
    # 放入3辆车，应全部进入充电位
    station.add_vehicle(101)
    station.add_vehicle(102)
    station.add_vehicle(103)
    
    assert len(station.charging_vehicles) == 3
    assert len(station.waiting_queue) == 0
    assert 101 in station.charging_vehicles
    
    # 放入第4和第5辆车，应进入排队队列
    station.add_vehicle(104)
    station.add_vehicle(105)
    
    assert len(station.charging_vehicles) == 3
    assert len(station.waiting_queue) == 2
    assert station.waiting_queue == [104, 105]
    
    # 移除1辆充电中的车辆（如102），队首(104)应当自动晋升
    station.remove_vehicle(102)
    
    assert len(station.charging_vehicles) == 3
    assert 102 not in station.charging_vehicles
    assert 104 in station.charging_vehicles
    assert len(station.waiting_queue) == 1
    assert station.waiting_queue == [105]
    
    # 直接尝试移除排队中的车辆（如发现别处有空或取消充电）
    station.remove_vehicle(105)
    assert len(station.charging_vehicles) == 3
    assert len(station.waiting_queue) == 0
