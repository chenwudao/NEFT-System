from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    print(f"WebSocket connection request from: {websocket.client}")
    await websocket.accept()
    print("WebSocket connected")
    
    try:
        while True:
            data = await websocket.receive_json()
            print(f"Received: {data}")
            await websocket.send_json({"type": "echo", "data": data})
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("WebSocket disconnected")

@app.get("/")
async def root():
    return {"message": "WebSocket test server"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)