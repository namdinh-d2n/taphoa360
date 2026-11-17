# Authenticated personal-shopping APIs and private, sanitized evidence photos.
import asyncio
import json
from io import BytesIO
from pathlib import Path
import secrets
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, Response
from PIL import Image, UnidentifiedImageError
import config
from .auth import require, current_user
from .shop_auth import customer_user
from .common import validate_payload, fail, money, number, required
from .database import transaction, reading, rows, one
from . import errands as domain

public = APIRouter(prefix="/api/shop/errands", dependencies=[Depends(validate_payload)])
admin = APIRouter(prefix="/api/v1/errands", dependencies=[Depends(validate_payload)])
media = APIRouter()


def load(conn, ident, user, customer=False):
    from .common import record

    order = record(conn, "errand_orders", ident)
    domain.scope(order, user, customer)
    return order


def directory(conn):
    return {
        "branches": rows(
            conn,
            """SELECT b.* FROM errand_branches b
        LEFT JOIN delivery_zones z ON b.zone_id=z.id WHERE b.active=1 AND (b.zone_id IS NULL OR z.active=1) ORDER BY b.province_name,b.id""",
        ),
        "provinces": rows(
            conn,
            "SELECT DISTINCT province_code code,province_name name FROM errand_branches WHERE active=1 ORDER BY province_name",
        ),
    }


@public.get("/directory")
def public_directory():
    with reading() as conn:
        return directory(conn)


def live_revision(conn, user, customer):
    if customer:
        where, params = " WHERE account_id=?", (user["id"],)
    elif user["role"] in {"inventory", "shipper"}:
        field = "shopper_id" if user["role"] == "inventory" else "shipper_id"
        where, params = " WHERE " + field + "=?", (user["id"],)
    else:
        where, params = "", ()
    from .shop_addresses import saved_address

    return domain.digest(
        {
            "saved_address": saved_address(conn, user["id"]) if customer else None,
            "orders": rows(
                conn,
                "SELECT id,version FROM errand_orders" + where + " ORDER BY id",
                params,
            ),
            "settings": one(conn, "SELECT * FROM errand_settings WHERE id=1"),
            "directory": directory(conn),
            "bank": one(
                conn,
                "SELECT bank_bin,bank_account,bank_name FROM shop_settings WHERE id=1",
            ),
        }
    )


async def event_stream(request, customer):
    from fastapi import HTTPException
    from .live_events import subscribe

    database = config.SQLITE_PATH

    def revision():
        user = (
            customer_user(request)
            if customer
            else require("cashier", "inventory", "shipper")(current_user(request))
        )
        with reading() as conn:
            return live_revision(conn, user, customer)

    # Authenticate before returning streaming headers as well as after every wakeup.
    await asyncio.to_thread(revision)

    async def stream():
        previous = None
        with subscribe(database) as changed:
            while not await request.is_disconnected():
                changed.clear()
                try:
                    current = await asyncio.to_thread(revision)
                except HTTPException:
                    yield "event: session-expired\ndata: {}\n\n"
                    return
                if current != previous:
                    yield (
                        "event: changed\ndata: "
                        + json.dumps({"revision": current})
                        + "\n\n"
                    )
                    previous = current
                else:
                    yield ": keepalive\n\n"
                try:
                    await asyncio.wait_for(changed.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@public.get("/events")
async def customer_events(request: Request):
    return await event_stream(request, True)


@admin.get("/events")
async def staff_events(request: Request):
    return await event_stream(request, False)


@public.get("/{ident}/qr")
def payment_qr(ident: int, version: int, user=Depends(customer_user)):
    from .shop_api import qr_payload
    import qrcode

    with reading() as conn:
        order = load(conn, ident, user, True)
        if version != order["version"]:
            fail("Thông tin đơn đã thay đổi. Mã QR sẽ cập nhật theo đơn mới.", 409)
        pay = domain.payment_details(conn, order)
        if order["payment_method"] != "TRANSFER" or not pay["qr_ready"]:
            fail(
                "QR chỉ mở khi chọn chuyển khoản và còn tiền đã được khách duyệt cần thanh toán.",
                409,
            )
        bank = pay["bank"]
        payload = qr_payload(
            bank["bank_bin"], bank["bank_account"], pay["amount"], order["code"]
        )
    output = BytesIO()
    qrcode.make(payload).save(output, format="PNG")
    return Response(
        output.getvalue(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{order["code"]}-qr.png"',
        },
    )


@public.get("")
def customer_orders(user=Depends(customer_user)):
    with reading() as conn:
        return {
            "orders": [
                domain.detail(conn, o)
                for o in rows(
                    conn,
                    "SELECT * FROM errand_orders WHERE account_id=? ORDER BY id DESC LIMIT 100",
                    (user["id"],),
                )
            ],
            "zones": rows(
                conn, "SELECT id,name,fee FROM delivery_zones WHERE active=1"
            ),
            "settings": one(conn, "SELECT * FROM errand_settings WHERE id=1"),
            **directory(conn),
            "bank": one(
                conn, "SELECT bank_name,bank_account FROM shop_settings WHERE id=1"
            ),
        }


@public.post("")
def create_order(data: dict, request: Request, user=Depends(customer_user)):
    with transaction() as conn:
        request_key = request.headers.get("idempotency-key")
        previous = one(
            conn, "SELECT id FROM errand_orders WHERE request_key=?", (request_key,)
        )
        result = domain.create(conn, user, data, request_key)
        if not previous:
            from .shop_addresses import remember_order_address

            remember_order_address(conn, user, data, errand=True)
        return result


@public.get("/{ident}")
def customer_detail(ident: int, user=Depends(customer_user)):
    with reading() as conn:
        return domain.detail(conn, load(conn, ident, user, True))


@public.post("/{ident}/{action}")
def customer_action(ident: int, action: str, data: dict, user=Depends(customer_user)):
    with transaction() as conn:
        order = load(conn, ident, user, True)
        if action == "complaints":
            domain.complain(conn, user, order, data)
        else:
            domain.customer_action(conn, user, order, action, data)
        return domain.detail(conn, load(conn, ident, user, True))


@admin.get("")
def staff_orders(user=Depends(require("cashier", "inventory", "shipper"))):
    with reading() as conn:
        where, params = "", ()
        if user["role"] == "inventory":
            where, params = " WHERE shopper_id=?", (user["id"],)
        if user["role"] == "shipper":
            where, params = " WHERE shipper_id=?", (user["id"],)
        result = {
            "orders": [
                domain.detail(conn, o)
                for o in rows(
                    conn,
                    "SELECT * FROM errand_orders"
                    + where
                    + " ORDER BY id DESC LIMIT 150",
                    params,
                )
            ],
            "workers": rows(
                conn,
                "SELECT id,name,role FROM users WHERE active=1 AND role IN ('owner','inventory','shipper')",
            ),
            "settings": one(conn, "SELECT * FROM errand_settings WHERE id=1"),
            **directory(conn),
        }
        if user["role"] in {"owner", "inventory"}:
            result["products"] = rows(
                conn,
                "SELECT id,product_name,unit,price,stock FROM products WHERE active=1",
            )
        return result


@admin.post("/settings")
def settings(data: dict, user=Depends(require())):
    hours = number(
        data.get("complaint_hours"), "Thời hạn phản hồi", minimum=1, integer=True
    )
    if hours > 168:
        fail("Thời hạn phản hồi tối đa 168 giờ.")
    with transaction() as conn:
        conn.execute(
            "UPDATE errand_settings SET service_fee=?,complaint_hours=?,policy=? WHERE id=1",
            (
                money(data.get("service_fee")),
                hours,
                required(data, "policy", "Chính sách chất lượng và khiếu nại", 1000),
            ),
        )
    return {"success": True}


@admin.post("/{ident}/{action}")
def staff_action(
    ident: int,
    action: str,
    data: dict,
    request: Request,
    user=Depends(require("cashier", "inventory", "shipper")),
):
    with transaction() as conn:
        order = load(conn, ident, user)
        if action == "money":
            domain.book_money(
                conn, user, order, data, request.headers.get("idempotency-key")
            )
        elif action == "resolve":
            domain.resolve_complaint(conn, user, order, data)
        else:
            domain.staff_action(conn, user, order, action, data)
        return domain.detail(conn, load(conn, ident, user))


def media_user(request: Request):
    # Explicit account context avoids staff/customer session confusion in one browser.
    return (
        (current_user(request), False)
        if request.query_params.get("staff") == "1"
        else (customer_user(request), True)
    )


@media.post("/api/errands/{ident}/photos")
async def upload_photo(ident: int, request: Request, image: UploadFile = File(...)):
    user, customer = media_user(request)
    with reading() as conn:
        load(conn, ident, user, customer)
    raw = await image.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        fail("Ảnh tối đa 4 MB.", 413)
    try:
        with Image.open(BytesIO(raw)) as picture:
            if picture.width * picture.height > 16_000_000:
                fail("Ảnh có độ phân giải quá lớn.")
            picture.load()
            picture = picture.convert("RGB")
            picture.thumbnail((1600, 1600))
            output = BytesIO()
            picture.save(output, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        fail("Tệp phải là ảnh hợp lệ.")
    folder = Path(config.SQLITE_PATH).parent / "errand-media"
    folder.mkdir(exist_ok=True)
    name = secrets.token_hex(16) + ".jpg"
    target = folder / name
    target.write_bytes(output.getvalue())
    try:
        with transaction() as conn:
            load(conn, ident, user, customer)
            conn.execute(
                "INSERT INTO errand_photos(name,order_id) VALUES(?,?)", (name, ident)
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"url": f"/api/errands/{ident}/photos/{name}"}


@media.get("/api/errands/{ident}/photos/{name}")
def view_photo(ident: int, name: str, request: Request):
    user, customer = media_user(request)
    with reading() as conn:
        load(conn, ident, user, customer)
        if not one(
            conn,
            "SELECT name FROM errand_photos WHERE name=? AND order_id=?",
            (name, ident),
        ):
            fail("Không tìm thấy ảnh.", 404)
    path = Path(config.SQLITE_PATH).parent / "errand-media" / name
    if not path.is_file():
        fail("Ảnh không còn trên máy chủ.", 404)
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )
