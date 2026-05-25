// 全局元素变量
let canvas, ctx, startButton, stopButton, toggleMapButton;
let timestampDisplay, totalScoreDisplay, taskCompletionRateDisplay, vehicleUtilizationDisplay;
let vehicleStatusList, taskList, stationList;
let currentStrategyDisplay, strategyReasonDisplay;
let simulationStatusDisplay;

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
// 2D Canvas 当前画面的经纬度外接矩形（根据 state 动态算出，保证车/仓库/充电站都在可视区内）
let sceneBounds = null;

// 后端 /api/graph 拉回来的 NetworkX 路网（只在 2D Canvas 模式用）：
//   { nodes: [[id, lng, lat], ...], edges: [[uIdx, vIdx], ...], bounds: {...} }
let roadGraph = null;
let roadGraphLoading = false;

// 路网 + 网格的 offscreen 缓存。路网/窗口尺寸/平移不变就永远不重画，
// 主画布 RAF 只做 drawImage（O(1)），这样车辆动画才能稳定 60 FPS。
let roadGraphCache = {
    canvas: null,
    // 缓存生效时的环境快照（任一变化就重建）：
    width: 0,
    height: 0,
    offsetX: 0,
    offsetY: 0,
    nodeCount: 0,
    edgeCount: 0,
    boundsKey: '',
};

// 2D Canvas 每辆车的动画状态：
//   path     : [[lng, lat], ...]  从"上一帧车显示位置"→"本 tick 途径节点"→"最新位置"
//   segLens  : 每段长度（米），用于按累计距离插值
//   totalLen : 所有段长之和
//   startTs  : tween 起始时间戳（performance.now）
//   duration : tween 时长 ms
const canvasVehicleAnimState = new Map();
let canvasRenderLoopRaf = null;

// WebSocket连接
// 固定使用localhost:8000/ws，确保与后端服务正确连接
const WS_URL = 'ws://localhost:8000/ws';
const API_BASE = 'http://localhost:8000/api';
console.log('WebSocket URL:', WS_URL);
let websocket = null;
let currentSimulationState = null;
let simulationEnded = false;
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

// 渲染相关参数（由后端 /simulation/status 的 render 字段填充）
let renderConfig = {
    speed_factor:          120,
    tick_interval:         1.0,
    marker_tween_ms:       900,
    marker_tween_adaptive: true,
};

async function refreshSimulationStatus() {
    try {
        const status = await apiRequest('/simulation/status');
        if (status && status.render) {
            renderConfig = Object.assign({}, renderConfig, status.render);
        }
        if (simulationStatusDisplay) {
            if (status.running) {
                const elapsed = Number(status.sim_seconds_elapsed || 0);
                const maxSec = status.max_sim_seconds;
                const elapsedStr = formatSimSeconds(elapsed);
                const limitStr = maxSec ? ` / 上限 ${formatSimSeconds(maxSec)}` : '（无限时）';
                simulationStatusDisplay.textContent = `运行中 [${status.strategy}] 仿真时长 ${elapsedStr}${limitStr}`;
            } else {
                simulationStatusDisplay.textContent = '未启动';
            }
        }
    } catch (error) {
        console.warn('获取仿真状态失败:', error);
    }
}

function formatSimSeconds(sec) {
    sec = Math.max(0, Math.round(Number(sec) || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}h${m}m${s}s`;
    if (m > 0) return `${m}m${s}s`;
    return `${s}s`;
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

// 从 state 里所有实体位置算一个 WGS84 经纬度外接矩形，用于 2D Canvas 投影
function computeSceneBounds(state) {
    if (!state) return null;
    let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
    const consider = (pos) => {
        if (!pos) return;
        const lng = Number(pos.x);
        const lat = Number(pos.y);
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) return;
        if (lng < minLng) minLng = lng;
        if (lng > maxLng) maxLng = lng;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
    };
    consider(state.warehouse_position);
    for (const s of (state.charging_stations || [])) consider(s.position || s.pos);
    for (const t of (state.tasks || [])) consider(t.position || t.pos);
    for (const v of (state.vehicles || [])) consider(v.position || v.pos);
    if (!Number.isFinite(minLng) || !Number.isFinite(minLat)) return null;
    // 单点也给个小 span，避免除零
    if (maxLng - minLng < 1e-6) { minLng -= 0.005; maxLng += 0.005; }
    if (maxLat - minLat < 1e-6) { minLat -= 0.005; maxLat += 0.005; }
    return { minLng, maxLng, minLat, maxLat };
}

// 当前 2D Canvas 投影使用的 bounds。优先级：
//   1) 后端 NetworkX 路网（nx.draw 风格，路网完整覆盖）
//   2) 动态 sceneBounds（从实体位置算出）
//   3) 已废弃的 AMap OSM 叠加层（不再使用）
function activeCanvasBounds() {
    if (roadGraph && roadGraph.bounds) return roadGraph.bounds;
    return sceneBounds;
}

// ---- 2D Canvas 车辆动画：RAF 循环 + 按累计距离沿折线插值 ----
//
// 收到一次新的 state（默认 1s 一次）就刷新每辆车的 anim：
//   path 的首点 = 当前显示位置（保证视觉连续，不会回跳），
//   中间 = tick_waypoints[1..end-1]（本 tick 走过的图节点），
//   尾点 = 后端汇报的最新位置。
// 之后 RAF 每帧按 (now - startTs)/duration 沿 path 做累计距离插值，
// 就能让车沿着真正的路网折线平滑走过去。
function _latLngBetween(lngA, latA, lngB, latB) {
    const midLat = (latA + latB) * 0.5;
    const mPerDegLat = 111_320;
    const mPerDegLng = 111_320 * Math.cos((midLat * Math.PI) / 180);
    const dx = (lngB - lngA) * mPerDegLng;
    const dy = (latB - latA) * mPerDegLat;
    return Math.hypot(dx, dy);
}

function getCanvasVehicleDisplayLngLat(v, now) {
    const anim = canvasVehicleAnimState.get(v.id);
    if (!anim || !anim.path || anim.path.length === 0) {
        return { lng: Number(v.position?.x), lat: Number(v.position?.y) };
    }
    const path = anim.path;
    const t = Math.min(1, (now - anim.startTs) / Math.max(1, anim.duration));
    const target = t * anim.totalLen;
    let acc = 0;
    for (let i = 0; i < anim.segLens.length; i++) {
        if (acc + anim.segLens[i] >= target) {
            const localT = anim.segLens[i] > 1e-9 ? (target - acc) / anim.segLens[i] : 0;
            const a = path[i], b = path[i + 1];
            return { lng: a[0] + (b[0] - a[0]) * localT, lat: a[1] + (b[1] - a[1]) * localT };
        }
        acc += anim.segLens[i];
    }
    const last = path[path.length - 1];
    return { lng: last[0], lat: last[1] };
}

function refreshCanvasVehicleAnimState(state) {
    if (!state || !Array.isArray(state.vehicles)) return;
    const now = performance.now();
    // tween 长度 = 一个后端 tick（默认 1s）。目标：老 tween 正好在新 state 到来时收尾。
    const tickIvMs = Math.max(100, (Number(renderConfig.tick_interval) || 1) * 1000);

    for (const v of state.vehicles) {
        const targetLng = Number(v.position?.x);
        const targetLat = Number(v.position?.y);
        if (!Number.isFinite(targetLng) || !Number.isFinite(targetLat)) continue;

        // 1) 先按后端给的 tick_waypoints 搭出本 tick 的折线骨架
        const base = [];
        if (Array.isArray(v.tick_waypoints) && v.tick_waypoints.length >= 2) {
            for (const w of v.tick_waypoints) {
                const lng = Number(w?.x), lat = Number(w?.y);
                if (Number.isFinite(lng) && Number.isFinite(lat)) base.push([lng, lat]);
            }
        }

        // 2) **关键**：新 tween 的**起点**直接用"当前屏幕上显示的位置"，
        //    而不是后端告诉我们的 tick_waypoints[0]。
        //    这样 WebSocket 有抖动（早到 / 晚到几十毫秒）时，也不会在交接瞬间把车
        //    瞬移到 tick_waypoints[0] 上——肉眼看到的就是"前后摇一晃"。
        //    前端显示位置在 WS 准点时 ≈ tick_waypoints[0]，抖动时可能稍前或稍后；
        //    用 disp 当新 tween 起点，视觉完全连贯。
        const prev = canvasVehicleAnimState.get(v.id);
        const disp = prev
            ? getCanvasVehicleDisplayLngLat(v, now)
            : (base[0] ? { lng: base[0][0], lat: base[0][1] } : { lng: targetLng, lat: targetLat });

        const path = [[disp.lng, disp.lat]];
        // 把 tick_waypoints[1..] 依次追加（tick_waypoints[0] 就是本 tick 起点，
        // 我们用 disp 替代了它，所以从 index 1 开始；这样中间节点全都在，
        // 车会严格沿路网折线走）
        if (base.length >= 2) {
            for (let i = 1; i < base.length; i++) path.push(base[i]);
            // 尾点对齐到后端最新汇报的位置，避免浮点漂移
            path[path.length - 1] = [targetLng, targetLat];
        } else {
            // 车这一 tick 没动 / 没折线：目标就是 disp 本身
            path.push([targetLng, targetLat]);
        }

        const segLens = [];
        let totalLen = 0;
        for (let i = 1; i < path.length; i++) {
            const L = _latLngBetween(path[i-1][0], path[i-1][1], path[i][0], path[i][1]);
            segLens.push(L);
            totalLen += L;
        }

        canvasVehicleAnimState.set(v.id, {
            path, segLens, totalLen,
            startTs: now, duration: tickIvMs,
        });
    }

    const alive = new Set(state.vehicles.map(v => v.id));
    for (const id of canvasVehicleAnimState.keys()) {
        if (!alive.has(id)) canvasVehicleAnimState.delete(id);
    }
}

function startCanvasRenderLoop() {
    if (canvasRenderLoopRaf != null) return;
    const loop = () => {
        // 切回 AMap 时自动停
        if (useRealMap) { canvasRenderLoopRaf = null; return; }
        if (currentSimulationState && canvas && ctx) {
            drawCanvasScene(currentSimulationState);
        }
        canvasRenderLoopRaf = requestAnimationFrame(loop);
    };
    canvasRenderLoopRaf = requestAnimationFrame(loop);
}

function stopCanvasRenderLoop() {
    if (canvasRenderLoopRaf != null) {
        cancelAnimationFrame(canvasRenderLoopRaf);
        canvasRenderLoopRaf = null;
    }
}

function cancelVehicleTweens() {
    for (const anim of vehicleAnimations.values()) {
        if (anim && anim.rafId) cancelAnimationFrame(anim.rafId);
    }
    vehicleAnimations.clear();
}

function resetSimulationEndedState() {
    simulationEnded = false;
    cancelVehicleTweens();
    canvasVehicleAnimState.clear();
}

function freezeSimulationRendering(reason, simSecondsElapsed) {
    simulationEnded = true;
    cancelVehicleTweens();
    stopCanvasRenderLoop();
    canvasVehicleAnimState.clear();

    // 真实地图模式下，把 marker 直接对齐到后端最后一帧位置，避免 tween 继续摇摆。
    if (useRealMap && currentSimulationState && Array.isArray(currentSimulationState.vehicles)) {
        for (const v of currentSimulationState.vehicles) {
            const marker = mapMarkers.get(`vehicle_${v.id}`);
            if (!marker || !v.position) continue;
            const p = positionToAmap(v.position);
            if (p && isFinite(p.lng) && isFinite(p.lat)) {
                marker.setPosition([p.lng, p.lat]);
            }
        }
    }

    if (!useRealMap && currentSimulationState && canvas && ctx) {
        drawCanvasScene(currentSimulationState);
    }

    if (simulationStatusDisplay) {
        const reasonText = reason ? `（${reason}）` : '';
        const elapsedText = simSecondsElapsed ? `，仿真时长 ${formatSimSeconds(simSecondsElapsed)}` : '';
        simulationStatusDisplay.textContent = `模拟结束${reasonText}${elapsedText}`;
    }
    if (startButton) startButton.disabled = true;
    if (stopButton) stopButton.disabled = true;
}

// 拉取后端的 NetworkX 路网（只在 canvas 模式需要）
async function ensureRoadGraphLoaded() {
    if (roadGraph || roadGraphLoading) return;
    roadGraphLoading = true;
    try {
        const resp = await fetch(`${API_BASE}/graph`, { cache: 'no-cache' });
        if (!resp.ok) throw new Error(`status=${resp.status}`);
        const data = await resp.json();
        if (data && Array.isArray(data.nodes) && Array.isArray(data.edges)) {
            roadGraph = data;
            console.log(`[RoadGraph] 已加载：${data.nodes.length} 节点 / ${data.edges.length} 边`);
            if (currentSimulationState && !useRealMap) {
                drawScene(currentSimulationState);
            }
        }
    } catch (e) {
        console.warn('[RoadGraph] 拉取 /api/graph 失败（2D Canvas 将只画实体）：', e);
    } finally {
        roadGraphLoading = false;
    }
}

// 把一个 WGS84 (lng, lat) 投影到 canvas 像素。保持纵横比，居中，留 pad 的白边。
function projectLngLat(lng, lat) {
    const b = activeCanvasBounds();
    if (!b || !canvas) return { x: (canvas ? canvas.width : 0) / 2, y: (canvas ? canvas.height : 0) / 2 };
    const pad = 40;
    const drawableW = Math.max(1, canvas.width - pad * 2);
    const drawableH = Math.max(1, canvas.height - pad * 2);
    const lngSpan = Math.max(1e-9, b.maxLng - b.minLng);
    const latSpan = Math.max(1e-9, b.maxLat - b.minLat);
    // lat 方向要按纬度折算 lng 的"米尺度"，避免东西方向被视觉压扁
    const latMid = (b.minLat + b.maxLat) * 0.5;
    const lngMetersPerDeg = Math.cos((latMid * Math.PI) / 180) * 111_320;
    const latMetersPerDeg = 111_320;
    const widthMeters = lngSpan * lngMetersPerDeg;
    const heightMeters = latSpan * latMetersPerDeg;
    const scale = Math.min(drawableW / widthMeters, drawableH / heightMeters); // px per meter
    const cxLng = (b.minLng + b.maxLng) * 0.5;
    const cyLat = (b.minLat + b.maxLat) * 0.5;
    const x = canvas.width / 2 + (lng - cxLng) * lngMetersPerDeg * scale;
    const y = canvas.height / 2 - (lat - cyLat) * latMetersPerDeg * scale;
    return { x, y };
}

function entityPosToCanvas(pos) {
    if (!pos) {
        return { x: canvas.width / 2, y: canvas.height / 2 };
    }
    // 2D Canvas **只用 WGS84**：/api/graph 的节点坐标是 WGS84，车辆/仓库/充电站/任务的 .x/.y 也是 WGS84。
    // 后端附带的 gcj_lng/gcj_lat 只给 AMap 用，canvas 里用它会和路网差 ~500m（GCJ02 偏移），看起来就是
    // "车在路旁边"。
    const lng = Number(pos.x);
    const lat = Number(pos.y);
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
        return { x: canvas.width / 2, y: canvas.height / 2 };
    }
    const p = projectLngLat(lng, lat);
    return { x: p.x + canvasOffsetX, y: p.y + canvasOffsetY };
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

function isOsmOverlayGcj02() {
    const features = osmOverlayGeoJson && Array.isArray(osmOverlayGeoJson.features)
        ? osmOverlayGeoJson.features
        : [];
    for (const feature of features.slice(0, 20)) {
        const cs = String(feature?.properties?.coord_system || '').toLowerCase();
        if (cs.includes('gcj')) return true;
        if (cs.includes('wgs')) return false;
    }
    return false;
}

function drawOsmOverlayOnAmap() {
    if (!map || !osmOverlayGeoJson) return;
    clearOsmAmapOverlay();

    // 检查是否为主干路模式（根据文件名或特征数量判断）
    const isMainRoadsMode = osmOverlayGeoJson.features.length < 5000;
    const overlayIsGcj02 = isOsmOverlayGcj02();
    
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
        
        // frontend 里的 osm_main_roads / amap_overlay 文件已经是 GCJ-02；
        // 只有未标注或明确 WGS84 的 GeoJSON 才转换，避免二次偏移。
        const amapPath = (overlayIsGcj02 ? path : path.map(p => pathPointToAmap(p)))
            .filter(p => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));
        if (amapPath.length < 2) continue;

        const polyline = new AMap.Polyline({
            path: amapPath,
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

function markerLabelText(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function amapBadgeContent({ color, label, symbol = '', size = 22, ring = '#ffffff' }) {
    const safeLabel = markerLabelText(label);
    const safeSymbol = markerLabelText(symbol);
    const fontSize = size >= 28 ? 14 : 12;
    return `
        <div style="position:relative; transform:translate(-50%, -50%); text-align:center; pointer-events:auto;">
            <div style="
                width:${size}px; height:${size}px; border-radius:50%;
                background:${color};
                border:2px solid ${ring};
                box-shadow:0 2px 8px rgba(0,0,0,.35), 0 0 0 2px rgba(15,23,42,.18);
                display:flex; align-items:center; justify-content:center;
                color:#0f172a; font-weight:800; font-size:${fontSize}px;
                line-height:1;">
                ${safeSymbol}
            </div>
            <div style="
                position:absolute; left:50%; top:${size + 3}px; transform:translateX(-50%);
                white-space:nowrap; padding:1px 5px; border-radius:4px;
                background:rgba(15,23,42,.82); color:#e2e8f0;
                border:1px solid rgba(226,232,240,.55);
                font-size:11px; line-height:16px; font-weight:700;">
                ${safeLabel}
            </div>
        </div>
    `;
}

function createAmapBadgeMarker(position, opts) {
    const size = opts.size || 22;
    return new AMap.Marker({
        position,
        content: amapBadgeContent(opts),
        title: opts.title || opts.label || '',
        offset: new AMap.Pixel(0, 0),
        anchor: 'center',
        zIndex: opts.zIndex || 100,
    });
}

function vehicleStatusColor(status) {
    switch (status) {
        case 'idle': return colors.vehicleIdle;
        case 'moving_to_task':
        case 'moving_to_node': return colors.vehicleMovingToTask;
        case 'moving_to_warehouse': return colors.vehicleReturningToWarehouse;
        case 'moving_to_charge': return colors.vehicleMovingToCharge;
        case 'charging':
        case 'waiting_charge': return colors.vehicleCharging;
        case 'stranded': return '#ef4444';
        default: return colors.vehicleIdle;
    }
}

function taskStatusColor(status) {
    switch (status) {
        case 'pending': return colors.taskPending;
        case 'assigned':
        case 'in_progress': return colors.taskDelivering;
        case 'completed': return colors.taskCompleted;
        case 'timeout': return colors.taskTimeout;
        default: return colors.taskPending;
    }
}

function stationColor(station) {
    if (station && station.queue_count > station.capacity) return colors.stationQueue;
    if (station && station.available_slots === 0) return colors.stationFull;
    return colors.station;
}

// 全局状态存储
let taskCompletePaths = new Map();
let vehiclePathProgress = new Map();
let completedTaskScores = new Map();

// 根据车辆状态获取颜色
function vehicleColor(status) {
	switch (status) {
		case 'idle': return colors.vehicleIdle;
		case 'moving_to_task': return colors.vehicleMovingToTask;
		case 'moving_to_node': return colors.vehicleMovingToTask;
		case 'moving_to_warehouse': return colors.vehicleReturningToWarehouse;
		case 'moving_to_charge': return colors.vehicleMovingToCharge;
		case 'charging': return colors.vehicleCharging;
		case 'waiting_charge': return '#fb923c';
		case 'stranded': return '#dc2626';
		default: return '#fff';
	}
}

// 获取车辆状态显示文本
function vehicleStatusText(status) {
	switch (status) {
		case 'idle': return '空闲';
		case 'moving_to_task': return '前往任务点';
		case 'moving_to_node': return '前往特殊节点';
		case 'moving_to_warehouse': return '返回仓库';
		case 'moving_to_charge': return '前往充电站';
		case 'charging': return '充电中 ⚡';
		case 'waiting_charge': return '排队充电 ⏳';
		case 'stranded': return '抛锚 ⚠️（没电了）';
		default: return status;
	}
}

// 根据任务状态获取颜色
function taskColor(status) {
	switch (status) {
		case 'pending': return colors.taskPending;
		case 'assigned':
		case 'in_progress': return colors.taskDelivering;
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

    // AMap 挂了 → 直接进 canvas：拉路网 + 起 RAF 循环
    ensureRoadGraphLoaded();
    startCanvasRenderLoop();
    
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
                const rawCenter = {
                    lng: (osmOverlayBounds.minLng + osmOverlayBounds.maxLng) / 2,
                    lat: (osmOverlayBounds.minLat + osmOverlayBounds.maxLat) / 2,
                };
                const center = isOsmOverlayGcj02()
                    ? rawCenter
                    : wgs84ToGcj02(rawCenter.lng, rawCenter.lat);
                map.setCenter([center.lng, center.lat]);
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
                resetSimulationEndedState();
                startButton.disabled = false;
                stopButton.disabled = true;
                
                // 更新状态显示
                if (simulationStatusDisplay) {
                    simulationStatusDisplay.textContent = '已重置，点击"启动模拟"开始新一轮';
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
                
                alert('模拟已重置');
            } catch (e) {
                console.error('重置仿真失败:', e);
                alert('重置仿真失败: ' + e.message);
            }
        });
    }
    toggleMapButton.addEventListener('click', toggleMapMode);

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
        stopCanvasRenderLoop();
        if (currentSimulationState) {
            drawScene(currentSimulationState);
        }
    } else {
        document.getElementById('mapContainer').style.display = 'none';
        canvas.style.display = 'block';
        toggleMapButton.textContent = '切换到真实地图';
        // 首次切到 canvas 时，异步把后端 NetworkX 路网拉下来当底图
        ensureRoadGraphLoaded();
        if (currentSimulationState) {
            refreshCanvasVehicleAnimState(currentSimulationState);
            drawScene(currentSimulationState);
        }
        startCanvasRenderLoop();
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
    resetSimulationEndedState();
    
    console.log('Starting simulation...');

    const startResult = await apiRequest('/simulation/start', {
        method: 'POST',
        body: JSON.stringify({})
    });

    console.log('Start simulation result:', startResult);

    if (!startResult.success) {
        throw new Error(startResult.message || '启动仿真失败');
    }

    if (simulationStatusDisplay) {
        const strat = startResult.strategy || 'nearest_task';
        const tcount = startResult.tasks_count || 0;
        const vcount = startResult.vehicles_count || 0;
        simulationStatusDisplay.textContent = `运行中 [${strat}] 车辆 ${vcount} 辆 / 初始任务 ${tcount}`;
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
			try {
				const msg = JSON.parse(evt.data);
				if (!msg) return;

				// 根据后端 websocket_handler 的协议按 type 处理
			switch (msg.type) {
				case 'state_update':
				case 'state_response':
                    if (simulationEnded) {
                        // 仿真结束后后端可能仍维持 websocket 心跳/状态广播；
                        // 前端冻结最后一帧，避免车辆 marker 继续 tween 产生摇摆。
                        break;
                    }
					if (msg.data) {
						currentSimulationState = msg.data;
						updateDashboard(currentSimulationState);
						if (useRealMap) {
							// AMap 模式下没有 RAF 循环，仍然走老的增量绘制路径
							drawScene(currentSimulationState);
						} else {
							// Canvas 模式下 RAF 在 60FPS 重绘，这里只更新 tween 状态，
							// 不再显式调 drawScene —— 之前多调一次会和 RAF 抢主线程，
							// 每秒来一次 state 就是可见的"一卡"。
							refreshCanvasVehicleAnimState(currentSimulationState);
						}
					}
					break;
                case 'simulation_finished':
                    freezeSimulationRendering(
                        msg.data && msg.data.reason,
                        msg.data && msg.data.sim_seconds_elapsed
                    );
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
				// **不要**在这里主动去拉 get_state。
				// 这三种单体事件在 1 个 backend tick 内会被广播很多次
				// （每次 update_position / update_battery / _apply_motion_cost 都会广播
				// 一次 vehicle_update）。以前这里每条都回一个 get_state，拿回 state_response
				// 后 refreshCanvasVehicleAnimState 就会在 1 秒内重建 5~10 次 tween，视觉上
				// 车就会走一小段 → 回一点 → 再走一小段 → …… → 最后一秒整 tick 的 state_update
				// 到来时又一口气瞬移到下一个节点。
				// 整 tick 的 state_update（1Hz）本来就覆盖了所有需要的字段，这些零碎事件直接忽略。
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
		// 随后重绘被选中车辆的路径高亮（跟车实时更新）
		highlightSelectedVehicleRoute(state);
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
                const warehouseMarker = createAmapBadgeMarker([realPos.lng, realPos.lat], {
                    color: colors.warehouse,
                    label: '仓库',
                    symbol: '仓',
                    size: 30,
                    title: '中央仓库',
                    zIndex: 180,
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
                    const stationMarker = createAmapBadgeMarker([realPos.lng, realPos.lat], {
                        color: stationColor(s),
                        label: `CS${s.id}`,
                        symbol: '⚡',
                        size: 24,
                        title: `充电站${s.id}`,
                        zIndex: 150,
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

            // 已完成的任务：直接从地图上消失，不再重绘图标
            if (t.status === 'completed' || t.status === 'timeout') {
                lastDrawnState.tasks.set(t.id, { ...t });
                continue;
            }

            try {
                const taskPos = t.position || t.pos;
                if (!taskPos) continue;
                const realPos = positionToAmap(taskPos);
                
                if (!realPos || isNaN(realPos.lng) || isNaN(realPos.lat)) {
                    console.error('Invalid task position:', realPos, 'for task:', t.id);
                    continue;
                }
                
                // 绘制任务标记
                const taskMarker = createAmapBadgeMarker([realPos.lng, realPos.lat], {
                    color: taskStatusColor(t.status),
                    label: `#${t.id}`,
                    symbol: t.priority ? String(t.priority) : '',
                    size: 20,
                    title: `任务${t.id}`,
                    zIndex: 120,
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

    // 4. 更新车辆位置（从 marker 当前显示位置平滑插值到后端最新位置，避免乱跳）
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

                if (!vehicleMarker) {
                    vehicleMarker = createAmapBadgeMarker([realPos.lng, realPos.lat], {
                        color: vehicleStatusColor(v.status),
                        label: `V${v.id}`,
                        symbol: '车',
                        size: 28,
                        title: `车辆${v.id}`,
                        zIndex: 200,
                    });
                    vehicleMarker.setMap(map);
                    mapMarkers.set(vehicleKey, vehicleMarker);
                } else {
                    const lastVehicle = lastDrawnState.vehicles.get(v.id);
                    if (!lastVehicle || lastVehicle.status !== v.status) {
                        vehicleMarker.setContent(amapBadgeContent({
                            color: vehicleStatusColor(v.status),
                            label: `V${v.id}`,
                            symbol: '车',
                            size: 28,
                        }));
                    }
                }

                // 平滑移动到新位置：沿后端汇报的"本 tick 折线"(v.tick_waypoints) 走，
                // 节点密集区也不会"直线切弯"；没有折线时退化为直线插值。
                tweenMarkerTo(
                    v.id,
                    vehicleMarker,
                    [realPos.lng, realPos.lat],
                    Number(v.speed) || 0,
                    Array.isArray(v.tick_waypoints) ? v.tick_waypoints : null
                );

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
    if (selectedVehiclePolyline) {
        selectedVehiclePolyline.setMap(null);
        selectedVehiclePolyline = null;
    }
    selectedVehicleId = null;
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

    // 先根据当前 state 动态算一个外接矩形，作为投影基准（不再依赖外部 geojson 必须加载成功）
    sceneBounds = computeSceneBounds(state);

    // 完全没有实体 & 也没有 OSM 底图 → 给个占位
    if (!activeCanvasBounds()) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '14px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('等待仿真数据…', canvas.width / 2, canvas.height / 2);
        return;
    }

    // 底图 = 网格 + 后端 NetworkX 路网。整张一次性从 offscreen 缓存贴上来（drawImage），
    // RAF 每帧只做 O(1) 复制，不会再每秒重描上万条边 → 车辆动画能真的跑到 60 FPS。
    if (roadGraph && roadGraph.nodes.length > 0) {
        drawRoadGraphOnCanvas();
    } else if (!useRealMap) {
        ensureRoadGraphLoaded();
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

			// 注：canvas 里默认不再画任务到仓库/车辆之间的路径线（太乱）。
			// 只有当用户在右侧车辆列表里点了某辆车时，才画那辆车"当前位置→command 目标"的路径。

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
		const now = performance.now();
		for (const v of state.vehicles) {
			const vehiclePos = v.position || v.pos;
			if (!vehiclePos) continue;
			// 用本地 RAF 插值出来的"显示位置"画，避免一秒一跳
			const disp = getCanvasVehicleDisplayLngLat(v, now);
			const pv = entityPosToCanvas(
				Number.isFinite(disp.lng) && Number.isFinite(disp.lat)
					? { x: disp.lng, y: disp.lat }
					: vehiclePos
			);

			// 注：canvas 里默认不画每辆车的完整行驶路径。只有当这辆车被用户选中时，
			// 才会在下方的 drawSelectedVehicleRouteOnCanvas() 里画它的剩余路径。

			// 车辆光晕（缩小版）
			const vehicleColorValue = vehicleColor(v.status);
			const glowGradient = ctx.createRadialGradient(pv.x, pv.y, 0, pv.x, pv.y, 10);
			glowGradient.addColorStop(0, vehicleColorValue.replace(')', ', 0.5)').replace('rgb', 'rgba'));
			glowGradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
			ctx.fillStyle = glowGradient;
			ctx.beginPath();
			ctx.arc(pv.x, pv.y, 10, 0, Math.PI * 2);
			ctx.fill();

			// 车辆主体（小圆点）
			drawShadowedCircle(ctx, pv.x, pv.y, 5, vehicleColorValue, vehicleColorValue.replace(')', ', 0.6)').replace('rgb', 'rgba'));

			// 车辆 ID 小标（贴在圆右上方）
			ctx.fillStyle = '#fff';
			ctx.font = 'bold 9px Arial';
			ctx.textAlign = 'left';
			ctx.textBaseline = 'middle';
			ctx.fillText(`V${v.id}`, pv.x + 7, pv.y - 5);

			// 只有这辆车被选中了才画"电量/载量"详细面板，避免画面被信息面板淹没。
			if (selectedVehicleId === v.id) {
				const panelWidth = 60;
				const panelHeight = 26;
				const panelX = pv.x - panelWidth / 2;
				const panelY = pv.y + 8;

				ctx.fillStyle = 'rgba(0, 0, 0, 0.78)';
				drawRoundedRect(ctx, panelX, panelY, panelWidth, panelHeight, 4);
				ctx.fill();

				const batteryPercent = (v.battery / v.max_battery);
				const batteryColor = batteryPercent > 0.3 ? '#4CAF50' : (batteryPercent > 0.15 ? '#FF9800' : '#F44336');
				drawProgressBar(ctx, panelX + 2, panelY + 2, panelWidth - 4, 9, batteryPercent, batteryColor, 'rgba(255,255,255,0.2)');
				ctx.fillStyle = '#fff';
				ctx.font = '7px Arial';
				ctx.textAlign = 'center';
				ctx.fillText(`🔋${v.battery.toFixed(0)}%`, panelX + panelWidth / 2, panelY + 7);

				const loadPercent = (v.current_load / v.max_load);
				const loadColor = loadPercent < 0.8 ? '#2196F3' : '#F44336';
				drawProgressBar(ctx, panelX + 2, panelY + 13, panelWidth - 4, 9, loadPercent, loadColor, 'rgba(255,255,255,0.2)');
				ctx.fillStyle = '#fff';
				ctx.font = '7px Arial';
				ctx.fillText(`📦${v.current_load.toFixed(0)}/${v.max_load}`, panelX + panelWidth / 2, panelY + 21);
			}
		}
	}

	// 选中某辆车时画它的剩余路径（从车当前显示位置 → command 目标节点）
	drawSelectedVehicleRouteOnCanvas(state);

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

// 在 2D Canvas 上画"被选中那辆车"的剩余路径：从车当前显示位置 → command 目标节点。
//
// 关键点：后端在一个 tick 内可能会跨多段路（A→B→C→mid_CD），所以前端实际显示的
// 车可能还在 A→B 段上，但 `v.remaining_route` 是以 **当前 tick 结束位置**（mid_CD）
// 为起点算的。直接 `disp → remaining_route[0]` 会变成"一条直线切过 B 和 C"，
// 正好对应用户看到的"直接直线指向 C"。
//
// 正确做法：把本 tick 还没走完的 waypoints 先接上，再拼上 remaining_route[1..]。
function drawSelectedVehicleRouteOnCanvas(state) {
    if (selectedVehicleId == null || !state || !Array.isArray(state.vehicles)) return;
    const v = state.vehicles.find(vv => vv.id === selectedVehicleId);
    if (!v) return;

    const route = Array.isArray(v.remaining_route) ? v.remaining_route : [];
    if (route.length < 1) return;

    const now = performance.now();
    const disp = getCanvasVehicleDisplayLngLat(v, now);

    // 1) 收集"本 tick 还没走完的"waypoints（严格沿路网，不切弯）
    const anim = canvasVehicleAnimState.get(v.id);
    const aheadInTick = []; // [[lng,lat], ...] —— 不含 disp 本身
    if (anim && anim.path && anim.segLens && anim.totalLen > 0) {
        const t = Math.min(1, Math.max(0, (now - anim.startTs) / Math.max(1, anim.duration)));
        const target = t * anim.totalLen;
        let acc = 0;
        let curSeg = -1;
        for (let i = 0; i < anim.segLens.length; i++) {
            if (acc + anim.segLens[i] >= target) { curSeg = i; break; }
            acc += anim.segLens[i];
        }
        if (curSeg < 0) curSeg = anim.segLens.length - 1;
        // 当前车身在 path[curSeg] → path[curSeg+1] 之间，接下来要依次经过：
        //   path[curSeg+1], path[curSeg+2], ..., path[last]
        for (let i = curSeg + 1; i < anim.path.length; i++) {
            aheadInTick.push(anim.path[i]);
        }
    }

    // 2) 把 remaining_route 接在 aheadInTick 后面。
    //    remaining_route[0] = 后端汇报的 v.position（tick 结束位置），
    //    通常 == anim.path[last] == aheadInTick 的最后一个点，所以跳过避免重复。
    const tail = [];
    for (let i = 1; i < route.length; i++) {
        const p = route[i];
        const lng = Number(p?.x), lat = Number(p?.y);
        if (Number.isFinite(lng) && Number.isFinite(lat)) tail.push([lng, lat]);
    }
    // 万一 remaining_route 只有一个点（== 当前位置），也得画出来
    if (route.length === 1) {
        const p = route[0];
        const lng = Number(p?.x), lat = Number(p?.y);
        if (Number.isFinite(lng) && Number.isFinite(lat)) tail.push([lng, lat]);
    }

    // 3) 拼完整折线：disp → aheadInTick → tail
    const startPx = entityPosToCanvas({ x: disp.lng, y: disp.lat });
    ctx.save();
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.setLineDash([6, 4]);
    ctx.shadowColor = 'rgba(245,158,11,0.9)';
    ctx.shadowBlur = 8;

    ctx.beginPath();
    ctx.moveTo(startPx.x, startPx.y);
    for (const [lng, lat] of aheadInTick) {
        const p = entityPosToCanvas({ x: lng, y: lat });
        ctx.lineTo(p.x, p.y);
    }
    for (const [lng, lat] of tail) {
        const p = entityPosToCanvas({ x: lng, y: lat });
        ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();

    // 终点菱形
    const lastPt = tail.length > 0 ? tail[tail.length - 1]
                 : aheadInTick.length > 0 ? aheadInTick[aheadInTick.length - 1]
                 : [disp.lng, disp.lat];
    const tgt = entityPosToCanvas({ x: lastPt[0], y: lastPt[1] });
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#f59e0b';
    ctx.beginPath();
    ctx.moveTo(tgt.x, tgt.y - 6);
    ctx.lineTo(tgt.x + 6, tgt.y);
    ctx.lineTo(tgt.x, tgt.y + 6);
    ctx.lineTo(tgt.x - 6, tgt.y);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
}

// 把"网格 + 路网"一次性画到一张 offscreen canvas 上并缓存，之后每帧直接 drawImage。
// 路网几万条边，每帧重新 stroke 会吃满 CPU，这是 canvas 卡顿的主因。
function ensureRoadGraphCache() {
    if (!roadGraph || !canvas) return null;
    const nodeCount = roadGraph.nodes.length;
    const edgeCount = roadGraph.edges.length;
    const b = activeCanvasBounds();
    const boundsKey = b
        ? `${b.minLng.toFixed(6)},${b.maxLng.toFixed(6)},${b.minLat.toFixed(6)},${b.maxLat.toFixed(6)}`
        : '';

    const cache = roadGraphCache;
    const valid = cache.canvas
        && cache.width === canvas.width
        && cache.height === canvas.height
        && cache.offsetX === canvasOffsetX
        && cache.offsetY === canvasOffsetY
        && cache.nodeCount === nodeCount
        && cache.edgeCount === edgeCount
        && cache.boundsKey === boundsKey;
    if (valid) return cache.canvas;

    // 构建 / 重建 offscreen
    const off = cache.canvas instanceof HTMLCanvasElement
        ? cache.canvas
        : document.createElement('canvas');
    off.width = canvas.width;
    off.height = canvas.height;
    const octx = off.getContext('2d');
    octx.clearRect(0, 0, off.width, off.height);

    // 背景（和主画布同色，保证无缝）
    octx.fillStyle = '#0f172a';
    octx.fillRect(0, 0, off.width, off.height);

    // 1) 网格
    if (b) {
        const step = 0.01; // ~1.1 km
        const minLng = Math.floor(b.minLng / step) * step;
        const maxLng = Math.ceil(b.maxLng / step) * step;
        const minLat = Math.floor(b.minLat / step) * step;
        const maxLat = Math.ceil(b.maxLat / step) * step;

        octx.strokeStyle = 'rgba(148,163,184,0.12)';
        octx.lineWidth = 1;
        octx.beginPath();
        for (let lng = minLng; lng <= maxLng + 1e-9; lng += step) {
            const top = projectLngLat(lng, maxLat);
            const bot = projectLngLat(lng, minLat);
            octx.moveTo(top.x + canvasOffsetX, top.y + canvasOffsetY);
            octx.lineTo(bot.x + canvasOffsetX, bot.y + canvasOffsetY);
        }
        for (let lat = minLat; lat <= maxLat + 1e-9; lat += step) {
            const left = projectLngLat(minLng, lat);
            const right = projectLngLat(maxLng, lat);
            octx.moveTo(left.x + canvasOffsetX, left.y + canvasOffsetY);
            octx.lineTo(right.x + canvasOffsetX, right.y + canvasOffsetY);
        }
        octx.stroke();
    }

    // 2) 路网节点像素
    const nodes = roadGraph.nodes;
    const edges = roadGraph.edges;
    const px = new Float32Array(nodes.length);
    const py = new Float32Array(nodes.length);
    for (let i = 0; i < nodes.length; i++) {
        const p = projectLngLat(nodes[i][1], nodes[i][2]);
        px[i] = p.x + canvasOffsetX;
        py[i] = p.y + canvasOffsetY;
    }

    // 3) 边（一次 beginPath + 一次 stroke，哪怕几万条）
    octx.strokeStyle = 'rgba(148,163,184,0.35)';
    octx.lineWidth = 0.8;
    octx.beginPath();
    for (let i = 0; i < edges.length; i++) {
        const e = edges[i];
        const a = e[0], b2 = e[1];
        if (a < 0 || b2 < 0 || a >= nodes.length || b2 >= nodes.length) continue;
        octx.moveTo(px[a], py[a]);
        octx.lineTo(px[b2], py[b2]);
    }
    octx.stroke();

    // 4) 节点（数量少才画）
    const NODE_DOT_LIMIT = 1500;
    if (nodes.length <= NODE_DOT_LIMIT) {
        octx.fillStyle = 'rgba(148,163,184,0.75)';
        for (let i = 0; i < nodes.length; i++) {
            octx.beginPath();
            octx.arc(px[i], py[i], 1.4, 0, Math.PI * 2);
            octx.fill();
        }
    }

    cache.canvas = off;
    cache.width = off.width;
    cache.height = off.height;
    cache.offsetX = canvasOffsetX;
    cache.offsetY = canvasOffsetY;
    cache.nodeCount = nodeCount;
    cache.edgeCount = edgeCount;
    cache.boundsKey = boundsKey;
    return off;
}

// 入口：从缓存把"网格 + 路网"一次性贴到主画布。整张就是一次 drawImage。
function drawRoadGraphOnCanvas() {
    const off = ensureRoadGraphCache();
    if (off) ctx.drawImage(off, 0, 0);
}

// 背景网格已经一并渲染进缓存里，这里保留一个空壳以免外部调用点报错。
function drawCanvasGrid() { /* moved into ensureRoadGraphCache */ }

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

// =====================================================================
// 点击车辆列表项 → 在地图上高亮该车当前 command 的路径
// =====================================================================
let selectedVehicleId = null;           // 当前被选中的车 id（null 表示没选）
let selectedVehiclePolyline = null;     // 地图上高亮用的那一条 polyline

function toggleVehicleHighlight(vehicleId) {
    selectedVehicleId = (selectedVehicleId === vehicleId) ? null : vehicleId;
    updateVehicleItemSelectionStyles();
    if (currentSimulationState) {
        highlightSelectedVehicleRoute(currentSimulationState);
    }
}

function updateVehicleItemSelectionStyles() {
    document.querySelectorAll('.vehicle-item').forEach(item => {
        const vid = Number(item.getAttribute('data-vehicle-id'));
        if (selectedVehicleId !== null && vid === selectedVehicleId) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });
}

function highlightSelectedVehicleRoute(state) {
    // 先清掉上一次的高亮
    if (selectedVehiclePolyline) {
        selectedVehiclePolyline.setMap(null);
        selectedVehiclePolyline = null;
    }

    if (selectedVehicleId === null) return;
    if (!useRealMap || !map) return;  // Canvas 模式暂不支持
    if (!state || !Array.isArray(state.vehicles)) return;

    const v = state.vehicles.find(vv => vv.id === selectedVehicleId);
    if (!v) {
        // 选中的车已不存在（例如重置），清空选择
        selectedVehicleId = null;
        updateVehicleItemSelectionStyles();
        return;
    }

    // 优先用 remaining_route（第一个点 = 车的当前实时位置），
    // 后端没给这个字段时退回 current_route / complete_path（从起点开始画）。
    const route = (v.remaining_route && v.remaining_route.length >= 2)
        ? v.remaining_route
        : (v.current_route || v.complete_path || []);
    if (!route || route.length < 2) return;  // 没在执行命令（idle/stranded/仓库待命）

    const pathCoords = route
        .map(p => pathPointToAmap(p))
        .filter(coord => coord && !isNaN(coord[0]) && !isNaN(coord[1]));
    if (pathCoords.length < 2) return;

    selectedVehiclePolyline = new AMap.Polyline({
        path: pathCoords,
        strokeColor: '#f59e0b',   // 醒目琥珀色
        strokeWeight: 6,
        strokeOpacity: 0.95,
        lineJoin: 'round',
        showDir: true,            // 带箭头指示行驶方向
        zIndex: 200,
    });
    selectedVehiclePolyline.setMap(map);
}

// 车辆平滑动画：从 marker 当前显示位置，沿后端汇报的"本 tick 折线"平滑插值到最新位置。
// - 有 tickWaypoints（>= 2 点）时沿折线走，节点再密也平滑，不会"直线切弯"；
// - 没有（比如老后端 / 停着的车）时退化为直线插值。
// - 基础时长 = renderConfig.marker_tween_ms；若 marker_tween_adaptive=True，
//   按"实际折线长度 / 预期每 tick 距离"缩短，末段不再显得慢。
function tweenMarkerTo(vehicleId, marker, targetLngLat, vehicleSpeedMps, tickWaypoints) {
    if (!map || !marker || !targetLngLat) return;
    const tgt = [Number(targetLngLat[0]), Number(targetLngLat[1])];
    if (!isFinite(tgt[0]) || !isFinite(tgt[1])) return;

    const existing = vehicleAnimations.get(vehicleId);
    if (existing && existing.rafId) cancelAnimationFrame(existing.rafId);

    const curPos = marker.getPosition();
    const src = curPos ? [curPos.getLng(), curPos.getLat()] : tgt;

    // ---- 构造这次动画要走的折线 path：首 = marker 当前显示点，尾 = 新目标点 ----
    let path = [src];
    if (Array.isArray(tickWaypoints) && tickWaypoints.length >= 2) {
        // tick_waypoints 的首点是"后端 tick 开始时的车辆位置"，
        // 但前端 marker 当前显示点 src 可能稍有偏差（上一段 tween 没完全跑到头）；
        // 所以拿 waypoints[1..end] 追加，起点保持用 src（视觉连续），尾点强制对齐 tgt。
        for (let i = 1; i < tickWaypoints.length; i++) {
            const amap = pathPointToAmap(tickWaypoints[i]);
            if (amap && isFinite(amap[0]) && isFinite(amap[1])) {
                path.push(amap);
            }
        }
    } else {
        path.push(tgt);
    }
    // 无论如何把末尾对齐到后端最新 tgt
    if (path.length >= 2) {
        path[path.length - 1] = tgt;
    } else {
        path.push(tgt);
    }

    // ---- 计算每段长度 + 总长（lng/lat 单位下的粗距，用于插值进度即可） ----
    const segLens = [];
    let totalDeg = 0;
    for (let i = 1; i < path.length; i++) {
        const dx = path[i][0] - path[i - 1][0];
        const dy = path[i][1] - path[i - 1][1];
        const len = Math.hypot(dx, dy);
        segLens.push(len);
        totalDeg += len;
    }
    if (totalDeg < 1e-9) {
        marker.setPosition(tgt);
        vehicleAnimations.delete(vehicleId);
        return;
    }

    // ---- tween 总时长 ----
    let durationMs = Math.max(1, Number(renderConfig.marker_tween_ms) || 900);
    if (renderConfig.marker_tween_adaptive && vehicleSpeedMps && vehicleSpeedMps > 0) {
        const expectedMeters =
            vehicleSpeedMps *
            (Number(renderConfig.speed_factor) || 120) *
            (Number(renderConfig.tick_interval) || 1);
        // 把所有段长换成米（沿纬度修正 lng 尺度）
        const latDeg = (src[1] + tgt[1]) * 0.5;
        const mPerDegLat = 111_320;
        const mPerDegLng = 111_320 * Math.cos((latDeg * Math.PI) / 180);
        let actualMeters = 0;
        for (let i = 1; i < path.length; i++) {
            const dx = (path[i][0] - path[i - 1][0]) * mPerDegLng;
            const dy = (path[i][1] - path[i - 1][1]) * mPerDegLat;
            actualMeters += Math.hypot(dx, dy);
        }
        if (expectedMeters > 1) {
            const ratio = Math.min(1, actualMeters / expectedMeters);
            durationMs = Math.max(50, durationMs * ratio);
        }
    }

    const startTime = performance.now();

    function tick(now) {
        const t = Math.min(1, (now - startTime) / durationMs);
        const targetDist = t * totalDeg;

        // 根据累计距离找当前所在段，再在段内线性插值
        let acc = 0;
        let pos = path[path.length - 1];
        for (let i = 0; i < segLens.length; i++) {
            if (acc + segLens[i] >= targetDist) {
                const localT = segLens[i] > 1e-12 ? (targetDist - acc) / segLens[i] : 0;
                const a = path[i], b = path[i + 1];
                pos = [a[0] + (b[0] - a[0]) * localT, a[1] + (b[1] - a[1]) * localT];
                break;
            }
            acc += segLens[i];
        }
        marker.setPosition(pos);

        if (t < 1) {
            const rafId = requestAnimationFrame(tick);
            vehicleAnimations.set(vehicleId, { rafId });
        } else {
            vehicleAnimations.delete(vehicleId);
        }
    }

    const rafId = requestAnimationFrame(tick);
    vehicleAnimations.set(vehicleId, { rafId });
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

	// 更新车辆状态列表（点击任意条目 → 在地图上高亮该车当前 command 的路径）
	vehicleStatusList.innerHTML = '';
	// 预先建一张任务速查表，用于在每辆车卡片里展示"这辆车正在背哪些货"
	const taskById = new Map();
	if (state.tasks) {
		for (const t of state.tasks) taskById.set(t.id, t);
	}
	const taskBadgeClass = (s) => {
		switch (s) {
			case 'pending':     return 'task-badge pending';
			case 'assigned':    return 'task-badge assigned';
			case 'in_progress': return 'task-badge in-progress';
			case 'completed':   return 'task-badge completed';
			case 'timeout':     return 'task-badge timeout';
			default:            return 'task-badge';
		}
	};
	const taskStatusLabel = (s) => {
		switch (s) {
			case 'pending':     return '待派';
			case 'assigned':    return '在车上';
			case 'in_progress': return '已送达';
			case 'completed':   return '已结算';
			case 'timeout':     return '超时';
			default:            return s || '';
		}
	};
	if (state.vehicles) {
		for (const v of state.vehicles) {
			const div = document.createElement('div');
			div.className = `vehicle-item ${v.status}`;
			div.setAttribute('data-vehicle-id', v.id);
			div.style.cursor = 'pointer';
			if (selectedVehicleId === v.id) div.classList.add('selected');

			const battPct = (v.battery_percentage ?? (v.battery / v.max_battery * 100)).toFixed(1);
			const typeLabel = v.vehicle_type ? `[${v.vehicle_type}]` : '';
			const progressInfo = vehiclePathProgress.get(v.id);
			const progressText = progressInfo ? `| 路径进度: ${(v.path_progress * 100).toFixed(0)}%` : '';

			// 路径长度提示：优先显示"剩余"段数（从车当前位置算起）
			const remainingLen = (v.remaining_route && v.remaining_route.length) || 0;
			const fullLen = (v.current_route && v.current_route.length) || 0;
			const segsToShow = remainingLen >= 2 ? (remainingLen - 1)
				: (fullLen >= 2 ? fullLen - 1 : 0);
			const routeHint = segsToShow > 0
				? `<span class="route-hint">🗺️ 剩余 ${segsToShow} 段（点我高亮）</span>`
				: `<span class="route-hint-empty">无进行中路径</span>`;

			// 这辆车正在承运的任务列表（一辆车可多任务；接力场景下这里会动态变）
			const taskIds = Array.isArray(v.assigned_task_ids) ? v.assigned_task_ids : [];
			let taskListHtml;
			if (taskIds.length === 0) {
				taskListHtml = `<div class="vehicle-tasks empty">当前未承运任务</div>`;
			} else {
				const items = taskIds.map(tid => {
					const t = taskById.get(tid);
					if (!t) return `<span class="task-badge">任务#${tid}</span>`;
					return `<span class="${taskBadgeClass(t.status)}" title="重量 ${(+t.weight).toFixed(1)}kg / 优先级 ${t.priority}">`
						+ `任务#${t.id} · ${taskStatusLabel(t.status)} · ${(+t.weight).toFixed(1)}kg`
						+ `</span>`;
				}).join(' ');
				taskListHtml = `<div class="vehicle-tasks">承运中（${taskIds.length}）：${items}</div>`;
			}

			div.innerHTML = `
				<strong>车辆#${v.id} ${typeLabel}</strong>
				<p>状态：${vehicleStatusText(v.status)} | 电量：${battPct}% | 载重：${v.current_load.toFixed(1)}/${v.max_load}kg ${progressText}</p>
				<p>总行驶：${(v.total_distance_traveled || 0).toFixed(0)}m | 充电站：${v.charging_station_id || '无'}</p>
				<p>${routeHint}</p>
				${taskListHtml}
			`;

			div.addEventListener('click', () => toggleVehicleHighlight(v.id));
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
