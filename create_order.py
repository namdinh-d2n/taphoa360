"""
API create_order module for Tạp hóa 360.
Replaces create_order.php.
Receives JSON order payload from Android/Client and persists to orders and order_items.
"""

from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import db

router = APIRouter()


def process_create_order(data: dict):
    if not data or not data.get("items"):
        return {"success": False, "message": "Dữ liệu đơn hàng không hợp lệ"}

    order_code = f"DH-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    created_by = data.get("created_by") or "Thu ngân"
    total_amount = float(data.get("total_amount", 0))
    payment_method = data.get("payment_method") or "Tiền mặt"
    apartment = data.get("apartment", "")
    customer_note = data.get("customer_note", "")

    try:
        # Insert into orders
        order_id = db.execute(
            """INSERT INTO orders (order_code, created_by, total_amount, payment_method, apartment, customer_note, status)
               VALUES (?, ?, ?, ?, ?, ?, 'PENDING')""",
            (order_code, created_by, total_amount, payment_method, apartment, customer_note)
        )

        # Insert items into order_items
        for item in data.get("items", []):
            name = item.get("name", "")
            qty = float(item.get("quantity", 1))
            price = float(item.get("price", 0))
            subtotal = float(item.get("subtotal", qty * price))
            shelf_location = item.get("shelf_location", "")

            db.execute(
                """INSERT INTO order_items (order_id, product_name, shelf_location, quantity, price, subtotal, is_picked)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (order_id, name, shelf_location, qty, price, subtotal)
            )

        return {
            "success": True,
            "message": "Tạo đơn thành công",
            "order_code": order_code,
            "order_id": order_id
        }
    except Exception as e:
        return {"success": False, "message": f"Lỗi khi lưu đơn hàng: {str(e)}"}


@router.post("/create_order.php")
@router.post("/api/create_order")
@router.post("/create_order")
async def create_order_endpoint(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    result = process_create_order(data)
    return JSONResponse(content=result, status_code=200 if result.get("success") else 400)
