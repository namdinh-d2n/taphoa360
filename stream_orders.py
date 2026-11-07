"""
Real-time Server-Sent Events (SSE) module for Tạp hóa 360.
Replaces stream_orders.php.
Streams new orders to web clients in real-time.
"""

import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import db

router = APIRouter()


async def order_event_generator(request: Request, last_id: int):
    # Gửi tín hiệu kết nối thành công ban đầu
    yield f"data: {json.dumps({'status': 'connected'})}\n\n"

    current_last_id = last_id
    while True:
        if await request.is_disconnected():
            break

        try:
            new_orders = db.query_all(
                "SELECT * FROM orders WHERE id > ? ORDER BY id ASC",
                (current_last_id,)
            )

            if new_orders:
                for row in new_orders:
                    order = dict(row)
                    order_id = int(order["id"])

                    # Lấy chi tiết mặt hàng
                    items = db.query_all(
                        "SELECT product_name, quantity, price FROM order_items WHERE order_id = ?",
                        (order_id,)
                    )
                    order["items"] = [dict(it) for it in items]

                    yield f"data: {json.dumps(order, default=str, ensure_ascii=False)}\n\n"
                    current_last_id = max(current_last_id, order_id)
        except Exception as e:
            # Avoid crashing the generator on temporary db locked
            pass

        await asyncio.sleep(2)


@router.get("/stream_orders.php")
@router.get("/api/stream_orders")
@router.get("/stream_orders")
async def stream_orders_endpoint(request: Request):
    last_id_param = request.query_params.get("last_id", "0")
    try:
        last_id = int(last_id_param)
    except ValueError:
        last_id = 0

    return StreamingResponse(
        order_event_generator(request, last_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
