from fastapi import APIRouter, WebSocket

router = APIRouter()

@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    while True:
        # Kirim update data ke frontend
        await websocket.send_json({"message": "Data updated"})