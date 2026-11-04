"""
Warehouse management and AI Assistant page router for Tạp hóa 360.
Replaces warehouse.php.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import db

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_warehouse_data(zone: str, query: str):
    selected_zone = zone or "B1"

    # 1. Lọc sản phẩm theo kệ (Zone)
    products = db.query_all(
        "SELECT * FROM products WHERE zone_code = ?",
        (selected_zone,)
    )

    # 2. Lấy gợi ý của Trợ lý ảo AI
    ai_suggestions = db.query_all(
        "SELECT * FROM ai_suggestions WHERE status = 'PENDING'"
    )

    # 3. Tìm kiếm định vị sản phẩm trên bản đồ 360 độ
    search_keyword = query.strip()
    product_info = None

    if search_keyword:
        search_term = f"%{search_keyword}%"
        product_info = db.query_one(
            "SELECT * FROM products WHERE product_name LIKE ? OR sku LIKE ? LIMIT 1",
            (search_term, search_term)
        )

    if not product_info:
        product_info = db.query_one("SELECT * FROM products LIMIT 1")

    if not product_info:
        product_info = {
            "product_name": "Chưa có sản phẩm trong kho",
            "shelf_location": "Chưa xác định",
            "zone_code": "B1",
            "stock": 0,
            "unit": ""
        }

    return {
        "products": products,
        "aiSuggestions": ai_suggestions,
        "productInfo": product_info,
        "selectedZone": selected_zone,
        "searchKeyword": search_keyword
    }


@router.get("/warehouse.php", response_class=HTMLResponse)
@router.get("/warehouse", response_class=HTMLResponse)
async def warehouse_page(request: Request):
    zone = request.query_params.get("zone", "B1")
    q = request.query_params.get("q", "")
    data = get_warehouse_data(zone, q)
    return templates.TemplateResponse(
        request=request,
        name="warehouse.html",
        context=data
    )
