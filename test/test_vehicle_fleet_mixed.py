import pytest
from backend.data.vehicle import Vehicle
from backend.config import config

def test_mixed_fleet_creation():
    small_cfg = config.get_vehicle_config("small")
    med_cfg = config.get_vehicle_config("medium")
    large_cfg = config.get_vehicle_config("large")
    
    # Check config validity
    assert small_cfg["max_battery"] == 60.0
    assert small_cfg["max_load"] == 500.0
    assert med_cfg["max_load"] == 1500.0
    assert large_cfg["max_load"] == 5000.0
    
    # Test instantiation of a small vehicle
    v_small = Vehicle(id=1, position=None, battery=60.0, max_battery=small_cfg["max_battery"],
                      current_load=0.0, max_load=small_cfg["max_load"],
                      unit_energy_consumption=small_cfg["unit_energy_consumption"],
                      speed=small_cfg["speed"], vehicle_type="small", 
                      charging_power=small_cfg["charging_power"])
                      
    assert v_small.get_remaining_load() == 500.0
    
    # Test partial load
    v_small.current_load = 100.0
    assert v_small.get_remaining_load() == 400.0
    
    # Test battery percentage
    v_small.battery = 30.0
    assert v_small.get_battery_percentage() == 50.0  # 30 / 60
