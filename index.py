"""
Dashboard page router for Tạp hóa 360.
Replaces index.php.
"""

from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import db

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_dashboard_stats():
    revenue_row = db.query_one("SELECT SUM(total_amount) as total FROM orders")
    total_revenue = float(revenue_row["total"]) if revenue_row and revenue_row.get("total") else 0

    orders_row = db.query_one("SELECT COUNT(*) as cnt FROM orders")
    total_orders_count = int(orders_row["cnt"]) if orders_row and orders_row.get("cnt") else 0

    products_row = db.query_one("SELECT COUNT(*) as cnt FROM products")
    total_products = int(products_row["cnt"]) if products_row and products_row.get("cnt") else 0

    expiring_row = db.query_one("SELECT COUNT(*) as cnt FROM ai_suggestions WHERE status = 'PENDING'")
    expiring_count = int(expiring_row["cnt"]) if expiring_row and expiring_row.get("cnt") else 0

    return {
        "totalRevenue": total_revenue,
        "totalOrdersCount": total_orders_count,
        "totalProducts": total_products,
        "expiringCount": expiring_count,
        "current_time": datetime.now().strftime("%d/%m/%Y - %H:%M")
    }


@router.get("/", response_class=HTMLResponse)
@router.get("/index.php", response_class=HTMLResponse)
@router.get("/index", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    stats = get_dashboard_stats()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=stats
    )
