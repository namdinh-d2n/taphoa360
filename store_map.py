"""
Store map 360 page router for Tạp hóa 360.
Replaces store_map.php.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import db

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_store_map_data(query: str):
    search_keyword = query.strip()
    if search_keyword:
        search_term = f"%{search_keyword}%"
        product_info = db.query_one(
            """SELECT product_name, sku, stock, unit, shelf_location, zone_code 
               FROM products 
               WHERE product_name LIKE ? OR sku LIKE ? LIMIT 1""",
            (search_term, search_term)
        )
    else:
        product_info = {
            "product_name": "Sữa tươi không đường 1L",
            "shelf_location": "Kệ B2 · Tầng 2 · Ô B2-04",
            "zone_code": "B2",
            "stock": 12,
            "unit": "lốc"
        }

    if not product_info:
        product_info = {
            "product_name": "Không tìm thấy sản phẩm",
            "shelf_location": "Chưa xác định vị trí",
            "zone_code": "--",
            "stock": 0,
            "unit": ""
        }

    return {
        "searchKeyword": search_keyword,
        "productInfo": product_info
    }


@router.get("/store_map.php", response_class=HTMLResponse)
@router.get("/store_map", response_class=HTMLResponse)
@router.get("/store-map", response_class=HTMLResponse)
async def store_map_page(request: Request):
    q = request.query_params.get("q", "")
    data = get_store_map_data(q)
    return templates.TemplateResponse(
        request=request,
        name="store_map.html",
        context=data
    )
