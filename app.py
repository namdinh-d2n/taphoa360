"""
Main Application for Tạp hóa 360 (Python Backend).
Combines all routes, handles CORS, and supports both standard REST URLs and legacy .php URLs.
"""

import sys
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Import all route modules
import index
import orders
import warehouse
import store_map
import create_order
import get_merchant_orders
import search_inventory
import stream_orders
import hr

app = FastAPI(
    title="Tạp hóa 360 - Quản trị Bán lẻ Thông minh",
    description="Hệ thống quản lý bán lẻ, kho hàng, trợ lý AI và API cho App Mobile",
    version="2.0.0"
)

# CORS Middleware for Android App and cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(index.router)
app.include_router(orders.router)
app.include_router(warehouse.router)
app.include_router(store_map.router)
app.include_router(create_order.router)
app.include_router(get_merchant_orders.router)
app.include_router(search_inventory.router)
app.include_router(stream_orders.router)
app.include_router(hr.router)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"============================================================")
    print(f"  TAP HOA 360 - SERVER RUNNING AT http://127.0.0.1:{port}")
    print(f"  - Trang tong quan:  http://127.0.0.1:{port}/")
    print(f"  - Quan ly don hang: http://127.0.0.1:{port}/orders.php")
    print(f"  - Quan ly kho:      http://127.0.0.1:{port}/warehouse.php")
    print(f"  - So do cua hang:   http://127.0.0.1:{port}/store_map.php")
    print(f"  - Nhan luc & Cham cong: http://127.0.0.1:{port}/hr.php")
    print(f"============================================================")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
