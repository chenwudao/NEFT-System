// 全局元素变量
let canvas, ctx, startButton, stopButton, toggleMapButton;
let timestampDisplay, totalScoreDisplay, taskCompletionRateDisplay, vehicleUtilizationDisplay;
let vehicleStatusList, taskList, stationList;
let currentStrategyDisplay, strategyReasonDisplay;
let modeSelect, scaleSelect, simulationStatusDisplay;

// 地图相关
let map = null;
let mapMarkers = new Map(); // 存储所有标记
let mapPolylines = new Map(); // 存储所有路径
let useRealMap = true; // 是否使用真实地图
const OSM_OVERLAY_URLS = [
    './osm_main_roads.geojson',  // 主干路覆盖层（精简版，更高效）
    './osm_panyu_amap_overlay_v2.geojson',  // 完整路网（备用）
    './osm_panyu_amap_overlay_v1.geojson'
];
let osmOverlayGeoJson = null;
let osmOverlayAmapPolylines = [];
let osmOverlayBounds = null;

// WebSocket连接
// 固定使用localhost:8000/ws，确保与后端服务正确连接
const WS_URL = 'ws://localhost:8000/ws';
const API_BASE = 'http://localhost:8000/api';
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

async function apiRequest(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
        headers: {
            'Content-Type': 'application/json'
        },
        ...options
    });
    if (!response.ok) {
        throw new Error(`API request failed: ${path}, status=${response.status}`);
    }
    return response.json();
}

async function applySimulationConfig() {
    const mode = modeSelect ? modeSelect.value : 'realtime';
    const scale = scaleSelect ? scaleSelect.value : 'medium';
    const result = await apiRequest('/simulation/config', {
        method: 'POST',
        body: JSON.stringify({ mode, scale })
    });
    if (simulationStatusDisplay) {
        simulationStatusDisplay.textContent = result.running ? '运行中' : '已配置';
    }
    return result;
}

async function refreshSimulationStatus() {
    try {
        const status = await apiRequest('/simulation/status');
        if (simulationStatusDisplay) {
            simulationStatusDisplay.textContent = status.running ? `运行中（${status.mode}/${status.scale}）` : '未启动';
        }
    } catch (error) {
        console.warn('获取仿真状态失败:', error);
    }
}

// 后端实体坐标为 OSM 图一致空间：WGS84 经纬度 (x=lon, y=lat)；高德需 GCJ-02
function wgs84ToGcj02(lon, lat) {
    if (lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271) {
        return { lng: lon, lat };
    }
    const a = 6378245.0;
    const ee = 0.00669342162296594323;
    function transformLat(x, y) {
        let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin(y / 3.0 * Math.PI)) * 2.0 / 3.0;
        ret += (160.0 * Math.sin(y / 12.0 * Math.PI) + 320 * Math.sin(y * Math.PI / 30.0)) * 2.0 / 3.0;
        return ret;
    }
    function transformLon(x, y) {
        let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin(x / 3.0 * Math.PI)) * 2.0 / 3.0;
        ret += (150.0 * Math.sin(x / 12.0 * Math.PI) + 300.0 * Math.sin(x / 30.0 * Math.PI)) * 2.0 / 3.0;
        return ret;
    }
    let dLat = transformLat(lon - 105.0, lat - 35.0);
    let dLon = transformLon(lon - 105.0, lat - 35.0);
    const radLat = lat / 180.0 * Math.PI;
    let magic = Math.sin(radLat);
    magic = 1 - ee * magic * magic;
    const sqrtMagic = Math.sqrt(magic);
    dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
    dLon = (dLon * 180.0) / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
    return { lng: lon + dLon, lat: lat + dLat };
}

function positionToAmap(pos) {
    if (!pos || (pos.x === undefined && pos.lng === undefined)) {
        return { lng: 113.38, lat: 23.0 };
    }
    if (Number.isFinite(pos.gcj_lng) && Number.isFinite(pos.gcj_lat)) {
        return { lng: pos.gcj_lng, lat: pos.gcj_lat };
    }
    const lon = Number(pos.x !== undefined ? pos.x : pos.lon);
    const lat = Number(pos.y !== undefined ? pos.y : pos.lat);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
        return { lng: 113.38, lat: 23.0 };
    }
    return wgs84ToGcj02(lon, lat);
}

function pathPointToAmap(p) {
    if (!p) return null;
    if (Number.isFinite(p.gcj_lng) && Number.isFinite(p.gcj_lat)) {
        return [p.gcj_lng, p.gcj_lat];
    }
    const x = p.x !== undefined ? p.x : p[0];
    const y = p.y !== undefined ? p.y : p[1];
    const g = wgs84ToGcj02(Number(x), Number(y));
    return [g.lng, g.lat];
}

/** @deprecated 保留名称：参数为 WGS84 经纬度 */
function simulateToRealCoords(x, y) {
    return wgs84ToGcj02(Number(x), Number(y));
}

function entityPosToCanvas(pos) {
    if (!pos) {
        return { x: canvas.width / 2, y: canvas.height / 2 };
    }
    if (osmOverlayBounds) {
        let lng;
        let lat;
        if (Number.isFinite(pos.gcj_lng) && Number.isFinite(pos.gcj_lat)) {
            lng = pos.gcj_lng;
            lat = pos.gcj_lat;
        } else {
            const g = wgs84ToGcj02(Number(pos.x), Number(pos.y));
            lng = g.lng;
            lat = g.lat;
        }
        const p = geoToCanvas(lng, lat);
        return { x: p.x + canvasOffsetX, y: p.y + canvasOffsetY };
    }
    return mapToCanvas(pos.x, pos.y);
}

function canvasPathPoint(p) {
    if (!p) {
        return { x: 0, y: 0 };
    }
    if (typeof p === 'object' && (p.x !== undefined || p.gcj_lng !== undefined)) {
        return entityPosToCanvas(p);
    }
    return entityPosToCanvas({ x: p[0], y: p[1] });
}

function renderStrategyScores(scores) {
    const el = document.getElementById('strategyScoreDetail');
    if (!el) return;
    if (!scores || typeof scores !== 'object' || Object.keys(scores).length === 0) {
        el.innerHTML = '<p class="strategy-score-empty">暂无候选策略评分（非 auto 或未触发 meta 选择）</p>';
        return;
    }
    const rows = Object.entries(scores).map(([name, d]) => {
        const s = d || {};
        return `<tr><td>${name}</td><td>${(s.total_score ?? 0).toFixed(2)}</td><td>${s.assigned_tasks ?? 0}</td><td>${(s.distance_cost ?? 0).toFixed(0)}</td><td>${(s.energy_cost ?? 0).toFixed(1)}</td></tr>`;
    }).join('');
    el.innerHTML = `
        <table class="strategy-score-table">
            <thead><tr><th>策略</th><th>总分</th><th>分配任务数</th><th>路径距离</th><th>能耗</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function computeOverlayBounds(geojson) {
    let minLng = Infinity;
    let maxLng = -Infinity;
    let minLat = Infinity;
    let maxLat = -Infinity;

    for (const feature of (geojson.features || [])) {
        const coords = feature?.geometry?.coordinates || [];
        for (const [lng, lat] of coords) {
            if (Number.isFinite(lng) && Number.isFinite(lat)) {
                minLng = Math.min(minLng, lng);
                maxLng = Math.max(maxLng, lng);
                minLat = Math.min(minLat, lat);
                maxLat = Math.max(maxLat, lat);
            }
        }
    }

    if (!Number.isFinite(minLng) || !Number.isFinite(minLat)) {
        return null;
    }
    return { minLng, maxLng, minLat, maxLat };
}

async function loadOsmOverlayGeoJson() {
    for (const url of OSM_OVERLAY_URLS) {
        try {
            const resp = await fetch(url, { cache: 'no-cache' });
            if (!resp.ok) continue;
            const data = await resp.json();
            if (data && data.type === 'FeatureCollection' && Array.isArray(data.features)) {
                osmOverlayGeoJson = data;
                osmOverlayBounds = computeOverlayBounds(data);
                console.log(`已加载OSM叠加路网: ${url}, features=${data.features.length}`);
                return true;
            }
        } catch (e) {
            console.warn(`加载OSM叠加路网失败: ${url}`, e);
        }
    }
    console.warn('未找到可用的OSM叠加GeoJSON文件');
    return false;
}

function clearOsmAmapOverlay() {
    for (const p of osmOverlayAmapPolylines) {
        p.setMap(null);
    }
    osmOverlayAmapPolylines = [];
}

function drawOsmOverlayOnAmap() {
    if (!map || !osmOverlayGeoJson) return;
    clearOsmAmapOverlay();

    // 检查是否为主干路模式（根据文件名或特征数量判断）
    const isMainRoadsMode = osmOverlayGeoJson.features.length < 5000;
    
    for (const feature of osmOverlayGeoJson.features) {
        if (feature?.geometry?.type !== 'LineString') continue;
        const path = (feature.geometry.coordinates || []).filter(
            c => Array.isArray(c) && c.length >= 2 && Number.isFinite(c[0]) && Number.isFinite(c[1])
        );
        if (path.length < 2) continue;

        const highway = feature?.properties?.highway || '';
        
        // 主干路模式：所有道路都用更明显的样式
        // 完整路网模式：只有主干路用明显样式
        let strokeColor, strokeWeight, strokeOpacity;
        
        if (isMainRoadsMode) {
            // 主干路模式 - 更醒目的样式
            const roadTypeColors = {
                'motorway': '#ff4444',      // 高速 - 红色
                'trunk': '#ff8800',         // 快速路 - 橙色
                'primary': '#ffcc00',       // 主干道 - 黄色
                'secondary': '#44ff44',     // 次干道 - 绿色
                'tertiary': '#44aaff'       // 支路 - 蓝色
            };
            strokeColor = roadTypeColors[highway] || '#66ccff';
            strokeWeight = 3;
            strokeOpacity = 0.9;
        } else {
            // 完整路网模式
            const isMainRoad = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary'].includes(highway);
            strokeColor = isMainRoad ? '#ef4444' : '#334155';
            strokeWeight = isMainRoad ? 2 : 1;
            strokeOpacity = isMainRoad ? 0.75 : 0.35;
        }
        
        const polyline = new AMap.Polyline({
            path,
            strokeColor,
            strokeWeight,
            strokeOpacity,
            zIndex: 40
        });
        polyline.setMap(map);
        osmOverlayAmapPolylines.push(polyline);
    }
    
    console.log(`[OSM Overlay] 已绘制 ${osmOverlayAmapPolylines.length} 条道路` + 
                (isMainRoadsMode ? ' (主干路模式)' : ' (完整路网模式)'));
}

function geoToCanvas(lng, lat) {
    if (!osmOverlayBounds) {
        return { x: 0, y: 0 };
    }
    const pad = 20;
    const drawableW = Math.max(1, canvas.width - pad * 2);
    const drawableH = Math.max(1, canvas.height - pad * 2);
    const lngSpan = Math.max(1e-9, osmOverlayBounds.maxLng - osmOverlayBounds.minLng);
    const latSpan = Math.max(1e-9, osmOverlayBounds.maxLat - osmOverlayBounds.minLat);
    const x = ((lng - osmOverlayBounds.minLng) / lngSpan) * drawableW + pad;
    const y = canvas.height - (((lat - osmOverlayBounds.minLat) / latSpan) * drawableH + pad);
    return { x, y };
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
		case 'transporting':
		case 'moving_to_task': return colors.vehicleMovingToTask;
		case 'delivering': return colors.vehicleDelivering;
		case 'returning_to_warehouse': return colors.vehicleReturningToWarehouse;
		case 'moving_to_charge': return colors.vehicleMovingToCharge;
		case 'charging': return colors.vehicleCharging;
		case 'waiting_charge': return '#fb923c'; // 排队充电：橙色（与充电中红色区分）
		default: return '#fff';
	}
}

// 获取车辆状态显示文本
function vehicleStatusText(status) {
	switch (status) {
		case 'idle': return '空闲';
		case 'transporting_to_task': return '前往任务点';
		case 'transporting': return '运输中';
		case 'delivering': return '配送中';
		case 'returning_to_warehouse': return '返回仓库';
		case 'moving_to_charge': return '前往充电站';
		case 'charging': return '充电中 ⚡';
		case 'waiting_charge': return '排队充电 ⏳';  // 新增
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
            zoom: 15, // 增大缩放级别，更清晰地显示校区和周边
            center: [113.406388, 23.011545], // 华南理工大学广州国际校区（番禺区南村镇兴业大道东777号，距离板桥地铁站约1.3km）
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
            drawOsmOverlayOnAmap();
            if (osmOverlayBounds) {
                const cx = (osmOverlayBounds.minLng + osmOverlayBounds.maxLng) / 2;
                const cy = (osmOverlayBounds.minLat + osmOverlayBounds.maxLat) / 2;
                map.setCenter([cx, cy]);
                map.setZoom(11);
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
    const resetButton = document.getElementById('resetButton');
    toggleMapButton = document.getElementById('toggleMap');
    timestampDisplay = document.getElementById('timestamp');
    totalScoreDisplay = document.getElementById('totalScore');
    taskCompletionRateDisplay = document.getElementById('taskCompletionRate');
    vehicleUtilizationDisplay = document.getElementById('vehicleUtilization');
    vehicleStatusList = document.getElementById('vehicleStatusList');
    taskList = document.getElementById('taskList');
    stationList = document.getElementById('stationList');
	currentStrategyDisplay = document.getElementById('currentStrategy');
	strategyReasonDisplay = document.getElementById('strategyReason');
    modeSelect = document.getElementById('modeSelect');
    scaleSelect = document.getElementById('scaleSelect');
    simulationStatusDisplay = document.getElementById('simulationStatus');
    
    // 添加Canvas拖动事件
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseUp);
    
    // 检查关键元素是否存在
    if (!startButton || !stopButton || !toggleMapButton) {
        console.error('Some required elements are missing:', {
            startButton: !!startButton,
            stopButton: !!stopButton,
            toggleMapButton: !!toggleMapButton
        });
        return;
    }
    startButton.addEventListener('click', () => {
        connect().catch((e) => {
            console.error('启动模拟失败:', e);
            alert(`启动模拟失败: ${e.message}`);
            startButton.disabled = false;
            stopButton.disabled = true;
        });
    });
    stopButton.addEventListener('click', disconnect);
    if (resetButton) {
        resetButton.addEventListener('click', async () => {
            if (!confirm('确定要清空当前所有进度并重置沙盒环境吗？')) return;
            try {
                if (websocket) websocket.close();
                
                // 调用后端重置API
                const resetResult = await apiRequest('/simulation/reset', { method: 'POST' });
                console.log('Reset result:', resetResult);
                
                // 重置前端状态
                websocket = null;
                startButton.disabled = false;
                stopButton.disabled = true;
                
                // 更新状态显示
                if (simulationStatusDisplay) {
                    simulationStatusDisplay.textContent = '已重置，请选择模式和规模后启动';
                }
                
                // 清空画布和地图
                if (ctx && canvas) {
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                }
                if (useRealMap && map) {
                    clearAllMapState();
                }
                
                // 重置统计数据
                if (timestampDisplay) timestampDisplay.textContent = '0';
                if (totalScoreDisplay) totalScoreDisplay.textContent = '0.0';
                if (taskCompletionRateDisplay) taskCompletionRateDisplay.textContent = '0.0%';
                if (vehicleUtilizationDisplay) vehicleUtilizationDisplay.textContent = '0.0%';
                
                alert('模拟已重置，请重新选择模式和规模后启动');
            } catch (e) {
                console.error('重置仿真失败:', e);
                alert('重置仿真失败: ' + e.message);
            }
        });
    }
    toggleMapButton.addEventListener('click', toggleMapMode);
    
    // 模式和规模选择只在未启动时可用，启动后禁用
    if (modeSelect) {
        modeSelect.addEventListener('change', () => {
            // 只有在未运行状态才能切换
            const isRunning = websocket && websocket.readyState === WebSocket.OPEN;
            if (isRunning) {
                alert('模拟运行中或暂停时不能切换模式，请先重置模拟');
                // 恢复原值
                refreshSimulationStatus();
                return;
            }
            applySimulationConfig().catch((e) => console.warn('更新模式失败:', e));
        });
    }
    if (scaleSelect) {
        scaleSelect.addEventListener('change', () => {
            // 只有在未运行状态才能切换
            const isRunning = websocket && websocket.readyState === WebSocket.OPEN;
            if (isRunning) {
                alert('模拟运行中或暂停时不能切换规模，请先重置模拟');
                // 恢复原值
                refreshSimulationStatus();
                return;
            }
            applySimulationConfig().catch((e) => console.warn('更新规模失败:', e));
        });
    }
    
    // 初始化画布尺寸
    resizeCanvas();
    
    loadOsmOverlayGeoJson().finally(() => {
        // 初始化地图
        initMap();
    });
    refreshSimulationStatus();
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
async function connect() {
	console.log('connect() called, websocket:', websocket);
	if (websocket) {
		console.log('WebSocket already exists, skipping');
		return;
	}
    
    // 获取用户选择的模式和规模
    const mode = modeSelect ? modeSelect.value : 'realtime';
    const scale = scaleSelect ? scaleSelect.value : 'medium';
    
    console.log(`Starting simulation with mode=${mode}, scale=${scale}`);
    
    // 发送启动请求，包含模式和规模
    const startResult = await apiRequest('/simulation/start', {
        method: 'POST',
        body: JSON.stringify({ mode, scale })
    });
    
    console.log('Start simulation result:', startResult);
    
    if (!startResult.success) {
        throw new Error(startResult.message || '启动仿真失败');
    }
    
    if (simulationStatusDisplay) {
        simulationStatusDisplay.textContent = `运行中（${mode}/${scale}）- ${startResult.tasks_count || 0}个任务`;
    }
	// 禁用启动按钮，防止重复点击
	startButton.disabled = true;
	console.log('Creating WebSocket connection to:', WS_URL);
	try {
		websocket = new WebSocket(WS_URL);
		console.log('WebSocket object created, readyState:', websocket.readyState);
		
		websocket.onopen = async () => {
			console.log('WebSocket连接成功，readyState:', websocket.readyState);
			startButton.disabled = true;
			stopButton.disabled = false;
			
			// 获取当前模拟速度
			try {
				const speedResponse = await apiRequest('/simulation/speed');
				if (speedResponse && speedResponse.speed_factor) {
					const speedDisplay = document.getElementById('simSpeedDisplay');
					if (speedDisplay) {
						speedDisplay.textContent = `×${speedResponse.speed_factor}（1秒=${(speedResponse.speed_factor/60).toFixed(0)}分钟）`;
					}
				}
			} catch (e) {
				console.log('获取模拟速度失败:', e);
			}
			
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
                    if (currentStrategyDisplay && msg.data.current_strategy) {
                        currentStrategyDisplay.textContent = msg.data.current_strategy;
                    }
                    if (strategyReasonDisplay && msg.data.current_strategy_reason) {
                        strategyReasonDisplay.textContent = msg.data.current_strategy_reason;
                    }
                    renderStrategyScores(msg.data.strategy_scores);
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
async function disconnect() {
    try {
        await apiRequest('/simulation/stop', { method: 'POST' });
    } catch (e) {
        console.warn('暂停仿真请求失败:', e);
    }
    if (simulationStatusDisplay) {
        simulationStatusDisplay.textContent = '已暂停（需重置后才能切换模式/规模）';
    }
	if (websocket) {
		websocket.close();
	}
    // 暂停时禁用启动按钮，强制用户先重置
    startButton.disabled = true;
    stopButton.disabled = true;
}

// 跟踪上次绘制的状态，用于增量更新
let lastDrawnState = {
    tasks: new Map(),
    vehicles: new Map(),
    stations: new Map(),
    warehouse: null
};

// 绘制场景
function drawScene(state) {
	if (!state) return;
	
	if (useRealMap && map) {
		drawRealMapSceneIncremental(state);
	} else {
		drawCanvasScene(state);
	}
}

// 在真实地图上增量绘制场景（避免闪烁）
function drawRealMapSceneIncremental(state) {
    // 1. 更新仓库（静态，通常不变）
    if (state.warehouse_position && !lastDrawnState.warehouse) {
        try {
            const realPos = positionToAmap(state.warehouse_position);
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
                lastDrawnState.warehouse = state.warehouse_position;
            }
        } catch (error) {
            console.error('Error creating warehouse marker:', error);
        }
    }

    // 2. 更新充电站（静态）
    if (state.charging_stations) {
        for (const s of state.charging_stations) {
            const stationKey = `station_${s.id}`;
            if (lastDrawnState.stations.has(s.id)) continue; // 已绘制，跳过
            
            try {
                const stationPos = s.position || s.pos;
                if (!stationPos) continue;
                const realPos = positionToAmap(stationPos);
                
                if (realPos && !isNaN(realPos.lng) && !isNaN(realPos.lat)) {
                    const stationMarker = new AMap.Marker({
                        position: [realPos.lng, realPos.lat],
                        icon: new AMap.Icon({
                            size: new AMap.Size(25, 25),
                            image: 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-default.png',
                            imageSize: new AMap.Size(25, 25)
                        }),
                        title: `充电站${s.id}`,
                        label: {
                            content: `充电站${s.id}`,
                            offset: new AMap.Pixel(0, -25)
                        }
                    });
                    stationMarker.setMap(map);
                    mapMarkers.set(stationKey, stationMarker);
                    lastDrawnState.stations.set(s.id, s);
                }
            } catch (error) {
                console.error('Error creating station marker:', error);
            }
        }
    }

    // 3. 更新任务（只添加新任务或更新状态变化的任务）
    if (state.tasks) {
        for (const t of state.tasks) {
            const taskKey = `task_${t.id}`;
            const lastTask = lastDrawnState.tasks.get(t.id);
            
            // 检查是否需要更新：新任务或状态变化
            const needsUpdate = !lastTask || lastTask.status !== t.status;
            
            if (!needsUpdate) continue;
            
            // 移除旧标记
            if (lastTask) {
                const oldMarker = mapMarkers.get(taskKey);
                if (oldMarker) {
                    oldMarker.setMap(null);
                    mapMarkers.delete(taskKey);
                }
                const oldPath = mapPolylines.get(`task_path_${t.id}`);
                if (oldPath) {
                    oldPath.setMap(null);
                    mapPolylines.delete(`task_path_${t.id}`);
                }
            }
            
            try {
                const taskPos = t.position || t.pos;
                if (!taskPos) continue;
                const realPos = positionToAmap(taskPos);
                
                if (!realPos || isNaN(realPos.lng) || isNaN(realPos.lat)) {
                    console.error('Invalid task position:', realPos, 'for task:', t.id);
                    continue;
                }
                
                // 根据状态选择颜色
                let iconUrl = 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-red.png';
                if (t.status === 'completed') {
                    iconUrl = 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-green.png';
                } else if (t.status === 'in_progress' || t.status === 'assigned') {
                    iconUrl = 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-yellow.png';
                }
                
                // 绘制任务标记
                const taskMarker = new AMap.Marker({
                    position: [realPos.lng, realPos.lat],
                    icon: new AMap.Icon({
                        size: new AMap.Size(20, 20),
                        image: iconUrl,
                        imageSize: new AMap.Size(20, 20)
                    }),
                    title: `任务${t.id}`,
                    label: {
                        content: `任务${t.id}`,
                        offset: new AMap.Pixel(0, -20)
                    }
                });
                taskMarker.setMap(map);
                mapMarkers.set(taskKey, taskMarker);
                
                // 绘制完整路径（仅对进行中的任务）
                const completePath = taskCompletePaths.get(t.id) || t.complete_path;
                if (completePath && completePath.length > 1 && t.status !== 'completed') {
                    const pathCoords = completePath.map(p => pathPointToAmap(p)).filter(Boolean);
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
                
                lastDrawnState.tasks.set(t.id, { ...t });
            } catch (error) {
                console.error('Error creating task marker:', error);
            }
        }
    }

    // 4. 更新车辆位置（只更新位置，不重新创建标记）
    if (state.vehicles) {
        for (const v of state.vehicles) {
            const vehicleKey = `vehicle_${v.id}`;
            let vehicleMarker = mapMarkers.get(vehicleKey);
            
            try {
                const vehiclePos = v.position || v.pos;
                if (!vehiclePos) continue;
                const realPos = positionToAmap(vehiclePos);
                
                if (!realPos || isNaN(realPos.lng) || isNaN(realPos.lat)) {
                    console.error('Invalid vehicle position:', realPos, 'for vehicle:', v.id);
                    continue;
                }
                
                if (vehicleMarker) {
                    // 标记已存在，只更新位置（平滑移动）
                    vehicleMarker.setPosition([realPos.lng, realPos.lat]);
                } else {
                    // 新车辆，创建标记
                    vehicleMarker = new AMap.Marker({
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
                    mapMarkers.set(vehicleKey, vehicleMarker);
                }
                
                // 更新动画路径（如果路径变化）
                const lastVehicle = lastDrawnState.vehicles.get(v.id);
                const pathChanged = !lastVehicle || 
                    JSON.stringify(lastVehicle.complete_path) !== JSON.stringify(v.complete_path);
                
                if (pathChanged && v.complete_path && v.complete_path.length > 1) {
                    animateVehicle(v);
                }
                
                lastDrawnState.vehicles.set(v.id, { ...v });
            } catch (error) {
                console.error('Error updating vehicle marker:', error);
            }
        }
    }
}

// 清除所有状态（用于重置模拟）
function clearAllMapState() {
    clearMapMarkers();
    clearMapPolylines();
    lastDrawnState = {
        tasks: new Map(),
        vehicles: new Map(),
        stations: new Map(),
        warehouse: null
    };
}

// 在真实地图上绘制场景（旧版本，保留用于兼容）
function drawRealMapScene(state) {
    // 清除旧的标记和路径
    clearMapMarkers();
    clearMapPolylines();
    
    // 绘制仓库
    if (state.warehouse_position) {
        try {
            const realPos = positionToAmap(state.warehouse_position);
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
                const realPos = positionToAmap(stationPos);
                
                if (realPos && !isNaN(realPos.lng) && !isNaN(realPos.lat)) {
                    const stationMarker = new AMap.Marker({
                        position: [realPos.lng, realPos.lat],
                        icon: new AMap.Icon({
                            size: new AMap.Size(25, 25),
                            image: 'https://a.amap.com/jsapi_demos/static/demo-center/icons/poi-marker-default.png',
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
                const realPos = positionToAmap(taskPos);
                
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
                    const pathCoords = completePath.map(p => pathPointToAmap(p)).filter(Boolean);
                    
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
                const realPos = positionToAmap(vehiclePos);
                
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

	ctx.fillStyle = '#0f172a';
	ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Canvas 底图优先使用后端分析OSM路网
    if (osmOverlayGeoJson && osmOverlayBounds) {
        for (const feature of osmOverlayGeoJson.features) {
            if (feature?.geometry?.type !== 'LineString') continue;
            const coords = feature.geometry.coordinates || [];
            if (coords.length < 2) continue;

            const highway = feature?.properties?.highway || '';
            const isMainRoad = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary'].includes(highway);

            ctx.beginPath();
            const p0 = geoToCanvas(coords[0][0], coords[0][1]);
            ctx.moveTo(p0.x + canvasOffsetX, p0.y + canvasOffsetY);
            for (let i = 1; i < coords.length; i++) {
                const p = geoToCanvas(coords[i][0], coords[i][1]);
                ctx.lineTo(p.x + canvasOffsetX, p.y + canvasOffsetY);
            }
            ctx.strokeStyle = isMainRoad ? 'rgba(239,68,68,0.55)' : 'rgba(148,163,184,0.30)';
            ctx.lineWidth = isMainRoad ? 1.4 : 0.8;
            ctx.stroke();
        }
    }

	// 绘制仓库（中央仓库）
	if (state.warehouse_position) {
		const w = entityPosToCanvas(state.warehouse_position);
		
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
			const p = entityPosToCanvas(stationPos);
			
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
			const p = entityPosToCanvas(taskPos);
			
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
				
				const start = canvasPathPoint(completePath[0]);
				ctx.moveTo(start.x, start.y);
				
				for (let i = 1; i < completePath.length; i++) {
					const point = canvasPathPoint(completePath[i]);
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
			const pv = entityPosToCanvas(vehiclePos);
			
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
				
				const start = canvasPathPoint(v.complete_path[0]);
				ctx.moveTo(start.x, start.y);
				
				for (let i = 1; i < v.complete_path.length; i++) {
					const pt = canvasPathPoint(v.complete_path[i]);
					ctx.lineTo(pt.x, pt.y);
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

// 车辆平滑动画（rAF 线性插値，修改版）
// 替代原 setInterval 实现，配合 WebSocket 1次/s 的推送，在帧间实现光滑移动
function animateVehicle(vehicle) {
    if (!map || !vehicle.complete_path || vehicle.complete_path.length < 2) return;

    // 取消之前的 rAF
    const existingAnim = vehicleAnimations.get(vehicle.id);
    if (existingAnim && existingAnim.rafId) cancelAnimationFrame(existingAnim.rafId);

    const path = vehicle.complete_path;
    const marker = mapMarkers.get(`vehicle_${vehicle.id}`);
    if (!marker) return;

    // 计算每段长度（度数转 km 语义上仅用于比例）
    const segLengths = [];
    let totalLen = 0;
    for (let i = 0; i < path.length - 1; i++) {
        const [ax, ay] = [path[i].x ?? path[i][0], path[i].y ?? path[i][1]];
        const [bx, by] = [path[i+1].x ?? path[i+1][0], path[i+1].y ?? path[i+1][1]];
        const d = Math.hypot(bx - ax, by - ay);
        segLengths.push(d);
        totalLen += d;
    }
    if (totalLen < 1e-9) return;

    // 总动画时间：基于 WebSocket 刷新周期 (1s)
    const totalDurationMs = Math.max(900, segLengths.length * 200);
    const startTime = performance.now();

    function tick(now) {
        const elapsed = now - startTime;
        const t = Math.min(1, elapsed / totalDurationMs);  // [0,1]

        // 当前应大 cumulative 距离
        let target = t * totalLen;
        let cursor = 0;
        for (let i = 0; i < segLengths.length; i++) {
            if (target <= cursor + segLengths[i]) {
                const local = (target - cursor) / (segLengths[i] || 1);
                const [ax, ay] = [path[i].x ?? path[i][0], path[i].y ?? path[i][1]];
                const [bx, by] = [path[i+1].x ?? path[i+1][0], path[i+1].y ?? path[i+1][1]];
                const cx = ax + (bx - ax) * local;
                const cy = ay + (by - ay) * local;
                const realPos = wgs84ToGcj02(cx, cy);
                marker.setPosition([realPos.lng, realPos.lat]);
                break;
            }
            cursor += segLengths[i];
        }

        if (t < 1) {
            const rafId = requestAnimationFrame(tick);
            vehicleAnimations.set(vehicle.id, { rafId });
        } else {
            vehicleAnimations.delete(vehicle.id);
        }
    }

    const rafId = requestAnimationFrame(tick);
    vehicleAnimations.set(vehicle.id, { rafId });
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
			const battPct = (v.battery_percentage ?? (v.battery / v.max_battery * 100)).toFixed(1);
			const typeLabel = v.vehicle_type ? `[${v.vehicle_type}]` : '';
			const progressInfo = vehiclePathProgress.get(v.id);
			const progressText = progressInfo ? `| 路径进度: ${(v.path_progress * 100).toFixed(0)}%` : '';
			div.innerHTML = `
				<strong>车辆#${v.id} ${typeLabel}</strong>
				<p>状态：${vehicleStatusText(v.status)} | 电量：${battPct}% | 载重：${v.current_load.toFixed(1)}/${v.max_load}kg ${progressText}</p>
				<p>总行驶：${(v.total_distance_traveled || 0).toFixed(0)}m | 充电站：${v.charging_station_id || '无'}</p>
			`;
			vehicleStatusList.appendChild(div);
		}
	}

	// 更新图表
	if (typeof updateCharts === 'function') updateCharts(state);

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
			const waitingIds = (s.waiting_queue || []).join(', ') || '无';
			div.innerHTML = `
				<strong>充电站${s.id}</strong>
				<p>充电框 ${s.capacity} | 充电中: ${s.charging_vehicles.length} | 排队: ${(s.waiting_queue || []).length}</p>
				<p>当前负荷: ${(s.load_pressure * 100).toFixed(0)}% | 排队车辆: ${waitingIds}</p>
			`;
			stationList.appendChild(div);
		}
	}
}

// ============================================================
// Chart.js 历史数据图表模块
// ============================================================

const CHART_MAX_POINTS = 60;  // 最多保留最近60秒数据

const chartData = {
    labels:         [],
    completionRate: [],
    utilization:    [],
    totalScore:     [],
    strategyNames:  [],
};

let chartsInitialized = false;
let completionRateChart, utilizationChart, totalScoreChart, strategyTimelineChart;

const CHART_COLORS = {
    blue:   'rgba(56, 189, 248, 0.85)',
    green:  'rgba(16, 185, 129, 0.85)',
    amber:  'rgba(245, 158, 11, 0.85)',
    purple: 'rgba(139, 92, 246, 0.85)',
    gridLine: 'rgba(255,255,255,0.08)',
    tickColor: '#94a3b8',
};

function makeChartDefaults(label, color, data) {
    return {
        type: 'line',
        data: {
            labels: chartData.labels,
            datasets: [{
                label,
                data,
                borderColor: color,
                backgroundColor: color.replace('0.85', '0.15'),
                borderWidth: 2,
                pointRadius: 2,
                fill: true,
                tension: 0.4,
            }],
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { labels: { color: '#e2e8f0', font: { size: 11 } } },
            },
            scales: {
                x: {
                    ticks: { color: CHART_COLORS.tickColor, maxTicksLimit: 6, font: { size: 10 } },
                    grid:  { color: CHART_COLORS.gridLine },
                },
                y: {
                    ticks: { color: CHART_COLORS.tickColor, font: { size: 10 } },
                    grid:  { color: CHART_COLORS.gridLine },
                    min: 0,
                },
            },
        },
    };
}

function initCharts() {
    if (chartsInitialized) return;
    if (typeof Chart === 'undefined') return;
    Chart.defaults.color = '#e2e8f0';

    completionRateChart = new Chart(
        document.getElementById('completionRateChart'),
        makeChartDefaults('任务完成率 (%)', CHART_COLORS.green, chartData.completionRate)
    );
    utilizationChart = new Chart(
        document.getElementById('utilizationChart'),
        makeChartDefaults('车辆利用率 (%)', CHART_COLORS.blue, chartData.utilization)
    );
    totalScoreChart = new Chart(
        document.getElementById('totalScoreChart'),
        makeChartDefaults('累计得分', CHART_COLORS.amber, chartData.totalScore)
    );

    // 策略时间线（梯形图）
    strategyTimelineChart = new Chart(
        document.getElementById('strategyTimelineChart'),
        {
            type: 'bar',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: '策略点数',
                    data: chartData.completionRate,
                    backgroundColor: CHART_COLORS.purple,
                    borderRadius: 3,
                }],
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { labels: { color: '#e2e8f0', font: { size: 11 } } },
                },
                scales: {
                    x: { ticks: { color: CHART_COLORS.tickColor, maxTicksLimit: 6, font: { size: 10 } }, grid: { color: CHART_COLORS.gridLine } },
                    y: { ticks: { color: CHART_COLORS.tickColor, font: { size: 10 } }, grid: { color: CHART_COLORS.gridLine }, min: 0, max: 100 },
                },
            },
        }
    );

    chartsInitialized = true;
}

function updateCharts(state) {
    if (!chartsInitialized) initCharts();
    if (!chartsInitialized) return;

    // 时间标签
    const now = new Date();
    const timeLabel = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;

    // 添加数据点
    chartData.labels.push(timeLabel);
    chartData.completionRate.push(((state.completion_rate || 0) * 100));
    chartData.utilization.push(((state.vehicle_utilization || 0) * 100));
    chartData.totalScore.push(state.total_score || 0);

    // 保留最多 CHART_MAX_POINTS 个点
    if (chartData.labels.length > CHART_MAX_POINTS) {
        chartData.labels.shift();
        chartData.completionRate.shift();
        chartData.utilization.shift();
        chartData.totalScore.shift();
    }

    // 注意：Chart.js 共享 labels 引用，由亖界的 labels 数组维护，直接 update() 即可
    completionRateChart.update();
    utilizationChart.update();
    totalScoreChart.update();
    strategyTimelineChart.update();
}

// 折叠面板交互
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('chartsPanelToggle');
    const content = document.getElementById('chartsContent');
    const icon = document.getElementById('chartToggleIcon');
    if (toggle && content) {
        toggle.addEventListener('click', () => {
            const collapsed = content.classList.toggle('collapsed');
            if (icon) icon.textContent = collapsed ? '▶' : '▼';
            if (!collapsed && !chartsInitialized) initCharts();
        });
    }

    // 默认尝试初始化图表（Chart.js 已以 CDN 引入）
    setTimeout(initCharts, 500);
});
