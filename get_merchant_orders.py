"""
API get_merchant_orders module for Tạp hóa 360.
Replaces get_merchant_orders.php.
Fetches active orders, picking items list, and shipper status for Android merchant app.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
import db

router = APIRouter()


def fetch_merchant_orders():
    # 1. Lấy đơn hàng mới nhất đang cần xử lý (PENDING hoặc PROCESSING)
    active_order = db.query_one(
        """SELECT id, order_code, apartment, total_amount, payment_method, status, customer_note, created_at 
           FROM orders 
           WHERE status IN ('PENDING', 'PROCESSING') 
           ORDER BY id DESC LIMIT 1"""
    )

    pick_list = []
    if active_order:
        order_id = active_order["id"]
        # 2. Lấy danh sách sản phẩm thuộc đơn hàng kèm vị trí kệ
        items = db.query_all(
            """SELECT id, product_name AS name, shelf_location AS shelfLocation, quantity, price, subtotal, is_picked AS isDone 
               FROM order_items 
               WHERE order_id = ?""",
            (order_id,)
        )
        for row in items:
            item = dict(row)
            qty_val = float(item.get("quantity") or 0)
            item["qty"] = f"{int(qty_val)} sp" if qty_val.is_integer() else f"{qty_val} sp"
            item["isDone"] = bool(item.get("isDone"))
            pick_list.append(item)

    # 3. Lấy danh sách nhân viên giao hàng (Shipper nội khu)
    shippers = []
    try:
        shippers_rows = db.query_all("SELECT name, status, note FROM shippers")
        shippers = [dict(s) for s in shippers_rows]
    except Exception:
        pass

    if not shippers:
        shippers = [
            {"name": "Anh Khoa", "status": "ĐANG GIAO", "note": "Đang giao: A2-1508"},
            {"name": "Chị Mai", "status": "PHÂN CÔNG", "note": "Sẵn sàng nhận đơn"}
        ]

    return {
        "success": True,
        "order": active_order,
        "pick_list": pick_list,
        "shippers": shippers
    }


@router.get("/get_merchant_orders.php")
@router.get("/api/get_merchant_orders")
@router.get("/get_merchant_orders")
async def get_merchant_orders_endpoint():
    data = fetch_merchant_orders()
    return JSONResponse(content=data)
