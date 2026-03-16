from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import asyncio

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模拟WebSocketHandler
class MockWebSocketHandler:
    def __init__(self):
        self.active_connections = set()
    
    async def connect(self, websocket):
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    def get_connection_count(self):
        return len(self.active_connections)
    
    async def handle_message(self, websocket, message):
        if message.get('type') == 'ping':
            await websocket.send_json({"type": "pong", "data": message})
        elif message.get('type') == 'get_state':
            await websocket.send_json({"type": "state_response", "data": {"test": "data"}})
        else:
            await websocket.send_json({"type": "echo", "data": message})

# 创建handler实例
websocket_handler = MockWebSocketHandler()

# 后台任务
async def background_task():
    while True:
        await asyncio.sleep(5)
        print(f"Background task: {len(websocket_handler.active_connections)} connections")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_task())

# WebSocket路由
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    print(f"WebSocket connection request from: {websocket.client}")
    await websocket.accept()
    print("WebSocket connected")
    
    await websocket_handler.connect(websocket)
    print(f"Total connections: {websocket_handler.get_connection_count()}")
    
    try:
        while True:
            data = await websocket.receive_json()
            print(f"Received: {data}")
            await websocket_handler.handle_message(websocket, data)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        websocket_handler.disconnect(websocket)
        print(f"WebSocket disconnected. Total connections: {websocket_handler.get_connection_count()}")

@app.get("/")
async def root():
    return {"message": "Test server"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)