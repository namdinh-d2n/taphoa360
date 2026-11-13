"""
API search_inventory module for Tạp hóa 360.
Replaces search_inventory.php.
Searches products by keyword (product_name or sku) and returns JSON data.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import db

router = APIRouter()


def search_products(keyword: str):
    search_term = f"%{keyword}%"
    rows = db.query_all(
        """SELECT id, product_name AS name, sku, stock, unit, shelf_location AS location, price 
           FROM products 
           WHERE product_name LIKE ? OR sku LIKE ? 
           LIMIT 10""",
        (search_term, search_term)
    )

    items = []
    for r in rows:
        items.append({
            "id": int(r["id"]),
            "name": r["name"],
            "sku": r["sku"],
            "stock": float(r["stock"]),
            "unit": r["unit"],
            "location": r["location"],
            "price": float(r.get("price") or 150000)
        })

    return {
        "success": True,
        "data": items
    }


@router.get("/search_inventory.php")
@router.get("/api/search_inventory")
@router.get("/search_inventory")
async def search_inventory_endpoint(request: Request):
    keyword = request.query_params.get("keyword", "").strip()
    result = search_products(keyword)
    return JSONResponse(content=result)
