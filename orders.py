"""
Orders management page router for Tạp hóa 360.
Replaces orders.php.
Supports listing recent orders, deleting orders (CRUD), and receiving real-time SSE notifications.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import db

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_orders_list():
    raw_orders = db.query_all("SELECT * FROM orders ORDER BY id DESC LIMIT 15")
    orders = []
    for o in raw_orders:
        order = dict(o)
        order_id = int(order["id"])
        items = db.query_all(
            "SELECT product_name, quantity FROM order_items WHERE order_id = ?",
            (order_id,)
        )
        item_parts = []
        for it in items:
            name = it["product_name"]
            qty = float(it["quantity"])
            qty_str = f"{int(qty)}" if qty.is_integer() else f"{qty:.2f}"
            item_parts.append(f"{name} (x{qty_str})")

        order["items_text"] = ", ".join(item_parts) if item_parts else "Chưa có sản phẩm"
        orders.append(order)
    return orders


@router.get("/orders.php", response_class=HTMLResponse)
@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    action = request.query_params.get("action")
    delete_id = request.query_params.get("id")

    # Handle Delete action
    if action == "delete" and delete_id:
        try:
            del_id = int(delete_id)
            db.execute("DELETE FROM order_items WHERE order_id = ?", (del_id,))
            db.execute("DELETE FROM orders WHERE id = ?", (del_id,))
        except Exception as e:
            print(f"[Orders] Error deleting order: {e}")
        return RedirectResponse(url="/orders.php", status_code=303)

    orders = get_orders_list()
    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context={"orders": orders}
    )
