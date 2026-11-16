"""Public catalogue and customer orders; prices and inventory stay server-owned."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
import hashlib, hmac, json, math, re, secrets
from .common import fail, required, money, quantity, objects, record, audit, rounded
from .database import rows, one
from . import inventory as stock, rescue
from .shop_auth import phone_number
from .catalog_data import category_groups,group_for
from .locations import address_snapshot

STORAGE = {
    "FRESH": "Hàng tươi",
    "FROZEN": "Đông lạnh",
    "CHILLED": "Bảo quản mát",
    "DRY": "Đồ khô",
    "HOUSEHOLD": "Gia dụng",
}


def clock():
    return stock.local_now()


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value))
        if result.tzinfo is not None:
            fail("Dùng thời gian Việt Nam, không kèm múi giờ.")
        return result.replace(microsecond=0).isoformat()
    except (ValueError, TypeError):
        fail("Ngày giờ cần có dạng YYYY-MM-DDTHH:MM.")


def normalize(value):
    from .invoice_ai import normalize

    return normalize(value)


def available_batches(conn, pid):
    return rescue.batches(conn, pid)


def sale_remaining(conn, sale):
    sold = one(
        conn,
        """SELECT COALESCE(SUM(i.quantity),0) n FROM online_items i JOIN online_orders o ON o.id=i.online_order_id
        WHERE i.sale_id=? AND o.stock_reserved=1 AND o.status IN ('PENDING','PAYMENT_REVIEW','CONFIRMED','SHIPPING')""",
        (sale["id"],),
    )["n"]
    sold += one(
        conn,
        "SELECT COALESCE(SUM(i.quantity),0) n FROM order_items i JOIN orders o ON o.id=i.order_id WHERE i.timed_sale_id=? AND o.status!='CANCELLED'",
        (sale["id"],),
    )["n"]
    return max(0, sale["max_units"] - sold)


def effective_price(conn, p, at=None):
    at = at or clock()
    base = rescue.selling_price(p)
    candidates = rows(
        conn,
        """SELECT * FROM timed_sales WHERE product_id=? AND active=1 AND starts_at<=? AND ends_at>?
        ORDER BY price,id""",
        (p["id"], at, at),
    )
    for sale in candidates:
        if sale["price"] >= base or sale_remaining(conn, sale) < 1:
            continue
        if sale["batch_id"]:
            batches = available_batches(conn, p["id"])
            if not batches or batches[0]["id"] != sale["batch_id"]:
                continue
        return sale["price"], sale
    return base, None


def public_catalog(
    conn, q="", category="", storage="", sort="relevant", cart=(), interest="",brand=""
):
    allproducts = stock.products(conn)
    since = (datetime.fromisoformat(clock()) - timedelta(days=28)).date().isoformat()
    stats = rows(
        conn,
        """SELECT i.product_id,SUM(i.quantity-i.returned_qty) units,COUNT(DISTINCT o.id) orders
        FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.status IN ('COMPLETED','PARTIAL_RETURN')
        AND o.managed=1 AND o.created_at>=? GROUP BY i.product_id""",
        (since,),
    )
    popularity = {i["product_id"]: i["orders"] for i in stats}
    pairs = Counter()
    if cart:
        values = rows(
            conn,
            """SELECT DISTINCT o.id,i.product_id FROM orders o JOIN order_items i ON i.order_id=o.id
            WHERE o.status IN ('COMPLETED','PARTIAL_RETURN') AND o.managed=1 AND o.created_at>=? AND i.quantity>i.returned_qty""",
            (since,),
        )
        baskets = defaultdict(set)
        for v in values:
            baskets[v["id"]].add(v["product_id"])
        for ids in baskets.values():
            if ids.intersection(cart):
                for pid in ids - set(cart):
                    pairs[pid] += 1
    output = []
    categories = set()
    for p in allproducts:
        if not p["active"] or not p["online_enabled"]:
            continue
        categories.add(p["category"])
        if category and p["category"] != category:
            continue
        if storage and p["storage_kind"] != storage:
            continue
        if brand and ' '.join(p['brand'].casefold().split())!=' '.join(brand.casefold().split()):continue
        if q and normalize(q) not in normalize(
            p["product_name"] + " " + p["category"] + " " + p["sku"]
        ):
            continue
        price, sale = effective_price(conn, p)
        batches = available_batches(conn, p["id"])
        first = batches[0] if batches else None
        score = (
            min(popularity.get(p["id"], 0), 50)
            + pairs[p["id"]] * 10
            + (30 if interest and interest == p["category"] else 0)
        )
        reason = (
            ("Mua chung trong " + str(pairs[p["id"]]) + " đơn gần đây")
            if pairs[p["id"]] >= 3
            else "Vì bạn vừa xem " + interest
            if interest == p["category"]
            else "Được mua trong " + str(popularity[p["id"]]) + " đơn gần đây"
            if popularity.get(p["id"])
            else "Khám phá thêm từ tiệm"
        )
        entry = {
            k: p[k]
            for k in [
                "id",
                "product_name",
                "sku",
                "unit",
                "category",
                "storage_kind",
                "description",
                "image_path",
                "brand",
                "catalog_origin",
            ]
        }
        entry.update(
            category_group=group_for(p['category']),
            reference_source=p['reference_source'] if p['catalog_origin']=='REFERENCE' else '',
            reference_checked_at=p['reference_checked_at'] if p['catalog_origin']=='REFERENCE' else '',
            price=price,
            regular_price=rescue.selling_price(p),
            stock=p["sellable_stock"],
            reason=reason,
            expiry=first["expires_on"] if first else None,
            sell_until=first["sell_until"] if first else None,
            sale={
                "id": sale["id"],
                "name": sale["name"],
                "ends_at": sale["ends_at"],
                "remaining": sale_remaining(conn, sale),
            }
            if sale
            else None,
            _score=score,
        )
        output.append(entry)
    output.sort(
        key=lambda p: (
            p["stock"] <= 0,
            p["price"]
            if sort == "price"
            else -popularity.get(p["id"], 0)
            if sort == "popular"
            else -p["_score"],
            p["product_name"],
        )
    )
    for p in output:
        p.pop("_score")
    settings = one(
        conn,
        "SELECT store_name,delivery_note,accepting_orders FROM shop_settings WHERE id=1",
    )
    at = clock()
    banners = rows(
        conn,
        """SELECT id,title,subtitle,theme,image_path,category FROM shop_banners WHERE active=1
        AND (starts_at IS NULL OR starts_at<=?) AND (ends_at IS NULL OR ends_at>?) ORDER BY position,id""",
        (at, at),
    )
    combos = []
    online_ids = {p["id"] for p in allproducts if p["active"] and p["online_enabled"]}
    for c in rescue.campaigns(conn):
        if c["product_id"] not in online_ids or c["partner_id"] not in online_ids:
            continue
        combo = {
            k: c[k]
            for k in [
                "id",
                "name",
                "price",
                "product_id",
                "partner_id",
                "product_name",
                "partner_name",
                "product_unit",
                "partner_unit",
                "expires_on",
                "available_sets",
            ]
        }
        combo["condition"] = "Dùng sớm; giao trước hạn dùng và giờ ngừng bán của lô."
        combos.append(combo)
    return {
        "products": output,
        "categories": sorted(categories),
        "category_groups":category_groups(categories),
        'brands':sorted({p['brand'] for p in allproducts if p['active'] and p['online_enabled'] and p['brand'].strip()},key=str.casefold),
        "storage_types": STORAGE,
        "banners": banners,
        "combos": combos,
        "zones": rows(
            conn,
            "SELECT id,name,fee,minimum_order,eta FROM delivery_zones WHERE active=1 ORDER BY id",
        ),
        "settings": settings,
        "server_time": at,
    }


def budget(conn, budget, kind):
    ceiling = money(budget)
    if not 10000 <= ceiling <= 2000000:
        fail("Ngân sách từ 10.000đ đến 2.000.000đ.")
    data = public_catalog(conn)["products"]
    terms = (
        ["banh", "sua", "yen mach", "ngu coc"]
        if kind == "breakfast"
        else ["gao", "mi", "dau an", "nuoc", "giay", "trung", "sua"]
    )
    candidates = [
        p
        for p in data
        if p["stock"] > 0
        and p["price"] > 0
        and (kind != "breakfast" or p["storage_kind"] != "HOUSEHOLD")
    ]
    candidates.sort(
        key=lambda p: (
            -sum(term in normalize(p["product_name"]) for term in terms),
            p["price"],
        )
    )
    selected = []
    spent = 0
    groups = set()
    for p in candidates:
        if len(selected) >= 5:
            break
        if spent + p["price"] <= ceiling and (
            p["category"] not in groups or len(selected) < 2
        ):
            selected.append({**p, "quantity": 1})
            spent += p["price"]
            groups.add(p["category"])
    return {
        "items": selected,
        "total": spent,
        "budget": ceiling,
        "remaining": ceiling - spent,
        "note": "Chưa gồm phí giao; bạn có thể sửa từng món trước khi thêm giỏ.",
    }


def quote(conn, data, account):
    if 'address_mode' in data:address_snapshot(data)
    settings = one(conn, "SELECT * FROM shop_settings WHERE id=1")
    if not settings["accepting_orders"]:
        fail("Tiệm đang tạm dừng nhận đơn online.", 409)
    zone = record(conn, "delivery_zones", data.get("zone_id"))
    if not zone["active"]:
        fail("Tiệm chưa giao tới khu vực này.", 409)
    method = data.get("payment_method", "COD")
    if method not in {"COD", "QR"}:
        fail("Chọn COD hoặc chuyển khoản QR.")
    if method == "QR" and not (settings["bank_bin"] and settings["bank_account"]):
        fail("Tiệm chưa cấu hình ngân hàng nhận chuyển khoản.", 409)
    result = []
    seen = set()
    for item in objects(data.get("items"), "Giỏ hàng", maximum=50):
        p = record(conn, "products", item.get("product_id"))
        qty = quantity(item.get("quantity"))
        if p["id"] in seen or not p["active"] or not p["online_enabled"]:
            fail("Sản phẩm bị lặp hoặc ngừng bán online.")
        seen.add(p["id"])
        batches = available_batches(conn, p["id"])
        capacity = math.floor(round(sum(b["remaining"] for b in batches), 3))
        if qty > capacity:
            fail(p["product_name"] + ": không đủ tồn, hãy cập nhật giỏ.", 409)
        price, sale = effective_price(conn, p)
        if sale and (
            qty > sale_remaining(conn, sale)
            or (sale["batch_id"] and qty > math.floor(batches[0]["remaining"]))
        ):
            fail("Số lượng vượt giới hạn sale/lô còn lại.", 409)
        result.append(
            {
                "product_id": p["id"],
                "product_name": p["product_name"],
                "unit": p["unit"],
                "storage_kind": p["storage_kind"],
                "quantity": qty,
                "price": price,
                "total": money(price * qty),
                "sale_id": sale["id"] if sale else None,
                "points_part": 0,
            }
        )
    if data.get("rescue_campaign_id"):
        count = quantity(data.get("rescue_sets", 1))
        campaign = rescue.campaign_state(
            conn, record(conn, "rescue_campaigns", data["rescue_campaign_id"])
        )
        lookup = {i["product_id"]: i for i in result}
        if campaign["available_sets"] < count or any(
            pid not in lookup or lookup[pid]["quantity"] < count
            for pid in [campaign["product_id"], campaign["partner_id"]]
        ):
            fail("Combo không còn đủ hàng hoặc lượt bán.", 409)
        first, second = [
            lookup[pid] for pid in [campaign["product_id"], campaign["partner_id"]]
        ]
        if first["sale_id"] or second["sale_id"]:
            fail(
                "Combo không cộng với sale theo giờ. Hãy chọn mua lẻ hoặc combo riêng."
            )
        discount = (first["price"] + second["price"] - campaign["price"]) * count
        if discount < 0:
            fail("Giá combo cần được cửa hàng kiểm tra lại.", 409)
        a = rounded(
            Decimal(discount) * first["price"] / (first["price"] + second["price"])
        )
        first["total"] -= a
        second["total"] -= discount - a
    points = quantity(data.get("points_used", 0), allow_zero=True)
    customer = record(conn, "customers", account["customer_id"])
    if points > customer["points"]:
        fail("Bạn không đủ điểm để đổi.", 409)
    if points and data.get("rescue_campaign_id"):
        fail("Combo dùng sớm không cộng đổi điểm.")
    if points > sum(i["total"] // 100 for i in result):
        fail("Điểm đổi vượt tiền hàng.")
    left = points
    for i in result:
        i["points_part"] = min(left, i["total"] // 100)
        left -= i["points_part"]
    goods = money(sum(i["total"] for i in result) - points * 100)
    if goods < zone["minimum_order"]:
        fail("Đơn tối thiểu tại khu vực này là " + str(zone["minimum_order"]) + "đ.")
    total = money(goods + zone["fee"])
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "items": result,
                "goods": goods,
                "fee": zone["fee"],
                "zone": zone["id"],
                "method": method,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "items": result,
        "goods_total": goods,
        "shipping_fee": zone["fee"],
        "total": total,
        "points_used": points,
        "payment_method": method,
        "zone_id": zone["id"],
        "fingerprint": fingerprint,
        "eta": zone["eta"],
    }


def event(conn, ident, status, note=""):
    conn.execute(
        "INSERT INTO online_events(online_order_id,status,note,created_at) VALUES(?,?,?,?)",
        (ident, status, note[:500], clock()),
    )


def change_points(conn, order, amount, reason):
    if not amount:
        return
    account = record(conn, "shop_accounts", order["account_id"])
    conn.execute(
        "UPDATE customers SET points=MAX(0,points+?) WHERE id=?",
        (amount, account["customer_id"]),
    )
    conn.execute(
        "INSERT INTO shop_points_ledger(account_id,online_order_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
        (account["id"], order["id"], amount, reason, clock()),
    )


def track_token(order, account):
    return hmac.new(
        account["password_hash"].encode(),
        ("track:" + order["request_key"]).encode(),
        hashlib.sha256,
    ).hexdigest()


def place(conn, account, data, key):
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        fail("Thiếu mã chống tạo trùng đơn.")
    request_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    old = one(conn, "SELECT * FROM online_orders WHERE request_key=?", (key,))
    full_account = record(conn, "shop_accounts", account["id"])
    if old:
        if old["account_id"] != account["id"] or old["request_hash"] != request_hash:
            fail("Mã đơn đã được dùng cho yêu cầu khác.", 409)
        return {
            "id": old["id"],
            "token": track_token(old, full_account),
            "replayed": True,
        }
    if (
        one(
            conn,
            "SELECT COUNT(*) n FROM online_orders WHERE account_id=? AND ((status IN ('PENDING','REVIEW') AND expires_at>?) OR status='PAYMENT_REVIEW')",
            (account["id"], clock()),
        )["n"]
        >= 3
    ):
        fail("Bạn đang có 3 đơn chờ xác nhận. Hãy chờ tiệm xử lý.", 429)
    current = quote(conn, data, account)
    if data.get("fingerprint") != current["fingerprint"]:
        fail("Giá hoặc tồn đã thay đổi. Hãy kiểm tra lại giỏ trước khi đặt.", 409)
    substitution = data.get("substitution", "CALL")
    if substitution not in {"CALL", "DROP", "CONTACT"}:
        fail("Lựa chọn xử lý hết hàng không hợp lệ.")
    receiver = required(data, "receiver", "Người nhận", 100)
    phone = phone_number(data.get("phone"))
    address_data=address_snapshot(data)
    address = address_data['address']
    created = clock()
    expires = (datetime.fromisoformat(created) + timedelta(minutes=30)).isoformat()
    code = (
        "WEB-"
        + datetime.fromisoformat(created).strftime("%Y%m%d")
        + "-"
        + secrets.token_hex(4).upper()
    )
    token = hmac.new(
        full_account["password_hash"].encode(),
        ("track:" + key).encode(),
        hashlib.sha256,
    ).hexdigest()
    ident = conn.execute(
        """INSERT INTO online_orders(code,account_id,token_hash,request_key,request_hash,payment_method,receiver,phone,address,zone_id,shipping_fee,goods_total,points_used,substitution,note,expires_at,created_at,updated_at,rescue_campaign_id,rescue_sets)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            code,
            account["id"],
            hashlib.sha256(token.encode()).hexdigest(),
            key,
            request_hash,
            current["payment_method"],
            receiver,
            phone,
            address,
            current["zone_id"],
            current["shipping_fee"],
            current["goods_total"],
            current["points_used"],
            substitution,
            str(data.get("note", ""))[:500],
            expires,
            created,
            created,
            data.get("rescue_campaign_id"),
            quantity(data.get("rescue_sets", 1))
            if data.get("rescue_campaign_id")
            else 0,
        ),
    ).lastrowid
    for item in current["items"]:
        insert_item(conn, ident, item)
    conn.execute('UPDATE online_orders SET address_mode=?,province_code=?,ward_code=?,address_line=? WHERE id=?',
                 (address_data['address_mode'],address_data['province_code'],address_data['ward_code'],address_data['address_line'],ident))
    order = record(conn, "online_orders", ident)
    change_points(conn, order, -current["points_used"], "Giữ điểm cho đơn " + code)
    if current['payment_method']=='QR':
        from .online_workflow import begin_payment
        begin_payment(conn,record(conn,'online_orders',ident))
    else:event(conn, ident, "PENDING", "Chờ tiệm xác nhận. Chưa thu tiền, chưa giữ hàng.")
    return {"id": ident, "token": token, "code": code}


def insert_item(conn, ident, item):
    conn.execute(
        """INSERT INTO online_items(online_order_id,product_id,product_name,unit,storage_kind,quantity,price,total,sale_id,points_part)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            ident,
            item["product_id"],
            item["product_name"],
            item["unit"],
            item["storage_kind"],
            item["quantity"],
            item["price"],
            item["total"],
            item.get("sale_id"),
            item.get("points_part", 0),
        ),
    )


def expire_pending(conn):
    for order in rows(
        conn,
        "SELECT * FROM online_orders WHERE status IN ('PENDING','REVIEW') AND expires_at<=?",
        (clock(),),
    ):
        if order['payment_flow']=='PREPAY' and order['stock_reserved']:
            from .online_workflow import release
            release(conn,order,{'id':None},'ONLINE_EXPIRE')
        change_points(
            conn, order, order["points_used"], "Hoàn điểm đơn hết thời gian xác nhận"
        )
        conn.execute(
            "UPDATE online_orders SET status='EXPIRED',points_used=0,updated_at=? WHERE id=?",
            (clock(), order["id"]),
        )
        event(
            conn,
            order["id"],
            "EXPIRED",
            "Đơn hết thời gian chờ, hãy kiểm tra giá và đặt lại.",
        )


def detail(conn, order, private=False):
    safe = {
        k: order[k]
        for k in [
            "id",
            "code",
            "status",
            "payment_method",
            "paid",
            "refund_due",
            "refund_paid",
            "goods_total",
            "shipping_fee",
            "points_used",
            "points_earned",
            "version",
            "approved",
            "created_at",
            "updated_at",
            "expires_at",
            "payment_flow","payment_status","payment_reported_at","payment_note","stock_reserved",
        ]
    }
    safe["total"] = order["goods_total"] + order["shipping_fee"]
    safe["substitution"] = order["substitution"]
    safe['invoice']=one(conn,'SELECT code,issued_at FROM online_invoices WHERE online_order_id=?',(order['id'],))
    safe["items"] = rows(
        conn,
        "SELECT id,product_id,product_name,unit,storage_kind,quantity,price,total,points_part,accepted,is_picked FROM online_items WHERE online_order_id=? ORDER BY id",
        (order["id"],),
    )
    for item in safe["items"]:
        if item["accepted"] is None:
            item["charged_total"] = item["total"] - item["points_part"] * 100
        else:
            base = rounded(Decimal(item["total"]) * item["accepted"] / item["quantity"])
            kept = min(
                item["points_part"] * item["accepted"] // item["quantity"], base // 100
            )
            item["charged_total"] = base - kept * 100
    safe["events"] = rows(
        conn,
        "SELECT status,note,created_at FROM online_events WHERE online_order_id=? ORDER BY id",
        (order["id"],),
    )
    # Bearer tracking links show progress and money, never address/phone or account details.
    if private:
        safe.update(
            receiver=order["receiver"],
            phone=order["phone"],
            address=order["address"],
            zone_id=order["zone_id"],
            shipper_id=order["shipper_id"],
            payment_reference=order["payment_reference"],
            note=order["note"],
            picker_id=order["picker_id"],
        )
        if order["payment_method"] == "QR" and order["status"] in {
            "PENDING","PAYMENT_REVIEW",
            "CONFIRMED",
            "SHIPPING",
        }:
            settings = json.loads(order["bank_snapshot"]) if order["bank_snapshot"] else one(
                conn,
                "SELECT bank_bin,bank_account,bank_name FROM shop_settings WHERE id=1",
            )
            safe["bank"] = {
                **settings,
                "reference": order["code"],
                "amount": max(0, safe["total"] - order["paid"]),
            }
    return safe


def propose(conn, user, order, data):
    if order['payment_flow']=='PREPAY':fail('Đơn QR có số tiền cố định. Hãy hủy/đối chiếu hoàn tiền và đề nghị khách đặt đơn mới.',409)
    if order["status"] not in {"PENDING", "REVIEW"}:
        fail("Chỉ điều chỉnh đơn chưa xác nhận.", 409)
    if order["rescue_campaign_id"]:
        fail("Đơn combo cần khách hủy và đặt lại khi thiếu hàng.", 409)
    # All substitutions/shortages require explicit customer approval, including DROP.
    account = record(conn, "shop_accounts", order["account_id"])
    change_points(
        conn, order, order["points_used"], "Trả điểm để xem phương án thay đổi"
    )
    payload = {
        **data,
        "zone_id": order["zone_id"],
        "payment_method": order["payment_method"],
        "points_used": 0,
    }
    revised = quote(conn, payload, account)
    conn.execute("DELETE FROM online_items WHERE online_order_id=?", (order["id"],))
    for item in revised["items"]:
        insert_item(conn, order["id"], item)
    conn.execute(
        "UPDATE online_orders SET status='REVIEW',goods_total=?,points_used=0,version=version+1,approved=0,updated_at=?,expires_at=? WHERE id=?",
        (
            revised["goods_total"],
            clock(),
            (datetime.fromisoformat(clock()) + timedelta(minutes=30)).isoformat(),
            order["id"],
        ),
    )
    reason = required(data, "reason", "Lý do thay đổi", 400)
    event(
        conn,
        order["id"],
        "REVIEW",
        "Tiệm đề nghị điều chỉnh: " + reason + ". Khách cần duyệt trên trang đơn.",
    )
    audit(conn, user, "PROPOSE_ONLINE_ORDER", order["id"], {"reason": reason})


def confirm(conn, user, order):
    if order['payment_flow']=='PREPAY':fail('Cần khách báo đã chuyển, thu ngân đối chiếu và duyệt thanh toán.',409)
    if order["status"] not in {"PENDING", "REVIEW"} or not order["approved"]:
        fail("Cần khách duyệt thay đổi trước khi xác nhận.", 409)
    if order["expires_at"] <= clock():
        fail("Đơn đã hết thời gian chờ xác nhận.", 409)
    items = rows(
        conn, "SELECT * FROM online_items WHERE online_order_id=?", (order["id"],)
    )
    if order["rescue_campaign_id"]:
        c = rescue.campaign_state(
            conn, record(conn, "rescue_campaigns", order["rescue_campaign_id"])
        )
        if order["rescue_sets"] > c["available_sets"]:
            fail("Combo không còn đủ lượt.", 409)
    for item in items:
        p = record(conn, "products", item["product_id"])
        if not p["active"] or not p["online_enabled"]:
            fail("Có hàng đã ngừng bán, cần đề nghị điều chỉnh đơn.", 409)
        if item["sale_id"]:
            sale = record(conn, "timed_sales", item["sale_id"])
            if (
                not sale["active"]
                or not sale["starts_at"] <= clock() < sale["ends_at"]
                or sale_remaining(conn, sale) < item["quantity"]
            ):
                fail("Sale đã kết thúc hoặc hết lượt, cần khách đặt lại.", 409)
            if sale["batch_id"]:
                available = available_batches(conn, p["id"])
                if not available or available[0]["id"] != sale["batch_id"]:
                    fail("Lô sale không còn đứng đầu FEFO.", 409)
        allocation = stock.take_stock(
            conn, user, p["id"], item["quantity"], "ONLINE_HOLD", order["id"]
        )
        conn.execute(
            "UPDATE online_items SET allocations=? WHERE id=?",
            (json.dumps(allocation), item["id"]),
        )
    conn.execute(
        "UPDATE online_orders SET status='CONFIRMED',stock_reserved=1,updated_at=? WHERE id=?",
        (clock(), order["id"]),
    )
    event(
        conn,
        order["id"],
        "CONFIRMED",
        "Tiệm đã giữ hàng. Khách kiểm tra khi nhận; chỉ tính tiền phần nhận thực tế.",
    )
    audit(conn, user, "CONFIRM_ONLINE_ORDER", order["id"], {})
    from .online_workflow import issue_invoice
    issue_invoice(conn,user,record(conn,'online_orders',order['id']))


def money_entry(
    conn, user, order, amount, method, kind, sale_order_id=None, reference=""
):
    # COD collections are separate from a cashier shift until the collector hands over cash.
    conn.execute(
        "INSERT INTO payments(order_id,amount,method,kind,reference,user_id,online_order_id) VALUES(?,?,?,?,?,?,?)",
        (
            sale_order_id,
            amount,
            method,
            kind,
            order["code"] + (":" + reference if reference else ""),
            user["id"],
            order['id'],
        ),
    )


def release_allocation(conn, user, order, item, accepted, handling):
    left = accepted
    kept = []
    for batch_id, qty, cost in json.loads(item["allocations"]):
        keep = min(left, qty)
        left -= keep
        if keep:
            kept.append((batch_id, keep, cost))
        rejected = qty - keep
        if not rejected:
            continue
        b = record(conn, "stock_batches", batch_id)
        if handling == "RESTOCK":
            if item["storage_kind"] in {"FRESH", "FROZEN", "CHILLED"}:
                fail(
                    "Hàng tươi/lạnh bị từ chối cần cách ly kiểm tra, chưa trả thẳng vào hàng bán."
                )
            conn.execute(
                "UPDATE stock_batches SET remaining=remaining+? WHERE id=?",
                (rejected, batch_id),
            )
            stock.movement(
                conn,
                user,
                item["product_id"],
                batch_id,
                rejected,
                "ONLINE_RELEASE",
                order["id"],
            )
        elif handling == "QUARANTINE":
            new = stock.add_batch(
                conn,
                user,
                item["product_id"],
                rejected,
                cost,
                "CHECK-" + order["code"],
                b["expires_on"],
                "ONLINE_QUARANTINE",
                order["id"],
                "Hàng khách từ chối, chờ kiểm tra chất lượng",
            )
            conn.execute(
                "UPDATE stock_batches SET quality_status='HOLD',sell_until=? WHERE id=?",
                (b["sell_until"], new),
            )
        elif handling != "DAMAGE":
            fail("Chọn cách ly, trả kho hợp lệ hoặc loại bỏ cho hàng từ chối.")
        else:
            audit(
                conn,
                user,
                "ONLINE_REJECT_DAMAGE",
                item["id"],
                {"quantity": rejected, "batch_id": batch_id},
            )
    return kept


def deliver(conn, user, order, data):
    if order["status"] != "SHIPPING":
        fail("Chỉ kiểm nhận đơn đang giao.", 409)
    items = rows(
        conn,
        "SELECT * FROM online_items WHERE online_order_id=? ORDER BY id",
        (order["id"],),
    )
    submitted = objects(data.get("items"), "Kết quả kiểm nhận", maximum=50)
    lookup = {i.get("item_id"): i for i in submitted}
    if len(lookup) != len(submitted) or set(lookup) != {i["id"] for i in items}:
        fail("Cần ghi đủ, không lặp từng mặt hàng kiểm nhận.")
    prepared = []
    netgoods = 0
    keptpoints = 0
    reason = str(data.get("reason", "")).strip()[:500]
    for item in items:
        request = lookup[item["id"]]
        accepted = quantity(request.get("accepted"), allow_zero=True)
        if accepted > item["quantity"]:
            fail("Số nhận vượt số lượng đã giao.")
        if accepted < item["quantity"] and not reason:
            fail("Cần lý do từ chối/hoàn tiền khi kiểm hàng.")
        for bid, qty, cost in json.loads(item["allocations"]):
            batch = record(conn, "stock_batches", bid)
            if accepted and (
                (batch["expires_on"] and batch["expires_on"] < clock()[:10])
                or (batch["sell_until"] and batch["sell_until"] <= clock())
            ):
                fail("Lô đã qua hạn/giờ ngừng bán. Ghi nhận không nhận phần này.", 409)
        base = rounded(Decimal(item["total"]) * accepted / item["quantity"])
        points = min(item["points_part"] * accepted // item["quantity"], base // 100)
        net = base - points * 100
        netgoods += net
        keptpoints += points
        prepared.append(
            (item, accepted, request.get("handling", "QUARANTINE"), net, points)
        )
    fee = order["shipping_fee"] if any(a for _, a, _, _, _ in prepared) else 0
    due = money(netgoods + fee)
    if order["payment_method"] == "QR" and order["paid"] < due:
        fail("Cần nhân viên xác nhận đủ tiền QR trước khi hoàn tất.", 409)
    if order["payment_method"] == "COD" and money(data.get("collected")) != due:
        fail("Tiền COD thực thu phải đúng phần khách nhận cộng phí giao.", 409)
    account = record(conn, "shop_accounts", order["account_id"])
    code = "ON-" + order["code"]
    earned = netgoods // 10000
    gross = sum(i["price"] * a for i, a, _, _, _ in prepared)
    final_id = conn.execute(
        """INSERT INTO orders(order_code,created_by,total_amount,payment_method,apartment,customer_note,status,customer_id,cashier_id,gross_amount,discount,points_redeemed,points_earned,managed,idempotency_key,request_hash,fulfillment,shipping_fee,rescue_campaign_id,rescue_sets,rescue_name)
        VALUES(?,?,?,?,?,?,'COMPLETED',?,?,?,?,?,?,1,?,?,'DELIVERY',?,?,?,?)""",
        (
            code,
            user["name"],
            due,
            "TRANSFER" if order["payment_method"] == "QR" else "CASH",
            order["address"],
            order["note"],
            account["customer_id"],
            user["id"],
            gross,
            gross - netgoods - keptpoints * 100,
            keptpoints,
            earned,
            "online-final-" + str(order["id"]),
            order["request_hash"],
            fee,
            order["rescue_campaign_id"],
            order["rescue_sets"],
            record(conn, "rescue_campaigns", order["rescue_campaign_id"])["name"]
            if order["rescue_campaign_id"]
            else "",
        ),
    ).lastrowid
    conn.execute(
        "INSERT INTO order_events(order_id,status,user_id,note) VALUES(?,'COMPLETED',?,'Kiểm nhận online đã hoàn tất')",
        (final_id, user["id"]),
    )
    for item, accepted, handling, net, points in prepared:
        allocations = release_allocation(conn, user, order, item, accepted, handling)
        kept_by_batch = {bid: qty for bid, qty, cost in allocations}
        for bid, held, cost in json.loads(item["allocations"]):
            conn.execute(
                "UPDATE stock_movements SET quantity=?,kind='ONLINE_REJECTED' WHERE kind='ONLINE_HOLD' AND reference=? AND batch_id=? AND product_id=?",
                (
                    -(held - kept_by_batch.get(bid, 0)),
                    str(order["id"]),
                    bid,
                    item["product_id"],
                ),
            )
        if accepted:
            cost = sum(q * c for _, q, c in allocations) / accepted
            ident = conn.execute(
                """INSERT INTO order_items(order_id,product_id,product_name,shelf_location,quantity,price,subtotal,is_picked,cost_price,net_subtotal)
                VALUES(?,?,?,?,?,?,?,1,?,?)""",
                (
                    final_id,
                    item["product_id"],
                    item["product_name"],
                    "",
                    accepted,
                    item["price"],
                    item["price"] * accepted,
                    cost,
                    net,
                ),
            ).lastrowid
            conn.executemany(
                "INSERT INTO order_allocations(order_item_id,batch_id,quantity,cost_price) VALUES(?,?,?,?)",
                [(ident, b, q, c) for b, q, c in allocations],
            )
            if item["sale_id"]:
                conn.execute(
                    "UPDATE order_items SET timed_sale_id=? WHERE id=?",
                    (item["sale_id"], ident),
                )
            for bid, qty, cost in allocations:
                # Stock already left inventory on confirmation; convert only the accepted portion into sale history.
                conn.execute(
                    "INSERT INTO stock_movements(product_id,batch_id,quantity,kind,reference,user_id) VALUES(?,?,?,'SALE',?,?)",
                    (item["product_id"], bid, -qty, final_id, user["id"]),
                )
        conn.execute(
            "UPDATE online_items SET accepted=?,rejected_handling=? WHERE id=?",
            (accepted, handling, item["id"]),
        )
    if order["payment_method"] == "COD":
        money_entry(conn, user, order, due, "CASH", "ONLINE_COD", final_id)
    else:
        conn.execute(
            "UPDATE payments SET order_id=? WHERE kind='ONLINE_PREPAY' AND reference LIKE ?",
            (final_id, order["code"] + ":%"),
        )
    restored = order["points_used"] - keptpoints
    change_points(conn, order, restored, "Hoàn điểm cho hàng không nhận")
    change_points(conn, order, earned, "Tích điểm theo hàng thực nhận")
    refund = max(0, order["paid"] - due)
    conn.execute(
        "UPDATE online_orders SET status='COMPLETED',payment_status='VERIFIED',stock_reserved=0,sale_order_id=?,goods_total=?,shipping_fee=?,points_used=?,points_earned=?,paid=?,refund_due=?,updated_at=? WHERE id=?",
        (
            final_id,
            netgoods,
            fee,
            keptpoints,
            earned,
            due if order["payment_method"] == "COD" else order["paid"],
            refund,
            clock(),
            order["id"],
        ),
    )
    event(
        conn,
        order["id"],
        "COMPLETED",
        f"Đã kiểm nhận. Tiền hàng/phí thực tế {due}đ; cần hoàn {refund}đ. " + reason,
    )
    audit(
        conn,
        user,
        "DELIVER_ONLINE_ORDER",
        order["id"],
        {"total": due, "refund_due": refund, "reason": reason},
    )
    return {
        "success": True,
        "total": due,
        "refund_due": refund,
        "sale_order_id": final_id,
    }


def cancel(conn, user, order, reason):
    if order["status"] not in {"PENDING", "REVIEW", "PAYMENT_REVIEW", "CONFIRMED"}:
        fail("Đơn này không còn có thể hủy; liên hệ tiệm xử lý.", 409)
    if order['payment_flow']=='PREPAY' and order['stock_reserved']:
        from .online_workflow import release
        release(conn,order,user,'ONLINE_CANCEL')
    elif order["status"] == "CONFIRMED":
        for item in rows(
            conn, "SELECT * FROM online_items WHERE online_order_id=?", (order["id"],)
        ):
            # Holds have not left the shop; release back to their original batches, retaining all quality gates.
            for bid, qty, cost in json.loads(item["allocations"]):
                conn.execute(
                    "UPDATE stock_batches SET remaining=remaining+? WHERE id=?",
                    (qty, bid),
                )
                stock.movement(
                    conn,
                    user,
                    item["product_id"],
                    bid,
                    qty,
                    "ONLINE_CANCEL",
                    order["id"],
                )
    change_points(conn, order, order["points_used"], "Hoàn điểm đơn hủy")
    conn.execute(
        "UPDATE online_orders SET status='CANCELLED',stock_reserved=0,points_used=0,refund_due=paid,updated_at=? WHERE id=?",
        (clock(), order["id"]),
    )
    event(conn, order["id"], "CANCELLED", reason)
