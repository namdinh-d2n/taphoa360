"""Public browsing, authenticated checkout and staff fulfilment."""

from io import BytesIO
from pathlib import Path
import hashlib, re, secrets
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import Response
import config
from .common import fail, required, money, quantity, record, audit, validate_payload
from .auth import require
from .shop_auth import customer_user, limited
from .database import reading, transaction, rows, one
from . import commerce as shop, inventory as stock
from . import online_workflow as workflow

public = APIRouter(prefix="/api/shop", dependencies=[Depends(validate_payload)])
admin = APIRouter(prefix="/api/v1/shop", dependencies=[Depends(validate_payload)])
media = APIRouter()


@public.get('/locations')
def vietnam_provinces():
    from .locations import provinces
    return provinces()


@public.get('/locations/{province_code}/wards')
def vietnam_wards(province_code:int):
    from .locations import wards
    return wards(province_code)


@admin.get('/categories')
def catalog_categories(user=Depends(require('inventory','cashier'))):
    from .catalog_data import category_groups
    with reading() as conn:return category_groups(p['category'] for p in stock.products(conn))


@public.get("/catalog")
def catalog(
    q: str = "",
    category: str = "",
    storage: str = "",
    sort: str = "relevant",
    cart: str = "",
    interest: str = "",
    brand: str = "",
):
    ids = {int(v) for v in cart.split(",")[:50] if v.isdigit()}
    with transaction() as conn:
        shop.expire_pending(conn)
        return shop.public_catalog(
            conn, q[:100], category[:80], storage[:20], sort, ids, interest[:80],brand[:80]
        )


@public.get("/budget")
def budget(amount: int = 50000, kind: str = "breakfast"):
    with reading() as conn:
        return shop.budget(conn, amount, kind)


@public.get('/products/{ident}')
def storefront_product(ident:int):
    from .product_discovery import product_details
    with reading() as conn:return product_details(conn,ident)


@public.post("/quote")
def quote(data: dict, user=Depends(customer_user)):
    with transaction() as conn:
        shop.expire_pending(conn)
        return shop.quote(conn, data, user)


@public.post("/orders")
def place(data: dict, request: Request, user=Depends(customer_user)):
    with transaction() as conn:
        shop.expire_pending(conn)
        return shop.place(conn, user, data, request.headers.get("idempotency-key"))


@public.get("/orders")
def my_orders(user=Depends(customer_user)):
    with transaction() as conn:
        shop.expire_pending(conn)
        account = record(conn, "shop_accounts", user["id"])
        result = []
        for order in rows(
            conn,
            "SELECT * FROM online_orders WHERE account_id=? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        ):
            result.append(
                {
                    **shop.detail(conn, order, True),
                    "tracking_token": shop.track_token(order, account),
                }
            )
        return result


@public.get('/orders/{ident}')
def customer_order(ident:int,user=Depends(customer_user)):
    with transaction() as conn:
        shop.expire_pending(conn)
        order=record(conn,'online_orders',ident)
        if order['account_id']!=user['id']:fail('Không tìm thấy đơn.',404)
        return shop.detail(conn,order,True)


@public.get("/track/{token}")
def track(token: str):
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        fail("Không tìm thấy đơn.", 404)
    with transaction() as conn:
        shop.expire_pending(conn)
        order = one(
            conn,
            "SELECT * FROM online_orders WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
        if not order:
            fail("Không tìm thấy đơn.", 404)
        return shop.detail(conn, order)


@public.post("/orders/{ident}/approve")
def approve(ident: int, data: dict, user=Depends(customer_user)):
    with transaction() as conn:
        order = record(conn, "online_orders", ident)
        if order["account_id"] != user["id"]:
            fail("Không tìm thấy đơn.", 404)
        if (
            order["status"] != "REVIEW"
            or order["version"] != data.get("version")
            or order["expires_at"] <= shop.clock()
        ):
            fail("Phương án đã thay đổi hoặc hết hạn.", 409)
        conn.execute(
            "UPDATE online_orders SET approved=1,updated_at=? WHERE id=?",
            (shop.clock(), ident),
        )
        shop.event(
            conn,
            ident,
            "REVIEW",
            "Khách đã đồng ý phương án điều chỉnh phiên bản " + str(order["version"]),
        )
    return {"success": True}


@public.post('/orders/{ident}/report-payment')
def report_payment(ident:int,data:dict,user=Depends(customer_user)):
    with transaction() as conn:
        shop.expire_pending(conn);order=record(conn,'online_orders',ident)
        if order['account_id']!=user['id']:fail('Không tìm thấy đơn.',404)
        return workflow.report(conn,order,data)


def field(tag, text):
    value = str(text)
    return tag + str(len(value.encode("utf-8"))).zfill(2) + value


def qr_payload(bank, account, amount, reference):
    merchant = (
        field("00", "A000000727")
        + field("01", field("00", bank) + field("01", account))
        + field("02", "QRIBFTTA")
    )
    content = (
        field("00", "01")
        + field("01", "12")
        + field("38", merchant)
        + field("53", "704")
        + field("54", str(amount))
        + field("58", "VN")
        + field("62", field("08", reference))
        + "6304"
    )
    crc = 0xFFFF
    for byte in content.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
            )
    return content + f"{crc:04X}"


@public.get("/orders/{ident}/qr")
def bank_qr(ident: int, format:str='svg',user=Depends(customer_user)):
    if format not in {'svg','png'}:fail('Định dạng mã QR không hợp lệ.')
    with reading() as conn:
        order = record(conn, "online_orders", ident)
        if order["account_id"] != user["id"]:
            fail("Không tìm thấy đơn.", 404)
        allowed=order['status'] in {'CONFIRMED','SHIPPING'} or (order['payment_flow']=='PREPAY' and order['status']=='PENDING' and order['stock_reserved'] and order['expires_at']>shop.clock())
        if order["payment_method"] != "QR" or not allowed or order['payment_status']=='REPORTED':
            fail('QR chỉ hiện cho đơn đang chờ khách chuyển tiền; đơn báo đã chuyển đang chờ đối chiếu.',409)
        import json
        settings = json.loads(order['bank_snapshot']) if order['bank_snapshot'] else one(conn, "SELECT * FROM shop_settings WHERE id=1")
        amount=order['goods_total']+order['shipping_fee']-order['paid']
        if amount<=0:fail('Đơn đã được xác nhận thanh toán, không cần chuyển thêm.',409)
        if not(settings['bank_bin'] and settings['bank_account']):fail('Tiệm chưa cấu hình ngân hàng nhận chuyển khoản.',409)
    import qrcode
    from qrcode.image.svg import SvgPathImage

    code = qrcode.QRCode(box_size=10,border=4)
    code.add_data(qr_payload(
            settings["bank_bin"],
            settings["bank_account"],
            amount,
            order["code"],
        ))
    code.make(fit=True)
    image=code.make_image(image_factory=SvgPathImage) if format=='svg' else code.make_image(fill_color='black',back_color='white')
    buf = BytesIO()
    if format=='png':image.save(buf,format='PNG')
    else:image.save(buf)
    return Response(
        buf.getvalue(),
        media_type='image/png' if format=='png' else "image/svg+xml",
        headers={"Cache-Control": "no-store",'Content-Disposition':f'inline; filename="{order["code"]}-qr.{format}"'},
    )


@admin.get("/overview")
def overview(user=Depends(require("cashier", "inventory", "shipper"))):
    with transaction() as conn:
        shop.expire_pending(conn)
        orders = rows(
            conn,
            "SELECT * FROM online_orders "
            + ("WHERE shipper_id=? " if user["role"] == "shipper" else "")
            + "ORDER BY id DESC LIMIT 100",
            (user["id"],) if user["role"] == "shipper" else (),
        )
        result = {"orders": [shop.detail(conn, o, True) for o in orders],'permissions':workflow.permissions(conn,user)}
        if user["role"] == "shipper":
            return result
        result.update(
            products=stock.products(conn),
            zones=rows(conn, "SELECT * FROM delivery_zones"),
            shippers=rows(
                conn, "SELECT id,name FROM users WHERE role='shipper' AND active=1"
            ),
            workers=rows(conn,"SELECT id,name,role FROM users WHERE active=1 AND role IN ('cashier','inventory')"),
        )
        if user["role"] == "cashier":
            for p in result["products"]:
                p.pop("cost_price", None)
        if user["role"] == "owner":
            result.update(
                settings=one(conn, "SELECT * FROM shop_settings WHERE id=1"),
                banners=rows(conn, "SELECT * FROM shop_banners ORDER BY position,id"),
                sales=rows(
                    conn,
                    "SELECT s.*,p.product_name FROM timed_sales s JOIN products p ON p.id=s.product_id ORDER BY s.id DESC",
                ),
            )
        setting=one(conn,'SELECT online_cashier_id,online_dispatcher_id FROM shop_settings WHERE id=1')
        result['responsibilities']={key:one(conn,'SELECT id,name,role FROM users WHERE id=?',(value,)) if value else None for key,value in setting.items()}
        return result


@admin.post("/orders/{ident}/{action}")
def order_action(
    ident: int,
    action: str,
    data: dict,
    user=Depends(require("cashier", "inventory", "shipper")),
):
    with transaction() as conn:
        shop.expire_pending(conn)
        order = record(conn, "online_orders", ident)
        if user["role"] == "shipper" and (
            order["shipper_id"] != user["id"] or action not in {"deliver"}
        ):
            fail("Chỉ xử lý kiểm nhận đơn được phân công.", 403)
        if action in {'confirm','propose','cancel','ship'}:workflow.require_permission(conn,user,'dispatch')
        if action in {'paid','refund','reject-payment'}:workflow.require_permission(conn,user,'money')
        if action=='prepare':
            workflow.prepare(conn,user,order,data);return {'success':True}
        if action=='reject-payment':
            workflow.reject_report(conn,user,order,data);return {'success':True}
        if action=='paid' and order['payment_flow']=='PREPAY':return workflow.approve(conn,user,order,data)
        if action == "propose":
            shop.propose(conn, user, order, data)
        elif action == "confirm":
            shop.confirm(conn, user, order)
        elif action == "cancel":
            shop.cancel(conn, user, order, required(data, "reason", "Lý do hủy"))
        elif action == "paid":
            if user["role"] not in {"owner", "cashier"}:
                fail("Chỉ chủ tiệm/thu ngân xác nhận tiền.", 403)
            if (
                order["payment_method"] != "QR"
                or order["status"] not in {"CONFIRMED", "SHIPPING"}
                or order["paid"]
            ):
                fail("Đơn không chờ xác nhận tiền QR.", 409)
            amount = money(data.get("amount"))
            if amount != order["goods_total"] + order["shipping_fee"]:
                fail("Số tiền chuyển khoản phải khớp tổng đơn.")
            reference = required(data, "reference", "Mã giao dịch ngân hàng", 100)
            if one(
                conn,
                "SELECT id FROM online_orders WHERE payment_reference=?",
                (reference,),
            ):
                fail("Mã giao dịch đã được sử dụng.", 409)
            shop.money_entry(
                conn,
                user,
                order,
                amount,
                "TRANSFER",
                "ONLINE_PREPAY",
                reference=reference,
            )
            conn.execute(
                "UPDATE online_orders SET paid=?,payment_reference=?,payment_status='VERIFIED',updated_at=? WHERE id=?",
                (amount, reference, shop.clock(), ident),
            )
            shop.event(
                conn,
                ident,
                order["status"],
                "Nhân viên đã đối chiếu và xác nhận nhận tiền QR.",
            )
        elif action == "ship":
            if order["status"] != "CONFIRMED":
                fail("Chỉ giao đơn đã xác nhận.", 409)
            if (
                order["payment_method"] == "QR"
                and order["paid"] < order["goods_total"] + order["shipping_fee"]
            ):
                fail("Cần xác nhận tiền QR trước khi giao.", 409)
            if order['payment_flow']=='PREPAY':
                workflow.validate_held(conn,order)
                if one(conn,'SELECT id FROM online_items WHERE online_order_id=? AND is_picked=0',(ident,)):fail('Cần xác nhận đã soạn đủ từng món trước khi giao.',409)
            shipper = record(conn, "users", data.get("shipper_id"))
            if shipper["role"] != "shipper" or not shipper["active"]:
                fail("Chọn tài khoản giao hàng đang hoạt động.")
            conn.execute(
                "UPDATE online_orders SET status='SHIPPING',shipper_id=?,updated_at=? WHERE id=?",
                (shipper["id"], shop.clock(), ident),
            )
            shop.event(
                conn,
                ident,
                "SHIPPING",
                "Nhân viên đang giao. Bạn có thể kiểm hàng khi nhận.",
            )
        elif action == "deliver":
            return shop.deliver(conn, user, order, data)
        elif action == "refund":
            if user["role"] not in {"owner", "cashier"}:
                fail("Chỉ chủ tiệm/thu ngân xác nhận hoàn tiền.", 403)
            if order["refund_due"] <= order["refund_paid"]:
                fail("Không còn tiền cần hoàn.", 409)
            amount = money(data.get("amount"))
            reference = required(data, "reference", "Mã giao dịch/biên nhận hoàn", 100)
            if amount != order["refund_due"] - order["refund_paid"]:
                fail("Số tiền hoàn phải khớp khoản còn cần hoàn.")
            method = data.get("method", "TRANSFER")
            if method not in {"CASH", "TRANSFER"}:
                fail("Phương thức hoàn không hợp lệ.")
            shop.money_entry(
                conn,
                user,
                order,
                -amount,
                method,
                "ONLINE_REFUND",
                order["sale_order_id"],
                reference,
            )
            conn.execute(
                "UPDATE online_orders SET refund_paid=refund_paid+?,refund_reference=?,updated_at=? WHERE id=?",
                (amount, reference, shop.clock(), ident),
            )
            shop.event(
                conn,
                ident,
                order["status"],
                "Đã hoàn " + str(amount) + "đ; mã biên nhận " + reference,
            )
        else:
            fail("Thao tác không hợp lệ.", 404)
        audit(
            conn,
            user,
            "ONLINE_" + action.upper(),
            ident,
            {"reason": str(data.get("reason", ""))[:500]},
        )
    return {"success": True}


@admin.get('/finance')
def online_finance(user=Depends(require('cashier'))):
    with reading() as conn:
        workflow.require_permission(conn,user,'money');return workflow.finance(conn)


@admin.post('/finance/expenses')
def online_expense(data:dict,request:Request,user=Depends(require('cashier'))):
    with transaction() as conn:return workflow.expense(conn,user,data,request.headers.get('idempotency-key'))


@admin.post('/finance/handovers')
def online_handover(data:dict,user=Depends(require('cashier'))):
    with transaction() as conn:return workflow.handover(conn,user,data)


@admin.post('/responsibilities')
def assign_responsibilities(data:dict,user=Depends(require())):
    values={}
    with transaction() as conn:
        for key,roles in [('online_cashier_id',{'cashier'}),('online_dispatcher_id',{'cashier','inventory'})]:
            ident=data.get(key)
            if ident:
                person=record(conn,'users',ident)
                if not person['active'] or person['role'] not in roles:fail('Chọn nhân viên đúng vai trò đang hoạt động.')
            values[key]=ident or None
        conn.execute('UPDATE shop_settings SET online_cashier_id=?,online_dispatcher_id=? WHERE id=1',(values['online_cashier_id'],values['online_dispatcher_id']))
        audit(conn,user,'ASSIGN_ONLINE_RESPONSIBILITIES',1,values)
    return {'success':True}


@admin.post("/settings")
def settings(data: dict, user=Depends(require())):
    bank = str(data.get("bank_bin", "")).strip()
    account = str(data.get("bank_account", "")).strip()
    if (bank or account) and (
        not re.fullmatch(r"\d{6}", bank)
        or not re.fullmatch(r"[0-9A-Za-z]{5,30}", account)
    ):
        fail("Mã BIN ngân hàng gồm 6 số; số tài khoản 5–30 ký tự chữ/số.")
    with transaction() as conn:
        conn.execute(
            "UPDATE shop_settings SET store_name=?,bank_bin=?,bank_account=?,bank_name=?,delivery_note=?,accepting_orders=? WHERE id=1",
            (
                required(data, "store_name", "Tên tiệm", 100),
                bank,
                account,
                str(data.get("bank_name", ""))[:100],
                str(data.get("delivery_note", ""))[:300],
                int(bool(data.get("accepting_orders", True))),
            ),
        )
        audit(conn, user, "SHOP_SETTINGS", 1, {"store_name": data["store_name"]})
    return {"success": True}


@admin.post("/zones")
def zone(data: dict, user=Depends(require())):
    with transaction() as conn:
        values = (
            required(data, "name", "Khu giao", 100),
            money(data.get("fee", 0)),
            money(data.get("minimum_order", 0)),
            str(data.get("eta", ""))[:150],
            int(bool(data.get("active", True))),
        )
        if data.get("id"):
            record(conn, "delivery_zones", data["id"])
            conn.execute(
                "UPDATE delivery_zones SET name=?,fee=?,minimum_order=?,eta=?,active=? WHERE id=?",
                (*values, data["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO delivery_zones(name,fee,minimum_order,eta,active) VALUES(?,?,?,?,?)",
                values,
            )
        audit(conn, user, "SHOP_ZONE", data.get("id", "new"), {"name": data["name"]})
    return {"success": True}


def image_path(value):
    value = str(value or "")
    if value and not re.fullmatch(r"(?:/shop-media/[a-f0-9]{32}|/static/catalog-images/ref-bhx-[0-9]+)\.webp", value):
        fail("Chọn ảnh đã tải lên cửa hàng.")
    return value


@admin.post("/banners")
def banner(data: dict, user=Depends(require())):
    start = shop.stamp(data["starts_at"]) if data.get("starts_at") else None
    end = shop.stamp(data["ends_at"]) if data.get("ends_at") else None
    if start and end and end <= start:
        fail("Ngày kết thúc phải sau ngày bắt đầu.")
    theme = data.get("theme", "GREEN")
    if theme not in {"GREEN", "ORANGE", "BLUE"}:
        fail("Màu banner không hợp lệ.")
    with transaction() as conn:
        values = (
            required(data, "title", "Tiêu đề", 120),
            str(data.get("subtitle", ""))[:250],
            theme,
            image_path(data.get("image_path")),
            str(data.get("category", ""))[:80],
            start,
            end,
            int(bool(data.get("active", True))),
            quantity(data.get("position", 0), allow_zero=True),
        )
        if data.get("id"):
            record(conn, "shop_banners", data["id"])
            conn.execute(
                "UPDATE shop_banners SET title=?,subtitle=?,theme=?,image_path=?,category=?,starts_at=?,ends_at=?,active=?,position=? WHERE id=?",
                (*values, data["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO shop_banners(title,subtitle,theme,image_path,category,starts_at,ends_at,active,position) VALUES(?,?,?,?,?,?,?,?,?)",
                values,
            )
        audit(
            conn, user, "SHOP_BANNER", data.get("id", "new"), {"title": data["title"]}
        )
    return {"success": True}


@admin.post("/sales")
def timed_sale(data: dict, user=Depends(require())):
    with transaction() as conn:
        if data.get("id") and set(data) <= {"id", "active"}:
            old = record(conn, "timed_sales", data["id"])
            if data["active"]:
                if old["ends_at"] <= shop.clock():
                    fail("Khung sale đã kết thúc. Hãy tạo lịch mới.")
                if one(
                    conn,
                    "SELECT id FROM timed_sales WHERE product_id=? AND active=1 AND starts_at<? AND ends_at>? AND id!=?",
                    (old["product_id"], old["ends_at"], old["starts_at"], old["id"]),
                ):
                    fail("Có khung sale đang trùng thời gian.", 409)
            conn.execute(
                "UPDATE timed_sales SET active=? WHERE id=?",
                (int(bool(data["active"])), data["id"]),
            )
            audit(
                conn,
                user,
                "TIMED_SALE_ACTIVE",
                data["id"],
                {"active": bool(data["active"])},
            )
            return {"success": True}
        p = record(conn, "products", data.get("product_id"))
        start = shop.stamp(data.get("starts_at"))
        end = shop.stamp(data.get("ends_at"))
        if end <= start or end <= shop.clock():
            fail("Khung sale cần kết thúc sau bắt đầu và sau hiện tại.")
        price = money(data.get("price"))
        count = quantity(data.get("max_units"))
        if not price or price >= p["price"]:
            fail("Giá sale phải lớn hơn 0 và thấp hơn giá bán thường.")
        available = stock.products(conn)
        if count > next(i["sellable_stock"] for i in available if i["id"] == p["id"]):
            fail("Giới hạn sale vượt tồn bán được.", 409)
        batch_id = data.get("batch_id") or None
        if batch_id:
            b = record(conn, "stock_batches", batch_id)
            if (
                b["product_id"] != p["id"]
                or b["quality_status"] != "SELLABLE"
                or b["remaining"] < count
            ):
                fail("Lô sale không phù hợp hoặc thiếu tồn.")
            if (b["expires_on"] and end[:10] > b["expires_on"]) or (
                b["sell_until"] and end > b["sell_until"]
            ):
                fail("Sale không được kéo dài quá hạn/giờ ngừng bán.")
        if one(
            conn,
            "SELECT id FROM timed_sales WHERE product_id=? AND active=1 AND starts_at<? AND ends_at>?",
            (p["id"], end, start),
        ):
            fail("Sản phẩm đã có khung sale trùng thời gian.", 409)
        conn.execute(
            "INSERT INTO timed_sales(name,product_id,batch_id,price,max_units,starts_at,ends_at,active) VALUES(?,?,?,?,?,?,?,1)",
            (
                required(data, "name", "Tên sale", 100),
                p["id"],
                batch_id,
                price,
                count,
                start,
                end,
            ),
        )
        audit(
            conn,
            user,
            "TIMED_SALE",
            p["id"],
            {"start": start, "end": end, "price": price},
        )
    return {"success": True}


@admin.get("/perishables")
def perishables(user=Depends(require("inventory"))):
    with reading() as conn:
        return rows(
            conn,
            """SELECT b.*,p.product_name,p.storage_kind,p.price,p.unit FROM stock_batches b JOIN products p ON p.id=b.product_id
            WHERE b.remaining>0 AND (p.storage_kind IN ('FRESH','FROZEN','CHILLED') OR b.quality_status!='SELLABLE' OR b.sell_until IS NOT NULL) ORDER BY b.sell_until IS NULL,b.sell_until,b.expires_on""",
        )


@admin.post("/batches/{ident}/quality")
def quality(ident: int, data: dict, user=Depends(require("inventory"))):
    reason = required(data, "reason", "Lý do/biên bản kiểm tra", 500)
    status = data.get("quality_status")
    if status not in {"SELLABLE", "HOLD", "DISPOSED"}:
        fail("Trạng thái chất lượng không hợp lệ.")
    cutoff = shop.stamp(data["sell_until"]) if data.get("sell_until") else None
    with transaction() as conn:
        b = record(conn, "stock_batches", ident)
        if b["sell_until"] and (cutoff is None or cutoff > b["sell_until"]):
            fail(
                "Không kéo dài giờ ngừng bán đã đặt; hãy kiểm tra và nhập lô mới đúng thực tế."
            )
        if status == "SELLABLE" and (
            (b["expires_on"] and b["expires_on"] < shop.clock()[:10])
            or (cutoff and cutoff <= shop.clock())
        ):
            fail("Lô đã qua hạn/giờ ngừng bán không thể đưa bán lại.")
        if status == "DISPOSED" and b["remaining"]:
            stock.movement(
                conn,
                user,
                b["product_id"],
                ident,
                -b["remaining"],
                "DAMAGE",
                ident,
                reason,
            )
            conn.execute("UPDATE stock_batches SET remaining=0 WHERE id=?", (ident,))
        conn.execute(
            "UPDATE stock_batches SET quality_status=?,sell_until=? WHERE id=?",
            (status, cutoff, ident),
        )
        audit(
            conn,
            user,
            "BATCH_QUALITY",
            ident,
            {"status": status, "cutoff": cutoff, "reason": reason},
        )
    return {"success": True}


@media.post("/api/v1/shop/upload")
def upload(image: UploadFile = File(...), user=Depends(require("inventory"))):
    try:
        content = image.file.read(4 * 1024 * 1024 + 1)
        if len(content) > 4 * 1024 * 1024:
            fail("Ảnh tối đa 4 MB.", 413)
        from PIL import Image, ImageOps, UnidentifiedImageError

        try:
            img = Image.open(BytesIO(content))
            if (
                img.format not in {"PNG", "JPEG", "WEBP"}
                or img.width * img.height > 16000000
            ):
                fail("Chọn ảnh JPG/PNG/WebP tối đa 16 triệu điểm ảnh.")
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((1600, 1600))
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ):
            fail("Không đọc được ảnh.")
        folder = config.BASE_DIR / ".local" / "shop-media"
        folder.mkdir(parents=True, exist_ok=True)
        name = secrets.token_hex(16) + ".webp"
        img.save(folder / name, "WEBP", quality=85)
        return {"path": "/shop-media/" + name}
    finally:
        image.file.close()


@admin.post("/products/{ident}/image")
def product_image(ident: int, data: dict, user=Depends(require("inventory"))):
    with transaction() as conn:
        record(conn, "products", ident)
        conn.execute(
            "UPDATE products SET image_path=? WHERE id=?",
            (image_path(data.get("path")), ident),
        )
    return {"success": True}
