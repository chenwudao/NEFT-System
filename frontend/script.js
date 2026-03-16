// 全局元素变量
let canvas, ctx, startButton, stopButton, speedSlow, speedNormal, speedFast, toggleMapButton;
let timestampDisplay, totalScoreDisplay, taskCompletionRateDisplay, vehicleUtilizationDisplay;
let vehicleStatusList, taskList, stationList;

// 地图相关
let map = null;
let mapMarkers = new Map(); // 存储所有标记
let mapPolylines = new Map(); // 存储所有路径
let useRealMap = true; // 是否使用真实地图

// WebSocket连接
// 固定使用localhost:8000/ws，确保与后端服务正确连接
const WS_URL = 'ws://localhost:8000/ws';
console.log('WebSocket URL:', WS_URL);
let websocket = null;
let currentSimulationState = null;
let animationFrameId = null;
let simulationInterval = 500;
const MAP_WIDTH = 1000;
const MAP_HEIGHT = 1000;

// 车辆动画状态
let vehicleAnimations = new Map();

// Canvas拖动功能
let isDragging = false;
let lastMouseX = 0;
let lastMouseY = 0;
let canvasOffsetX = 0;
let canvasOffsetY = 0;

// 地图坐标转换（模拟坐标到真实地图坐标）
function simulateToRealCoords(x, y) {
    // 将模拟坐标（0-1000）转换为真实地图坐标
    // 这里以北京市中心为基准
    const baseLng = 116.404;
    const baseLat = 39.915;
    const scale = 0.001; // 缩放因子
    
    // 确保坐标是有效的数字
    if (isNaN(x) || isNaN(y)) {
        console.error('Invalid coordinates:', x, y);
        return { lng: baseLng, lat: baseLat };
    }
    
    const lng = baseLng + (x * scale);
    const lat = baseLat + (y * scale);
    
    // 验证经纬度是否在合理范围内
    if (isNaN(lng) || isNaN(lat)) {
        console.error('Invalid converted coordinates:', lng, lat, 'from:', x, y);
        return { lng: baseLng, lat: baseLat };
    }
    
    return { lng, lat };
}

// 颜色定义
const colors = {
	background: '#21313f',
	edge: '#546e7a',
	node: '#90a4ae',
	warehouse: '#ffd54f',
	station: '#26a69a',
	stationFull: '#f44336',
	stationQueue: '#ffb300',
	taskPending: '#9C27B0',
	taskDelivering: '#2196F3',
	taskCompleted: '#4CAF50',
	taskTimeout: '#F44336',
	vehicleIdle: '#8BC34A',
	vehicleMovingToTask: '#FFC107',
	vehicleDelivering: '#2196F3',
	vehicleReturningToWarehouse: '#FF5722',
	vehicleMovingToCharge: '#FF9800',
	vehicleCharging: '#F44336',
	path: '#64b5f6',
	completePath: '#00bcd4'
};

// 全局状态存储
let taskCompletePaths = new Map();
let vehiclePathProgress = new Map();
let completedTaskScores = new Map();

// 根据车辆状态获取颜色
function vehicleColor(status) {
	switch (status) {
		case 'idle': return colors.vehicleIdle;
		case 'transporting_to_task':
		case 'moving_to_task': return colors.vehicleMovingToTask;
		case 'delivering': return colors.vehicleDelivering;
		case 'returning_to_warehouse': return colors.vehicleReturningToWarehouse;
		case 'moving_to_charge': return colors.vehicleMovingToCharge;
		case 'charging': return colors.vehicleCharging;
		default: return '#fff';
	}
}

// 获取车辆状态显示文本
function vehicleStatusText(status) {
	switch (status) {
		case 'idle': return '空闲';
		case 'transporting_to_task': return '前往任务点';
		case 'delivering': return '配送中';
		case 'returning_to_warehouse': return '返回仓库';
		case 'moving_to_charge': return '前往充电站';
		case 'charging': return '充电中';
		default: return status;
	}
}

// 根据任务状态获取颜色
function taskColor(status) {
	switch (status) {
		case 'pending': return colors.taskPending;
		case 'delivering': return colors.taskDelivering;
		case 'completed': return colors.taskCompleted;
		case 'timeout': return colors.taskTimeout;
		default: return '#fff';
	}
}

// 初始化地图（异步加载）
function initMap() {
    const loadingOverlay = document.getElementById('loadingOverlay');
    
    // 检查AMap是否已加载
    if (typeof AMap === 'undefined') {
        console.warn('高德地图API尚未加载完成，等待加载...');
        if (loadingOverlay) {
            loadingOverlay.style.display = 'block';
            loadingOverlay.textContent = '正在加载地图API...';
        }
        
        // 等待AMap加载完成
        const checkInterval = setInterval(() => {
            if (typeof AMap !== 'undefined') {
                clearInterval(checkInterval);
                if (loadingOverlay) {
                    loadingOverlay.textContent = '地图API加载完成，正在初始化...';
                }
                createMap();
            }
        }, 100);
        
        // 超时处理
        setTimeout(() => {
            clearInterval(checkInterval);
            if (typeof AMap === 'undefined') {
                console.error('高德地图API加载超时，将使用Canvas模式');
                fallbackToCanvasMode(loadingOverlay);
            }
        }, 5000);
    } else {
        if (loadingOverlay) {
            loadingOverlay.style.display = 'block';
            loadingOverlay.textContent = '正在初始化地图...';
        }
        createMap();
    }
}

// 降级到Canvas模式
function fallbackToCanvasMode(loadingOverlay) {
    console.log('切换到Canvas模式');
    useRealMap = false;
    
    if (loadingOverlay) {
        loadingOverlay.style.display = 'none';
    }
    
    const mapContainer = document.getElementById('mapContainer');
    if (mapContainer) {
        mapContainer.style.display = 'none';
    }
    
    if (canvas) {
        canvas.style.display = 'block';
    }
    
    if (toggleMapButton) {
        toggleMapButton.textContent = '切换到真实地图';
        toggleMapButton.disabled = true; // 禁用切换按钮，因为API不可用
    }
    
    // 显示提示信息
    const mapContainerDiv = document.querySelector('.map-container');
    if (mapContainerDiv) {
        const warning = document.createElement('div');
        warning.style.cssText = 'position: absolute; top: 10px; left: 10px; background: rgba(255, 152, 0, 0.9); color: white; padding: 10px; border-radius: 4px; z-index: 1000; font-size: 14px;';
        warning.textContent = '⚠️ 地图API不可用，已切换到Canvas模式';
        mapContainerDiv.appendChild(warning);
        
        // 5秒后自动消失
        setTimeout(() => {
            warning.remove();
        }, 5000);
    }
}

// 创建地图实例
function createMap() {
    const loadingOverlay = document.getElementById('loadingOverlay');
    
    try {
        // 初始化地图
        map = new AMap.Map('mapContainer', {
            zoom: 14,
            center: [116.404, 39.915], // 北京市中心
            viewMode: '2D',
            pitch: 0,
            mapStyle: 'amap://styles/normal'
        });
        
        // 地图加载完成后隐藏加载提示
        map.on('complete', () => {
            console.log('地图初始化成功');
            if (loadingOverlay) {
                loadingOverlay.style.display = 'none';
            }
            
            // 添加地图控件（在地图加载完成后）
            try {
                AMap.plugin(['AMap.Scale', 'AMap.ToolBar', 'AMap.ControlBar'], function() {
                    map.addControl(new AMap.Scale());
                    map.addControl(new AMap.ToolBar());
                    map.addControl(new AMap.ControlBar({
                        showZoomBar: true,
                        showControlButton: true,
                        position: {
                            right: '10px',
                            top: '10px'
                        }
                    }));
                });
            } catch (pluginError) {
                console.warn('地图控件加载失败:', pluginError);
            }
        });
        
        // 监听地图错误
        map.on('error', (error) => {
            console.error('地图加载错误:', error);
            fallbackToCanvasMode(loadingOverlay);
        });
        
    } catch (error) {
        console.error('地图初始化失败:', error);
        fallbackToCanvasMode(loadingOverlay);
    }
}

// 画布尺寸自适应
function resizeCanvas() {
	if (canvas) {
		const rect = canvas.parentElement.getBoundingClientRect();
		canvas.width = Math.max(300, Math.floor(rect.width));
		canvas.height = Math.max(300, Math.floor(rect.height));
		if (currentSimulationState) {
			drawScene(currentSimulationState);
		}
	}
}
window.addEventListener('resize', resizeCanvas);

// 初始化函数
function initializeApp() {
    // 初始化元素
    canvas = document.getElementById('simulationCanvas');
    if (!canvas) {
        console.error('Canvas element not found');
        return;
    }
    ctx = canvas.getContext('2d');
    startButton = document.getElementById('startButton');
    stopButton = document.getElementById('stopButton');
    speedSlow = document.getElementById('speedSlow');
    speedNormal = document.getElementById('speedNormal');
    speedFast = document.getElementById('speedFast');
    toggleMapButton = document.getElementById('toggleMap');
    timestampDisplay = document.getElementById('timestamp');
    totalScoreDisplay = document.getElementById('totalScore');
    taskCompletionRateDisplay = document.getElementById('taskCompletionRate');
    vehicleUtilizationDisplay = document.getElementById('vehicleUtilization');
    vehicleStatusList = document.getElementById('vehicleStatusList');
    taskList = document.getElementById('taskList');
    stationList = document.getElementById('stationList');
    
    // 添加Canvas拖动事件
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseUp);
    
    // 检查关键元素是否存在
    if (!speedSlow || !speedNormal || !speedFast || !startButton || !stopButton || !toggleMapButton) {
        console.error('Some required elements are missing:', {
            speedSlow: !!speedSlow,
            speedNormal: !!speedNormal,
            speedFast: !!speedFast,
            startButton: !!startButton,
            stopButton: !!stopButton,
            toggleMapButton: !!toggleMapButton
        });
        return;
    }
    
    // 绑定事件监听器
    speedSlow.addEventListener('click', () => setSimulationSpeed('slow'));
    speedNormal.addEventListener('click', () => setSimulationSpeed('normal'));
    speedFast.addEventListener('click', () => setSimulationSpeed('fast'));
    startButton.addEventListener('click', connect);
    stopButton.addEventListener('click', disconnect);
    toggleMapButton.addEventListener('click', toggleMapMode);
    
    // 初始化画布尺寸
    resizeCanvas();
    
    // 初始化地图
    initMap();
}

// 等待DOM完全加载后再初始化地图
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
} else {
    initializeApp();
}

// 监听高德地图API加载错误
window.addEventListener('error', function(event) {
    // 检查是否是高德地图相关的错误
    if (event.filename && event.filename.includes('webapi.amap.com')) {
        console.error('高德地图API错误:', event.message);
        
        // 如果是API密钥无效的错误，自动切换到Canvas模式
        if (event.message && event.message.includes('INVALID_USER_KEY')) {
            console.log('检测到API密钥无效，切换到Canvas模式');
            const loadingOverlay = document.getElementById('loadingOverlay');
            fallbackToCanvasMode(loadingOverlay);
        }
    }
});

// 切换地图模式
function toggleMapMode() {
    useRealMap = !useRealMap;
    
    if (useRealMap) {
        document.getElementById('mapContainer').style.display = 'block';
        canvas.style.display = 'none';
        toggleMapButton.textContent = '切换到Canvas模式';
        if (currentSimulationState) {
            drawScene(currentSimulationState);
        }
    } else {
        document.getElementById('mapContainer').style.display = 'none';
        canvas.style.display = 'block';
        toggleMapButton.textContent = '切换到真实地图';
        if (currentSimulationState) {
            drawScene(currentSimulationState);
        }
    }
}

// 处理Canvas拖动
function handleMouseDown(e) {
	isDragging = true;
	lastMouseX = e.clientX;
	lastMouseY = e.clientY;
	canvas.style.cursor = 'grabbing';
}

function handleMouseMove(e) {
	if (!isDragging) return;
	
	const deltaX = e.clientX - lastMouseX;
	const deltaY = e.clientY - lastMouseY;
	
	canvasOffsetX += deltaX;
	canvasOffsetY += deltaY;
	
	lastMouseX = e.clientX;
	lastMouseY = e.clientY;
	
	// 重绘场景
	if (currentSimulationState) {
		drawScene(currentSimulationState);
	}
}

function handleMouseUp() {
	isDragging = false;
	canvas.style.cursor = 'grab';
}

// 重置Canvas视图
function resetCanvasView() {
	canvasOffsetX = 0;
	canvasOffsetY = 0;
	if (currentSimulationState) {
		drawScene(currentSimulationState);
	}
}

// 连接WebSocket
function connect() {
	console.log('connect() called, websocket:', websocket);
	if (websocket) {
		console.log('WebSocket already exists, skipping');
		return;
	}
	// 禁用启动按钮，防止重复点击
	startButton.disabled = true;
	console.log('Creating WebSocket connection to:', WS_URL);
	try {
		websocket = new WebSocket(WS_URL);
		console.log('WebSocket object created, readyState:', websocket.readyState);
		
		websocket.onopen = () => {
			console.log('WebSocket连接成功，readyState:', websocket.readyState);
			startButton.disabled = true;
			stopButton.disabled = false;
			// 连接成功后向后端订阅全部事件，并请求当前系统状态
			try {
				console.log('Sending subscribe message...');
				websocket.send(JSON.stringify({
					type: 'subscribe',
					events: ['all']
				}));
				console.log('Sending get_state message...');
				websocket.send(JSON.stringify({
					type: 'get_state'
				}));
				console.log('初始化消息已发送');
			} catch (e) {
				console.error('发送初始化消息失败：', e);
			}
		};
		websocket.onmessage = (evt) => {
			console.log('Received WebSocket message:', evt.data);
			try {
				const msg = JSON.parse(evt.data);
				if (!msg) return;

				// 根据后端 websocket_handler 的协议按 type 处理
			switch (msg.type) {
				case 'state_update':
				case 'state_response':
					if (msg.data) {
						console.log('Received state update/response');
						currentSimulationState = msg.data;
						updateDashboard(currentSimulationState);
						drawScene(currentSimulationState);
					}
					break;
				case 'performance_metrics':
					if (msg.data) {
						totalScoreDisplay.textContent = (msg.data.total_score ?? 0).toFixed(1);
						taskCompletionRateDisplay.textContent = (msg.data.completion_rate * 100 ?? 0).toFixed(1) + '%';
					}
					break;
				case 'system_status':
					if (msg.data) {
						// 转换时间戳为可读格式
						if (msg.data.timestamp) {
							const date = new Date(msg.data.timestamp * 1000);
							timestampDisplay.textContent = date.toLocaleString();
						} else {
							timestampDisplay.textContent = '0';
						}
					}
					break;
				case 'task_update':
			case 'vehicle_update':
			case 'station_update':
				// 收到单个更新时，重新获取整个状态
				if (websocket) {
					websocket.send(JSON.stringify({ type: 'get_state' }));
				}
				break;
			case 'complete_path_update':
				// 处理完整路径更新
				if (msg.data) {
					taskCompletePaths.set(msg.data.task_id, msg.data.complete_path);
					vehiclePathProgress.set(msg.data.vehicle_id, {
						total_distance: msg.data.total_distance,
						energy_consumption: msg.data.energy_consumption,
						is_feasible: msg.data.is_feasible,
						estimated_completion_time: msg.data.estimated_completion_time
					});
					if (currentSimulationState) {
						drawScene(currentSimulationState);
					}
				}
				break;
			case 'task_completed':
				// 处理任务完成事件
				if (msg.data) {
					completedTaskScores.set(msg.data.task_id, {
						score: msg.data.score,
						is_on_time: msg.data.is_on_time,
						completion_time: msg.data.completion_time,
						total_distance: msg.data.total_distance
					});
					console.log(`任务#${msg.data.task_id} 完成！得分: ${msg.data.score.toFixed(1)}`);
				}
				break;
			case 'vehicle_returned_to_warehouse':
				// 处理车辆返回仓库事件
				if (msg.data) {
					console.log(`车辆#${msg.data.vehicle_id} 返回仓库，总行驶距离: ${msg.data.total_distance_traveled.toFixed(1)}`);
				}
				break;
			case 'warehouse_position_update':
				// 处理仓库位置更新
				if (msg.data && currentSimulationState) {
					currentSimulationState.warehouse_position = msg.data;
					drawScene(currentSimulationState);
				}
				break;
			case 'command_update':
			default:
				// 如有需要可以在这里扩展其他类型的处理
				break;
			}
			} catch (e) {
				console.error('数据解析失败：', e);
			}
		};
		websocket.onclose = (event) => {
			console.log('WebSocket连接已关闭:', event.code, event.reason);
			startButton.disabled = false;
			stopButton.disabled = true;
			websocket = null;
			if (animationFrameId) {
				cancelAnimationFrame(animationFrameId);
				animationFrameId = null;
			}
		};
		websocket.onerror = (e) => {
			console.error('WebSocket连接错误：', e);
			alert('服务器未启动或无法连接到服务器，请检查后端是否已启动');
			// 恢复按钮状态
			startButton.disabled = false;
			websocket = null;
		};
	} catch (e) {
		console.error('创建WebSocket对象失败：', e);
		alert('创建WebSocket连接失败，请检查网络连接');
		// 恢复按钮状态
		startButton.disabled = false;
	}
}

// 断开WebSocket
function disconnect() {
	if (websocket) {
		websocket.close();
	}
}

// 设置仿真速度
function setSimulationSpeed(speed) {
	speedSlow.style.background = '#f9f9f9';
	speedSlow.style.color = '#333';
	speedNormal.style.background = '#f9f9f9';
	speedNormal.style.color = '#333';
	speedFast.style.background = '#f9f9f9';
	speedFast.style.color = '#333';
	switch (speed) {
		case 'slow':
			simulationInterval = 1000;
			speedSlow.style.background = '#2196F3';
			speedSlow.style.color = 'white';
			break;
		case 'normal':
			simulationInterval = 500;
			speedNormal.style.background = '#2196F3';
			speedNormal.style.color = 'white';
			break;
		case 'fast':
			simulationInterval = 200;
			speedFast.style.background = '#2196F3';
			speedFast.style.color = 'white';
			break;
	}
}


// 绘制场景
function drawScene(state) {
	if (!state) return;
	
	if (useRealMap && map) {
		drawRealMapScene(state);
	} else {
		drawCanvasScene(state);
	}
}

// 在真实地图上绘制场景
function drawRealMapScene(state) {
    // 清除旧的标记和路径
    clearMapMarkers();
    clearMapPolylines();
    
    // 绘制仓库
    if (state.warehouse_position) {
        try {
            const realPos = simulateToRealCoords(state.warehouse_position.x, state.warehouse_position.y);
            if (realPos && !isNaN(realPos.lng) && !isNaN(realPos.lat)) {
                const warehouseMarker = new AMap.Marker({
                    position: [realPos.lng, realPos.lat],
                    icon: new AMap.Icon({
                        size: new AMap.Size(30, 30),
                        image: 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-default.png',
                        imageSize: new AMap.Size(30, 30)
                    }),
                    title: '中央仓库',
                    label: {
                        content: '仓库',
                        offset: new AMap.Pixel(0, -30)
                    }
                });
                warehouseMarker.setMap(map);
                mapMarkers.set('warehouse', warehouseMarker);
            } else {
                console.error('Invalid warehouse position:', realPos);
            }
        } catch (error) {
            console.error('Error creating warehouse marker:', error);
        }
    }
    
    // 绘制充电站
    if (state.charging_stations) {
        for (const s of state.charging_stations) {
            try {
                const stationPos = s.position || s.pos;
                if (!stationPos) continue;
                const realPos = simulateToRealCoords(stationPos.x, stationPos.y);
                
                if (realPos && !isNaN(realPos.lng) && !isNaN(realPos.lat)) {
                    const stationMarker = new AMap.Marker({
                        position: [realPos.lng, realPos.lat],
                        icon: new AMap.Icon({
                            size: new AMap.Size(25, 25),
                            image: 'https://a.amap.com/jsapi_demos/static/demo-center/icons/car.png',
                            imageSize: new AMap.Size(25, 25)
                        }),
                        title: `充电站${s.id}`,
                        label: {
                            content: `充电站${s.id}`,
                            offset: new AMap.Pixel(0, -25)
                        }
                    });
                    stationMarker.setMap(map);
                    mapMarkers.set(`station_${s.id}`, stationMarker);
                } else {
                    console.error('Invalid station position:', realPos, 'for station:', s.id);
                }
            } catch (error) {
                console.error('Error creating station marker:', error);
            }
        }
    }
    
    // 绘制任务
    if (state.tasks) {
        for (const t of state.tasks) {
            try {
                const taskPos = t.position || t.pos;
                if (!taskPos) continue;
                const realPos = simulateToRealCoords(taskPos.x, taskPos.y);
                
                if (!realPos || isNaN(realPos.lng) || isNaN(realPos.lat)) {
                    console.error('Invalid task position:', realPos, 'for task:', t.id);
                    continue;
                }
                
                // 绘制任务标记
                const taskMarker = new AMap.Marker({
                    position: [realPos.lng, realPos.lat],
                    icon: new AMap.Icon({
                        size: new AMap.Size(20, 20),
                        image: 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-red.png',
                        imageSize: new AMap.Size(20, 20)
                    }),
                    title: `任务${t.id}`,
                    label: {
                        content: `任务${t.id}`,
                        offset: new AMap.Pixel(0, -20)
                    }
                });
                taskMarker.setMap(map);
                mapMarkers.set(`task_${t.id}`, taskMarker);
                
                // 绘制完整路径
                const completePath = taskCompletePaths.get(t.id) || t.complete_path;
                if (completePath && completePath.length > 1) {
                    const pathCoords = completePath.map(p => {
                        const realCoords = simulateToRealCoords(p.x || p[0], p.y || p[1]);
                        return [realCoords.lng, realCoords.lat];
                    });
                    
                    // 验证路径坐标
                    const validPathCoords = pathCoords.filter(coord => 
                        coord && !isNaN(coord[0]) && !isNaN(coord[1])
                    );
                    
                    if (validPathCoords.length > 1) {
                        const polyline = new AMap.Polyline({
                            path: validPathCoords,
                            strokeColor: colors.completePath,
                            strokeWeight: 2,
                            strokeStyle: 'dashed',
                            strokeDasharray: [5, 5]
                        });
                        polyline.setMap(map);
                        mapPolylines.set(`task_path_${t.id}`, polyline);
                    }
                }
            } catch (error) {
                console.error('Error creating task marker:', error);
            }
        }
    }
    
    // 绘制车辆（带动画效果）
    if (state.vehicles) {
        for (const v of state.vehicles) {
            try {
                const vehiclePos = v.position || v.pos;
                if (!vehiclePos) continue;
                const realPos = simulateToRealCoords(vehiclePos.x, vehiclePos.y);
                
                if (!realPos || isNaN(realPos.lng) || isNaN(realPos.lat)) {
                    console.error('Invalid vehicle position:', realPos, 'for vehicle:', v.id);
                    continue;
                }
                
                // 绘制车辆标记
                const vehicleMarker = new AMap.Marker({
                    position: [realPos.lng, realPos.lat],
                    icon: new AMap.Icon({
                        size: new AMap.Size(30, 30),
                        image: 'https://a.amap.com/jsapi_demos/static/demo-center/icons/car.png',
                        imageSize: new AMap.Size(30, 30)
                    }),
                    title: `车辆${v.id}`,
                    label: {
                        content: `V${v.id}`,
                        offset: new AMap.Pixel(0, -30)
                    }
                });
                vehicleMarker.setMap(map);
                mapMarkers.set(`vehicle_${v.id}`, vehicleMarker);
                
                // 启动车辆动画
                if (v.complete_path && v.complete_path.length > 1) {
                    animateVehicle(v);
                }
            } catch (error) {
                console.error('Error creating vehicle marker:', error);
            }
        }
    }
}

// 绘制圆角矩形
function drawRoundedRect(ctx, x, y, width, height, radius) {
	ctx.beginPath();
	ctx.moveTo(x + radius, y);
	ctx.lineTo(x + width - radius, y);
	ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
	ctx.lineTo(x + width, y + height - radius);
	ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
	ctx.lineTo(x + radius, y + height);
	ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
	ctx.lineTo(x, y + radius);
	ctx.quadraticCurveTo(x, y, x + radius, y);
	ctx.closePath();
}

// 绘制带阴影的圆形
function drawShadowedCircle(ctx, x, y, radius, fillColor, shadowColor) {
	ctx.save();
	ctx.shadowColor = shadowColor;
	ctx.shadowBlur = 10;
	ctx.shadowOffsetX = 2;
	ctx.shadowOffsetY = 2;
	ctx.fillStyle = fillColor;
	ctx.beginPath();
	ctx.arc(x, y, radius, 0, Math.PI * 2);
	ctx.fill();
	ctx.restore();
}

// 绘制进度条
function drawProgressBar(ctx, x, y, width, height, progress, color, bgColor) {
	// 背景
	ctx.fillStyle = bgColor;
	drawRoundedRect(ctx, x, y, width, height, 3);
	ctx.fill();
	
	// 进度
	if (progress > 0) {
		ctx.fillStyle = color;
		drawRoundedRect(ctx, x, y, width * progress, height, 3);
		ctx.fill();
	}
	
	// 边框
	ctx.strokeStyle = '#fff';
	ctx.lineWidth = 1;
	ctx.stroke();
}

// 在Canvas上绘制场景
function drawCanvasScene(state) {
	ctx.clearRect(0, 0, canvas.width, canvas.height);
	
	// 绘制渐变背景
	const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
	gradient.addColorStop(0, '#1a1a2e');
	gradient.addColorStop(0.5, '#16213e');
	gradient.addColorStop(1, '#0f3460');
	ctx.fillStyle = gradient;
	ctx.fillRect(0, 0, canvas.width, canvas.height);
	
	// 绘制网格线
	ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
	ctx.lineWidth = 1;
	const gridSize = 50;
	for (let x = 0; x <= MAP_WIDTH; x += gridSize) {
		const start = mapToCanvas(x, 0);
		const end = mapToCanvas(x, MAP_HEIGHT);
		ctx.beginPath();
		ctx.moveTo(start.x, start.y);
		ctx.lineTo(end.x, end.y);
		ctx.stroke();
	}
	for (let y = 0; y <= MAP_HEIGHT; y += gridSize) {
		const start = mapToCanvas(0, y);
		const end = mapToCanvas(MAP_WIDTH, y);
		ctx.beginPath();
		ctx.moveTo(start.x, start.y);
		ctx.lineTo(end.x, end.y);
		ctx.stroke();
	}

	// 绘制仓库（中央仓库）
	if (state.warehouse_position) {
		const w = mapToCanvas(state.warehouse_position.x, state.warehouse_position.y);
		
		// 外圈光晕
		const glowGradient = ctx.createRadialGradient(w.x, w.y, 0, w.x, w.y, 25);
		glowGradient.addColorStop(0, 'rgba(255, 193, 7, 0.4)');
		glowGradient.addColorStop(1, 'rgba(255, 193, 7, 0)');
		ctx.fillStyle = glowGradient;
		ctx.beginPath();
		ctx.arc(w.x, w.y, 25, 0, Math.PI * 2);
		ctx.fill();
		
		// 仓库主体
		drawShadowedCircle(ctx, w.x, w.y, 12, '#ffc107', 'rgba(255, 193, 7, 0.5)');
		
		// 仓库图标
		ctx.fillStyle = '#000';
		ctx.font = 'bold 14px Arial';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'middle';
		ctx.fillText('🏭', w.x, w.y);
		
		// 标签
		ctx.fillStyle = '#ffc107';
		ctx.font = 'bold 12px Arial';
		ctx.fillText('仓库', w.x, w.y - 20);
	}

	// 绘制充电站
	if (state.charging_stations) {
		for (const s of state.charging_stations) {
			const stationPos = s.position || s.pos;
			if (!stationPos) continue;
			const p = mapToCanvas(stationPos.x, stationPos.y);
			
			// 根据状态选择颜色
			let color = colors.station;
			let glowColor = 'rgba(38, 166, 154, 0.5)';
			if (s.charging_vehicles.length >= s.capacity) {
				color = colors.stationFull;
				glowColor = 'rgba(244, 67, 54, 0.5)';
			} else if (s.queue_count > 0) {
				color = colors.stationQueue;
				glowColor = 'rgba(255, 179, 0, 0.5)';
			}
			
			// 光晕
			const glowGradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 20);
			glowGradient.addColorStop(0, glowColor);
			glowGradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
			ctx.fillStyle = glowGradient;
			ctx.beginPath();
			ctx.arc(p.x, p.y, 20, 0, Math.PI * 2);
			ctx.fill();
			
			// 充电站主体
			drawShadowedCircle(ctx, p.x, p.y, 10, color, glowColor);
			
			// 闪电图标
			ctx.fillStyle = '#fff';
			ctx.font = 'bold 12px Arial';
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText('⚡', p.x, p.y);
			
			// 标签
			ctx.fillStyle = '#fff';
			ctx.font = '10px Arial';
			ctx.fillText(`CS${s.id}`, p.x, p.y - 18);
			
			// 显示容量信息
			ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
			ctx.font = '9px Arial';
			ctx.fillText(`${s.charging_vehicles.length}/${s.capacity}`, p.x, p.y + 18);
		}
	}

	// 绘制任务和路径
	if (state.tasks) {
		for (const t of state.tasks) {
			const taskPos = t.position || t.pos;
			if (!taskPos) continue;
			const p = mapToCanvas(taskPos.x, taskPos.y);
			
			// 获取任务颜色
			const color = taskColor(t.status);
			
			// 绘制任务路径（如果存在）
			const completePath = taskCompletePaths.get(t.id) || t.complete_path;
			if (completePath && completePath.length > 1 && t.status !== 'completed') {
				// 路径光晕效果
				ctx.save();
				ctx.shadowColor = color;
				ctx.shadowBlur = 10;
				
				ctx.strokeStyle = color;
				ctx.lineWidth = 3;
				ctx.setLineDash([8, 4]);
				ctx.beginPath();
				
				const startX = completePath[0].x !== undefined ? completePath[0].x : completePath[0][0];
				const startY = completePath[0].y !== undefined ? completePath[0].y : completePath[0][1];
				const start = mapToCanvas(startX, startY);
				ctx.moveTo(start.x, start.y);
				
				for (let i = 1; i < completePath.length; i++) {
					const px = completePath[i].x !== undefined ? completePath[i].x : completePath[i][0];
					const py = completePath[i].y !== undefined ? completePath[i].y : completePath[i][1];
					const point = mapToCanvas(px, py);
					ctx.lineTo(point.x, point.y);
				}
				ctx.stroke();
				ctx.restore();
				ctx.setLineDash([]);
			}
			
			// 任务点光晕
			const glowGradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 15);
			glowGradient.addColorStop(0, color.replace(')', ', 0.4)').replace('rgb', 'rgba'));
			glowGradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
			ctx.fillStyle = glowGradient;
			ctx.beginPath();
			ctx.arc(p.x, p.y, 15, 0, Math.PI * 2);
			ctx.fill();
			
			// 任务点主体
			drawShadowedCircle(ctx, p.x, p.y, 8, color, color.replace(')', ', 0.5)').replace('rgb', 'rgba'));
			
			// 任务图标
			ctx.fillStyle = '#fff';
			ctx.font = 'bold 10px Arial';
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText('📦', p.x, p.y);
			
			// 任务ID和重量
			ctx.fillStyle = '#fff';
			ctx.font = 'bold 11px Arial';
			ctx.fillText(`#${t.id}`, p.x, p.y - 16);
			
			// 货物重量
			ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
			ctx.font = '9px Arial';
			ctx.fillText(`${t.weight.toFixed(0)}kg`, p.x, p.y + 16);
			
			// 如果任务已完成，显示得分
			if (t.status === 'completed' && t.score > 0) {
				ctx.fillStyle = t.is_on_time ? '#4CAF50' : '#FF9800';
				ctx.font = 'bold 10px Arial';
				ctx.fillText(`+${t.score.toFixed(0)}`, p.x, p.y + 26);
			}
		}
	}

	// 绘制车辆（增强版）
	if (state.vehicles) {
		for (const v of state.vehicles) {
			const vehiclePos = v.position || v.pos;
			if (!vehiclePos) continue;
			const pv = mapToCanvas(vehiclePos.x, vehiclePos.y);
			
			// 绘制车辆当前路径
			if (v.complete_path && v.complete_path.length > 1) {
				const pathColor = vehicleColor(v.status);
				
				// 路径发光效果
				ctx.save();
				ctx.shadowColor = pathColor;
				ctx.shadowBlur = 8;
				
				ctx.strokeStyle = pathColor;
				ctx.lineWidth = 4;
				ctx.lineCap = 'round';
				ctx.lineJoin = 'round';
				ctx.beginPath();
				
				const vStartX = v.complete_path[0].x !== undefined ? v.complete_path[0].x : v.complete_path[0][0];
				const vStartY = v.complete_path[0].y !== undefined ? v.complete_path[0].y : v.complete_path[0][1];
				const start = mapToCanvas(vStartX, vStartY);
				ctx.moveTo(start.x, start.y);
				
				for (let i = 1; i < v.complete_path.length; i++) {
					const vpx = v.complete_path[i].x !== undefined ? v.complete_path[i].x : v.complete_path[i][0];
					const vpy = v.complete_path[i].y !== undefined ? v.complete_path[i].y : v.complete_path[i][1];
					const p = mapToCanvas(vpx, vpy);
					ctx.lineTo(p.x, p.y);
				}
				ctx.stroke();
				ctx.restore();
			}
			
			// 车辆光晕
			const vehicleColorValue = vehicleColor(v.status);
			const glowGradient = ctx.createRadialGradient(pv.x, pv.y, 0, pv.x, pv.y, 20);
			glowGradient.addColorStop(0, vehicleColorValue.replace(')', ', 0.5)').replace('rgb', 'rgba'));
			glowGradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
			ctx.fillStyle = glowGradient;
			ctx.beginPath();
			ctx.arc(pv.x, pv.y, 20, 0, Math.PI * 2);
			ctx.fill();
			
			// 车辆主体
			drawShadowedCircle(ctx, pv.x, pv.y, 10, vehicleColorValue, vehicleColorValue.replace(')', ', 0.6)').replace('rgb', 'rgba'));
			
			// 车辆图标
			ctx.fillStyle = '#fff';
			ctx.font = 'bold 12px Arial';
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText('🚚', pv.x, pv.y);
			
			// 车辆ID
			ctx.fillStyle = '#fff';
			ctx.font = 'bold 11px Arial';
			ctx.fillText(`V${v.id}`, pv.x, pv.y - 18);
			
			// 电量和载量信息面板
			const panelWidth = 70;
			const panelHeight = 35;
			const panelX = pv.x - panelWidth / 2;
			const panelY = pv.y + 22;
			
			// 面板背景
			ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
			drawRoundedRect(ctx, panelX, panelY, panelWidth, panelHeight, 5);
			ctx.fill();
			
			// 电量进度条
			const batteryPercent = (v.battery / v.max_battery);
			const batteryColor = batteryPercent > 0.3 ? '#4CAF50' : (batteryPercent > 0.15 ? '#FF9800' : '#F44336');
			drawProgressBar(ctx, panelX + 3, panelY + 3, panelWidth - 6, 12, batteryPercent, batteryColor, 'rgba(255, 255, 255, 0.2)');
			
			// 电量文字
			ctx.fillStyle = '#fff';
			ctx.font = '8px Arial';
			ctx.textAlign = 'center';
			ctx.fillText(`🔋${v.battery.toFixed(0)}%`, panelX + panelWidth / 2, panelY + 10);
			
			// 载量进度条
			const loadPercent = (v.current_load / v.max_load);
			const loadColor = loadPercent < 0.8 ? '#2196F3' : '#F44336';
			drawProgressBar(ctx, panelX + 3, panelY + 18, panelWidth - 6, 12, loadPercent, loadColor, 'rgba(255, 255, 255, 0.2)');
			
			// 载量文字
			ctx.fillStyle = '#fff';
			ctx.font = '8px Arial';
			ctx.fillText(`📦${v.current_load.toFixed(0)}/${v.max_load}`, panelX + panelWidth / 2, panelY + 25);
		}
	}

	// 绘制图例
	drawLegend(ctx);

	// 绘制连接提示（如果未连接则显示提示信息）
	if (!websocket) {
		ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
		drawRoundedRect(ctx, canvas.width / 2 - 150, canvas.height / 2 - 40, 300, 80, 10);
		ctx.fill();
		
		ctx.fillStyle = '#fff';
		ctx.font = 'bold 16px Arial';
		ctx.textAlign = 'center';
		ctx.fillText('未连接到服务器', canvas.width / 2, canvas.height / 2 - 10);
		
		ctx.fillStyle = '#aaa';
		ctx.font = '14px Arial';
		ctx.fillText('点击"启动模拟"按钮开始', canvas.width / 2, canvas.height / 2 + 15);
	}
}

// 绘制图例
function drawLegend(ctx) {
	const legendX = 10;
	const legendY = 10;
	const legendWidth = 140;
	const legendHeight = 180;
	
	// 图例背景
	ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
	drawRoundedRect(ctx, legendX, legendY, legendWidth, legendHeight, 8);
	ctx.fill();
	
	// 图例标题
	ctx.fillStyle = '#fff';
	ctx.font = 'bold 12px Arial';
	ctx.textAlign = 'left';
	ctx.fillText('📊 图例', legendX + 10, legendY + 20);
	
	// 图例项
	const items = [
		{ color: colors.warehouse, icon: '🏭', text: '仓库' },
		{ color: colors.station, icon: '⚡', text: '充电站' },
		{ color: colors.taskPending, icon: '📦', text: '待处理任务' },
		{ color: colors.taskDelivering, icon: '📦', text: '配送中' },
		{ color: colors.taskCompleted, icon: '✓', text: '已完成' },
		{ color: colors.vehicleIdle, icon: '🚚', text: '空闲车辆' },
		{ color: colors.vehicleMovingToTask, icon: '🚚', text: '前往任务' },
		{ color: colors.vehicleCharging, icon: '🚚', text: '充电中' }
	];
	
	let itemY = legendY + 40;
	items.forEach(item => {
		// 颜色点
		ctx.fillStyle = item.color;
		ctx.beginPath();
		ctx.arc(legendX + 20, itemY, 6, 0, Math.PI * 2);
		ctx.fill();
		
		// 文字
		ctx.fillStyle = '#fff';
		ctx.font = '10px Arial';
		ctx.fillText(`${item.icon} ${item.text}`, legendX + 35, itemY + 3);
		
		itemY += 18;
	});
}

// 清除地图标记
function clearMapMarkers() {
    for (const marker of mapMarkers.values()) {
        marker.setMap(null);
    }
    mapMarkers.clear();
}

// 清除地图路径
function clearMapPolylines() {
    for (const polyline of mapPolylines.values()) {
        polyline.setMap(null);
    }
    mapPolylines.clear();
}

// 车辆动画函数
function animateVehicle(vehicle) {
    if (!map || !vehicle.complete_path || vehicle.complete_path.length < 2) {
        return;
    }
    
    // 取消之前的动画
    const existingAnimation = vehicleAnimations.get(vehicle.id);
    if (existingAnimation) {
        clearInterval(existingAnimation);
    }
    
    // 使用后端提供的速度，如果没有则使用默认值
    const vehicleSpeed = vehicle.speed || 0.1;
    
    // 将后端速度转换为前端动画速度
    // 后端速度单位：单位/秒
    // 前端动画间隔：50ms
    // 假设路径段平均长度为100单位，则每段需要 100/speed 秒
    // 前端每帧进度 = (50ms / (100/speed * 1000ms)) = speed / 20
    const animationSpeed = vehicleSpeed / 20;
    
    const path = vehicle.complete_path;
    let currentIndex = 0;
    let progress = 0;
    
    const animation = setInterval(() => {
        const from = path[currentIndex];
        const to = path[currentIndex + 1];
        
        // 处理两种路径格式：对象格式 {x, y} 或数组格式 [x, y]
        const fromX = from.x !== undefined ? from.x : from[0];
        const fromY = from.y !== undefined ? from.y : from[1];
        const toX = to.x !== undefined ? to.x : to[0];
        const toY = to.y !== undefined ? to.y : to[1];
        
        progress += animationSpeed;
        
        if (progress >= 1) {
            progress = 0;
            currentIndex++;
            if (currentIndex >= path.length - 1) {
                clearInterval(animation);
                vehicleAnimations.delete(vehicle.id);
                return;
            }
        }
        
        // 计算当前位置
        const currentX = fromX + (toX - fromX) * progress;
        const currentY = fromY + (toY - fromY) * progress;
        
        // 更新车辆标记位置
        const realPos = simulateToRealCoords(currentX, currentY);
        const marker = mapMarkers.get(`vehicle_${vehicle.id}`);
        if (marker) {
            marker.setPosition([realPos.lng, realPos.lat]);
        }
    }, 50);
    
    vehicleAnimations.set(vehicle.id, animation);
}

// 坐标映射
function mapToCanvas(x, y) {
	const scaleX = canvas.width / MAP_WIDTH;
	const scaleY = canvas.height / MAP_HEIGHT;
	return { x: x * scaleX + canvasOffsetX, y: y * scaleY + canvasOffsetY };
}

// 更新仪表盘
function updateDashboard(state) {
	// 转换时间戳为可读格式
	if (state.timestamp) {
		const date = new Date(state.timestamp * 1000);
		timestampDisplay.textContent = date.toLocaleString();
	} else {
		timestampDisplay.textContent = '0';
	}
	
	// 使用后端计算的字段
	totalScoreDisplay.textContent = (state.total_score ?? 0).toFixed(1);
	taskCompletionRateDisplay.textContent = (state.completion_rate * 100 ?? 0).toFixed(1) + '%';
	vehicleUtilizationDisplay.textContent = (state.vehicle_utilization * 100 ?? 0).toFixed(1) + '%';

	// 更新车辆状态列表
	vehicleStatusList.innerHTML = '';
	if (state.vehicles) {
		for (const v of state.vehicles) {
			const div = document.createElement('div');
			div.className = `vehicle-item ${v.status}`;
			const progressInfo = vehiclePathProgress.get(v.id);
			let progressText = '';
			if (progressInfo) {
				progressText = `| 路径进度: ${(v.path_progress * 100).toFixed(0)}%`;
			}
			div.innerHTML = `
				<strong>车辆#${v.id}</strong>
				<p>状态：${vehicleStatusText(v.status)} | 电量：${v.battery.toFixed(1)}% | 载重：${v.current_load.toFixed(1)}/${v.max_load} ${progressText}</p>
				<p>总行驶距离: ${(v.total_distance_traveled || 0).toFixed(1)} | 电量消耗: ${(v.energy_consumption || 0).toFixed(1)}</p>
			`;
			vehicleStatusList.appendChild(div);
		}
	}

	taskList.innerHTML = '';
	if (state.tasks) {
		for (const t of state.tasks) {
			const div = document.createElement('div');
			div.className = `task-item ${t.status}`;
			let scoreText = '';
			if (t.status === 'completed' && t.score > 0) {
				scoreText = `<span class="score ${t.is_on_time ? 'on-time' : 'timeout'}">得分: ${t.score.toFixed(1)} ${t.is_on_time ? '(按时)' : '(超时)'}</span>`;
			}
			const distanceText = t.complete_path_distance > 0 ? `| 路径距离: ${t.complete_path_distance.toFixed(1)}` : '';
			div.innerHTML = `
				<strong>任务#${t.id}</strong>
				<p>重量：${t.weight.toFixed(1)} | 分配车辆：${t.assigned_vehicle_id || '未分配'} ${distanceText}</p>
				<p>状态：${t.status} ${scoreText}</p>
			`;
			taskList.appendChild(div);
		}
	}

	stationList.innerHTML = '';
	// 后端字段为 charging_stations
	if (state.charging_stations) {
		for (const s of state.charging_stations) {
			const div = document.createElement('div');
			div.className = `station-item ${s.charging_vehicles.length >= s.capacity ? 'full' : (s.queue_count > 0 ? 'queue' : '')}`;
			div.innerHTML = `
				<strong>充电站${s.id}</strong>
				<p>容量：${s.capacity} | 充电中：${s.charging_vehicles.length} | 排队：${s.queue_count}</p>
			`;
			stationList.appendChild(div);
		}
	}
}