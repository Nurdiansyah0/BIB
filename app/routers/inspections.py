from fastapi import APIRouter, Request
from geopy.distance import distance

router = APIRouter()

@router.post("/verify-location")
async def verify_location(request: Request):
    data = await request.json()
    user_lat = data['lat']
    user_lon = data['lon']
    
    # Implementasi logika verifikasi lokasi
    return {"valid": True, "terminal_id": 1}