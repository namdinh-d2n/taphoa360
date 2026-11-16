# Personal shopping domain. All writes run inside the caller's transaction.
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
import secrets
from .common import fail, required, money, number, objects, record, now, audit, rounded
from .database import one, rows
from .inventory import take_stock, payment

EDITABLE = {"ESTIMATE_APPROVED", "SHOPPING", "CHANGE_REVIEW"}
TERMINAL = {"CANCELLED", "SETTLED"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        fail("Thiếu mã chống trùng. Hãy tải lại và thử lại.")
    return value


def event(conn, order, actor, message):
    current = record(conn, "errand_orders", order["id"])
    conn.execute(
        "INSERT INTO errand_events(order_id,actor,message,snapshot,created_at) VALUES(?,?,?,?,?)",
        (
            order["id"],
            actor,
            message,
            encode(
                {
                    "status": current["status"],
                    "version": current["version"],
                    "total": current["total"],
                    "estimate": current["estimate"],
                    "items": rows(
                        conn,
                        "SELECT * FROM errand_items WHERE order_id=?",
                        (order["id"],),
                    ),
                }
            ),
            now(),
        ),
    )


def update(conn, order, **values):
    values.update(version=order["version"] + 1, updated_at=now())
    conn.execute(
        "UPDATE errand_orders SET "
        + ",".join(name + "=?" for name in values)
        + " WHERE id=?",
        (*values.values(), order["id"]),
    )


def check_version(order, data):
    if type(data.get("version")) is not int or data["version"] != order["version"]:
        fail("Đơn đã thay đổi. Hãy tải lại trước khi xác nhận.", 409)


def scope(order, user, customer=False):
    if customer:
        if order["account_id"] != user["id"]:
            fail("Không tìm thấy đơn đi chợ hộ.", 404)
    elif user["role"] in {"owner", "cashier"}:
        return
    elif (user["role"] == "inventory" and order["shopper_id"] == user["id"]) or (
        user["role"] == "shipper" and order["shipper_id"] == user["id"]
    ):
        return
    else:
        fail("Đơn chưa được phân công cho bạn.", 403)


def require_role(user, *roles):
    if user["role"] not in {"owner", *roles}:
        fail("Bạn không có quyền thực hiện thao tác này.", 403)


def worker(conn, ident, role):
    account = record(conn, "users", ident)
    if not account["active"] or account["role"] not in {role, "owner"}:
        fail("Chọn nhân viên đang hoạt động đúng vai trò.")
    return account["id"]


def finances(conn, order):
    totals = {
        r["kind"]: r["amount"]
        for r in rows(
            conn,
            "SELECT kind,SUM(amount) amount FROM errand_money WHERE order_id=? GROUP BY kind",
            (order["id"],),
        )
    }
    net = totals.get("RECEIVE", 0) - totals.get("REFUND", 0)
    due = (
        0
        if order["status"] == "CANCELLED"
        else (order["total"] - order["credit"] if order["total"] else order["estimate"])
    )
    external = one(
        conn,
        "SELECT COALESCE(SUM(subtotal),0) n FROM errand_items WHERE order_id=? AND source='EXTERNAL' AND skipped=0",
        (order["id"],),
    )["n"]
    return {
        "received": totals.get("RECEIVE", 0),
        "refunded": totals.get("REFUND", 0),
        "expenses": totals.get("EXPENSE", 0),
        "net_received": net,
        "due": due,
        "collect_due": max(0, due - net),
        "refund_due": max(0, net - due),
        "external_goods": external,
        "expense_due": max(0, external - totals.get("EXPENSE", 0)),
    }


def payment_details(conn, order):
    approved_final = order["status"] in {
        "APPROVED",
        "PURCHASED",
        "SHIPPING",
        "DELIVERED",
    }
    approved_estimate = order["status"] in {
        "ESTIMATE_APPROVED",
        "SHOPPING",
        "CHANGE_REVIEW",
        "FINAL_REVIEW",
    }
    cap = (
        order["total"]
        if approved_final
        else order["estimate"]
        if approved_estimate
        else 0
    )
    net = finances(conn, order)["net_received"]
    amount = max(0, cap - order["credit"] - net)
    bank = one(
        conn, "SELECT bank_bin,bank_account,bank_name FROM shop_settings WHERE id=1"
    )
    return {
        "amount": amount,
        "reference": order["code"],
        "method": order.get("payment_method", "TRANSFER"),
        "bank": bank,
        "qr_ready": bool(amount and bank["bank_bin"] and bank["bank_account"]),
    }


def detail(conn, order):
    result = dict(order)
    result["items"] = rows(
        conn, "SELECT * FROM errand_items WHERE order_id=? ORDER BY id", (order["id"],)
    )
    for item in result["items"]:
        item["proposal"] = json.loads(item["proposal"]) if item["proposal"] else None
    result["events"] = rows(
        conn,
        "SELECT id,actor,message,created_at FROM errand_events WHERE order_id=? ORDER BY id",
        (order["id"],),
    )
    result["ledger"] = rows(
        conn,
        "SELECT id,kind,amount,method,reference,recipient,reason,created_at FROM errand_money WHERE order_id=? ORDER BY id",
        (order["id"],),
    )
    result["complaints"] = rows(
        conn,
        "SELECT * FROM errand_complaints WHERE order_id=? ORDER BY id",
        (order["id"],),
    )
    result["finance"] = finances(conn, order)
    result["payment"] = payment_details(conn, order)
    result.pop("request_hash", None)
    result.pop("request_key", None)
    return result


def photo(conn, order, value):
    if not value:
        return ""
    if not isinstance(value, str) or not re.fullmatch(
        r"/api/errands/[0-9]+/photos/[a-f0-9]{32}\.jpg", value
    ):
        fail("Ảnh phải được tải lên trong đơn này.")
    if not one(
        conn,
        "SELECT name FROM errand_photos WHERE name=? AND order_id=?",
        (value.rsplit("/", 1)[1], order["id"]),
    ):
        fail("Ảnh không thuộc đơn này.")
    return value


def create(conn, user, data, request_key):
    request_key = key(request_key)
    old = one(conn, "SELECT * FROM errand_orders WHERE request_key=?", (request_key,))
    if old:
        if old["account_id"] != user["id"] or old["request_hash"] != digest(data):
            fail("Mã yêu cầu đã được dùng cho nội dung khác.", 409)
        return detail(conn, old)
    branch = record(conn, "errand_branches", data.get("branch_id"))
    province_code = number(
        data.get("province_code"), "Tỉnh/thành", minimum=1, integer=True
    )
    if not branch["active"] or branch["province_code"] != province_code:
        fail("Cửa hàng không thuộc tỉnh/thành đã chọn hoặc đã ngừng nhận đơn.")
    if branch["zone_id"]:
        zone = record(conn, "delivery_zones", branch["zone_id"])
        if not zone["active"]:
            fail("Cửa hàng chưa phục vụ giao hàng.")
    else:
        # Demo service points do not create or expand the ordinary shop's zones.
        zone = one(
            conn, "SELECT * FROM delivery_zones WHERE active=1 ORDER BY id LIMIT 1"
        )
        if not zone:
            zone_id = conn.execute(
                "INSERT INTO delivery_zones(name,fee,eta) VALUES('Đi chợ hộ',0,'Giờ giao theo xác nhận')"
            ).lastrowid
            zone = record(conn, "delivery_zones", zone_id)
    method = data.get("payment_method", "TRANSFER")
    if method not in {"TRANSFER", "CASH"}:
        fail("Chọn chuyển khoản hoặc tiền mặt khi nhận hàng.")
    settings = record(conn, "errand_settings", 1)
    budget = money(data.get("budget"))
    if budget < settings["service_fee"] + branch["fee"]:
        fail("Ngân sách phải bao gồm phí mua hộ và phí giao.")
    preferences = required(
        data, "preferences", "Yêu cầu chung và cách xử lí thiếu hàng", 1000
    )
    items = objects(data.get("items"), "Danh sách đi chợ", maximum=50)
    ident = conn.execute(
        """INSERT INTO errand_orders(code,account_id,request_key,request_hash,receiver,phone,address,zone_id,delivery_window,budget,preferences,service_fee,shipping_fee,complaint_hours,policy,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "DCH-" + secrets.token_hex(5).upper(),
            user["id"],
            request_key,
            digest(data),
            required(data, "receiver", "Người nhận", 100),
            required(data, "phone", "Điện thoại", 30),
            required(data, "address", "Địa chỉ", 500),
            zone["id"],
            required(data, "delivery_window", "Khung giờ giao", 100),
            budget,
            preferences,
            settings["service_fee"],
            branch["fee"],
            settings["complaint_hours"],
            settings["policy"],
            now(),
            now(),
        ),
    ).lastrowid
    conn.execute(
        """UPDATE errand_orders SET province_code=?,province_name=?,branch_id=?,branch_name=?,payment_method=? WHERE id=?""",
        (
            branch["province_code"],
            branch["province_name"],
            branch["id"],
            branch["name"],
            method,
            ident,
        ),
    )
    for item in items:
        qty = number(
            item.get("quantity"), "Số lượng phải là số nguyên", minimum=1, integer=True
        )
        conn.execute(
            "INSERT INTO errand_items(order_id,requested_name,requested_qty,requested_unit,criteria) VALUES(?,?,?,?,?)",
            (
                ident,
                required(item, "name", "Tên món", 150),
                qty,
                required(item, "unit", "Đơn vị", 30),
                required(item, "criteria", "Tiêu chí chất lượng / sơ chế", 500),
            ),
        )
    order = record(conn, "errand_orders", ident)
    event(
        conn,
        order,
        "Khách hàng",
        "Đã gửi danh sách đi chợ; chưa phát sinh thu tiền. Cần khách duyệt mọi thay thế và bản chốt cuối.",
    )
    return detail(conn, order)


def selection(conn, order, data):
    source = data.get("source")
    if source not in {"STORE", "EXTERNAL"}:
        fail("Chọn hàng của tiệm hoặc mua ngoài.")
    qty = number(
        data.get("quantity"),
        "Lượng thực chọn phải là số nguyên",
        minimum=1,
        integer=True,
    )
    price = money(data.get("unit_price"))
    subtotal = money(rounded(Decimal(str(qty)) * price))
    product_id = None
    if source == "STORE":
        product = record(conn, "products", data.get("product_id"))
        if not product["active"] or qty != int(qty):
            fail(
                "Hàng trong kho dùng đơn vị nguyên theo danh mục; hàng cân lẻ chọn nguồn mua ngoài."
            )
        product_id = product["id"]
        if (
            data.get("selected_name") != product["product_name"]
            or data.get("unit") != product["unit"]
        ):
            fail("Tên và đơn vị hàng của tiệm phải khớp danh mục.")
    return {
        "selected_name": required(data, "selected_name", "Tên hàng thực chọn", 150),
        "quantity": qty,
        "unit": required(data, "unit", "Đơn vị thực chọn", 30),
        "unit_price": price,
        "subtotal": subtotal,
        "source": source,
        "product_id": product_id,
        "vendor": required(data, "vendor", "Nguồn mua / nhà bán", 150),
        "quality": required(data, "quality", "Kết quả kiểm chất lượng", 1000),
        "photo": photo(conn, order, data.get("photo")),
        "skipped": 0,
    }


def apply_selection(conn, item, chosen):
    conn.execute(
        "UPDATE errand_items SET "
        + ",".join(k + "=?" for k in chosen)
        + ",proposal=NULL,decision='APPROVED' WHERE id=?",
        (*chosen.values(), item["id"]),
    )


def is_waiting(order):
    return order["status"] in {"ESTIMATE_REVIEW", "CHANGE_REVIEW", "FINAL_REVIEW"}


def staff_action(conn, user, order, action, data):
    scope(order, user)
    check_version(order, data)
    status = order["status"]
    actor = user["name"]
    if action == "estimate":
        require_role(user, "cashier")
        if status not in {"REQUESTED", "ESTIMATE_REVIEW"}:
            fail("Chỉ báo giá trước khi khách duyệt.", 409)
        estimate = money(data.get("estimate"))
        if estimate < order["service_fee"] + order["shipping_fee"]:
            fail("Tiền dự kiến phải bao gồm các khoản phí.")
        update(
            conn,
            order,
            estimate=estimate,
            status="ESTIMATE_REVIEW",
            review_deadline=(datetime.now() + timedelta(hours=2)).isoformat(
                timespec="seconds"
            ),
        )
        message = (
            "Mời khách duyệt giá dự kiến "
            + str(estimate)
            + "đ, đã bao gồm phí. "
            + required(data, "note", "Ghi chú báo giá", 500)
        )
    elif action == "assign":
        require_role(user, "cashier")
        if status in TERMINAL or status in {"SHIPPING", "DELIVERED"}:
            fail("Không thể phân công ở trạng thái này.", 409)
        update(
            conn,
            order,
            shopper_id=worker(conn, data.get("shopper_id"), "inventory"),
            shipper_id=worker(conn, data.get("shipper_id"), "shipper"),
        )
        message = "Đã phân công nhân viên đi chợ và giao hàng."
    elif action in {"select", "propose"}:
        require_role(user, "inventory")
        if status not in EDITABLE or not order["shopper_id"]:
            fail("Cần khách duyệt dự kiến và phân công trước khi chọn hàng.", 409)
        item = record(conn, "errand_items", data.get("item_id"))
        if item["order_id"] != order["id"]:
            fail("Món không thuộc đơn.", 404)
        chosen = selection(conn, order, data)
        changed = (
            chosen["selected_name"] != item["requested_name"]
            or chosen["quantity"] != item["requested_qty"]
            or chosen["unit"] != item["requested_unit"]
        )
        if action == "select" and changed:
            fail("Đổi tên, lượng hoặc đơn vị cần gửi phương án cho khách duyệt.", 409)
        if action == "propose":
            reason = required(data, "reason", "Lý do thiếu hàng / thay thế", 500)
            if not chosen["photo"]:
                fail("Cần ảnh hàng thay thế để khách đối chiếu.")
            conn.execute(
                "UPDATE errand_items SET proposal=?,decision='PENDING' WHERE id=?",
                (encode(chosen), item["id"]),
            )
            update(
                conn,
                order,
                status="CHANGE_REVIEW",
                review_deadline=(datetime.now() + timedelta(hours=2)).isoformat(
                    timespec="seconds"
                ),
            )
            message = (
                "Cần khách duyệt thay thế "
                + item["requested_name"]
                + ": "
                + reason
                + "; giá món mới "
                + str(chosen["subtotal"])
                + "đ."
            )
        else:
            apply_selection(conn, item, chosen)
            update(
                conn, order, status="SHOPPING" if status != "CHANGE_REVIEW" else status
            )
            message = "Đã kiểm chất lượng và chọn " + chosen["selected_name"] + "."
    elif action == "unavailable":
        require_role(user, "inventory")
        if status not in EDITABLE:
            fail("Đơn chưa ở bước chọn hàng.", 409)
        item = record(conn, "errand_items", data.get("item_id"))
        if item["order_id"] != order["id"]:
            fail("Món không thuộc đơn.", 404)
        conn.execute(
            "UPDATE errand_items SET proposal=?,decision='PENDING' WHERE id=?",
            (encode({"unavailable": True}), item["id"]),
        )
        update(
            conn,
            order,
            status="CHANGE_REVIEW",
            review_deadline=(datetime.now() + timedelta(hours=2)).isoformat(
                timespec="seconds"
            ),
        )
        message = (
            "Hết hàng / không đạt chất lượng: "
            + item["requested_name"]
            + ". "
            + required(data, "reason", "Lý do", 500)
            + " Khách chọn bỏ món hoặc yêu cầu chọn lại."
        )
    elif action == "final":
        require_role(user, "cashier")
        if status not in EDITABLE | {"FINAL_REVIEW"}:
            fail("Đơn chưa sẵn sàng gửi bản chốt.", 409)
        items = rows(
            conn, "SELECT * FROM errand_items WHERE order_id=?", (order["id"],)
        )
        if any(
            i["decision"] == "PENDING"
            or (not i["skipped"] and (not i["selected_name"] or not i["quality"]))
            for i in items
        ):
            fail(
                "Cần chọn/kiểm chất lượng đủ món và xử lí các phương án đang chờ.", 409
            )
        if all(i["skipped"] for i in items):
            fail("Không còn hàng; hãy hủy đơn và hoàn tiền.", 409)
        total = money(
            sum(i["subtotal"] for i in items if not i["skipped"])
            + order["service_fee"]
            + order["shipping_fee"]
        )
        update(
            conn,
            order,
            total=total,
            status="FINAL_REVIEW",
            review_deadline=(datetime.now() + timedelta(hours=2)).isoformat(
                timespec="seconds"
            ),
        )
        message = (
            "Mời khách kiểm tra từng món và duyệt tổng cuối "
            + str(total)
            + "đ trước khi mua. "
            + ("Tổng vượt ngân sách ban đầu. " if total > order["budget"] else "")
            + required(data, "note", "Ghi chú bản chốt", 500)
        )
    elif action == "revise-approved":
        require_role(user, "cashier")
        if status != "APPROVED":
            fail("Chỉ mở lại bản đã duyệt khi chưa mua/xuất hàng.", 409)
        update(conn, order, status="SHOPPING", total=0)
        message = (
            "Bản chốt cần điều chỉnh trước khi mua; phải gửi khách duyệt lại. "
            + required(data, "note", "Lý do thay đổi", 500)
        )
    elif action == "purchase":
        require_role(user, "inventory")
        if status != "APPROVED":
            fail("Chỉ mua/xuất hàng sau khi khách duyệt bản chốt.", 409)
        receipt = required(
            data, "note", "Mã hóa đơn / biên nhận và kết quả kiểm hàng", 500
        )
        for item in rows(
            conn,
            "SELECT * FROM errand_items WHERE order_id=? AND skipped=0",
            (order["id"],),
        ):
            if item["source"] == "STORE":
                for batch, qty, cost in take_stock(
                    conn,
                    user,
                    item["product_id"],
                    item["quantity"],
                    "ERRAND_SALE",
                    order["code"],
                ):
                    conn.execute(
                        "INSERT INTO errand_allocations(item_id,batch_id,quantity,cost_price) VALUES(?,?,?,?)",
                        (item["id"], batch, qty, cost),
                    )
        update(conn, order, status="PURCHASED")
        message = (
            "Đã mua/xuất hàng đúng bản chốt; kiểm tra và đóng gói. Chứng từ: " + receipt
        )
    elif action == "ship":
        require_role(user, "cashier")
        if status != "PURCHASED" or not order["shipper_id"]:
            fail("Cần mua hàng và phân công giao trước.", 409)
        update(conn, order, status="SHIPPING")
        message = "Đã bàn giao hàng, đang giao; chỉ thu đúng khoản khách đã duyệt."
    elif action == "deliver":
        require_role(user, "shipper")
        if status != "SHIPPING":
            fail("Đơn chưa được giao đi.", 409)
        update(conn, order, status="DELIVERED", delivered_at=now())
        message = (
            "Nhân viên báo đã giao. "
            + required(data, "note", "Biên nhận / tình trạng giao", 500)
            + " Mời khách kiểm nhận."
        )
    elif action == "settle":
        require_role(user, "cashier")
        balance = finances(conn, order)
        if status not in {"DELIVERED", "CANCELLED"} or (
            status == "DELIVERED" and not order["received"]
        ):
            fail("Cần khách xác nhận kiểm nhận trước khi quyết toán.", 409)
        if one(
            conn,
            "SELECT id FROM errand_complaints WHERE order_id=? AND status IN ('OPEN','REVIEW')",
            (order["id"],),
        ):
            fail("Còn khiếu nại đang xử lí.", 409)
        if balance["collect_due"] or balance["refund_due"]:
            fail("Còn tiền phải thu/hoàn; cần chứng từ giao dịch thực tế.", 409)
        if status == "DELIVERED" and balance["expense_due"]:
            fail("Cần ghi nhận chi phí mua ngoài trước khi quyết toán.", 409)
        update(conn, order, status="SETTLED" if status == "DELIVERED" else "CANCELLED")
        message = "Đã đối soát và quyết toán chi phí; thu/hoàn có chứng từ."
    elif action == "cancel":
        require_role(user, "cashier")
        if status not in {
            "REQUESTED",
            "ESTIMATE_REVIEW",
            "ESTIMATE_APPROVED",
            "SHOPPING",
            "CHANGE_REVIEW",
            "FINAL_REVIEW",
            "APPROVED",
        }:
            fail("Đã mua hàng; cần xử lí qua kiểm nhận/khiếu nại.", 409)
        update(conn, order, status="CANCELLED", total=0, estimate=0)
        message = "Đã hủy; hoàn toàn bộ số đã nhận. " + required(
            data, "reason", "Lý do hủy", 500
        )
    else:
        fail("Thao tác không hợp lệ.", 404)
    event(conn, order, actor, message)
    audit(
        conn,
        user,
        "ERRAND_" + action.upper(),
        order["id"],
        {"version": order["version"]},
    )


def customer_action(conn, user, order, action, data):
    scope(order, user, True)
    check_version(order, data)
    status = order["status"]
    if action == "payment-method":
        if status in TERMINAL or data.get("method") not in {"CASH", "TRANSFER"}:
            fail("Không thể đổi phương thức thanh toán ở trạng thái này.", 409)
        update(conn, order, payment_method=data["method"])
        event(
            conn,
            order,
            "Khách hàng",
            "Khách chọn "
            + (
                "chuyển khoản qua QR."
                if data["method"] == "TRANSFER"
                else "tiền mặt khi nhận hàng."
            ),
        )
        return
    if action in {"approve-estimate", "approve-final", "decide-item"}:
        if (
            not is_waiting(order)
            or not order["review_deadline"]
            or order["review_deadline"] < now()
        ):
            fail(
                "Phương án hết hạn; yêu cầu cửa hàng gửi lại. Không tự coi là đã đồng ý.",
                409,
            )
    if action == "approve-estimate" and status == "ESTIMATE_REVIEW":
        update(conn, order, status="ESTIMATE_APPROVED")
        message = "Khách đã duyệt giá dự kiến và các khoản phí."
    elif action == "decide-item" and status == "CHANGE_REVIEW":
        item = record(conn, "errand_items", data.get("item_id"))
        if item["order_id"] != order["id"] or item["decision"] != "PENDING":
            fail("Phương án không còn chờ duyệt.", 409)
        decision = data.get("decision")
        proposed = json.loads(item["proposal"])
        if decision == "APPROVE" and not proposed.get("unavailable"):
            apply_selection(conn, item, proposed)
            message = "Khách đồng ý phương án thay thế " + item["requested_name"] + "."
        elif decision == "SKIP":
            conn.execute(
                "UPDATE errand_items SET skipped=1,subtotal=0,proposal=NULL,decision='SKIPPED' WHERE id=?",
                (item["id"],),
            )
            message = "Khách chọn bỏ món " + item["requested_name"] + "."
        elif decision == "REJECT":
            conn.execute(
                "UPDATE errand_items SET selected_name='',subtotal=0,quality='',proposal=NULL,decision='REJECTED' WHERE id=?",
                (item["id"],),
            )
            message = "Khách yêu cầu chọn lại " + item["requested_name"] + "."
        else:
            fail("Lựa chọn không hợp lệ.")
        pending = one(
            conn,
            "SELECT id FROM errand_items WHERE order_id=? AND decision='PENDING'",
            (order["id"],),
        )
        update(conn, order, status="CHANGE_REVIEW" if pending else "SHOPPING")
    elif action == "approve-final" and status == "FINAL_REVIEW":
        update(conn, order, status="APPROVED")
        message = (
            "Khách đã duyệt toàn bộ hàng, trọng lượng, chất lượng và tổng cuối "
            + str(order["total"])
            + "đ; không thu phụ phí ngoài bản này."
        )
    elif action == "revise" and status in {"ESTIMATE_REVIEW", "FINAL_REVIEW"}:
        update(
            conn,
            order,
            status="REQUESTED" if status == "ESTIMATE_REVIEW" else "SHOPPING",
            total=0,
        )
        message = "Khách yêu cầu chỉnh trước khi duyệt: " + required(
            data, "note", "Nội dung cần chỉnh", 500
        )
    elif action == "receive" and status == "DELIVERED":
        if order["received"]:
            fail("Bạn đã xác nhận kiểm nhận.", 409)
        update(conn, order, received=1)
        message = (
            "Khách đã kiểm nhận. Có thể phản hồi/khiếu nại theo chính sách của đơn."
        )
    elif action == "cancel" and status in {
        "REQUESTED",
        "ESTIMATE_REVIEW",
        "ESTIMATE_APPROVED",
        "SHOPPING",
        "CHANGE_REVIEW",
        "FINAL_REVIEW",
        "APPROVED",
    }:
        update(conn, order, status="CANCELLED", total=0, estimate=0)
        message = "Khách hủy trước khi mua; hoàn toàn bộ tiền đã nhận. " + required(
            data, "note", "Lý do hủy", 500
        )
    elif action == "report-payment" and status not in TERMINAL:
        update(conn, order)
        message = (
            "Khách báo đã chuyển tiền; chờ thu ngân đối chiếu (chưa ghi thu). "
            + required(data, "note", "Mã chuyển khoản / nội dung đối chiếu", 200)
        )
    else:
        fail("Thao tác không phù hợp trạng thái hiện tại.", 409)
    event(conn, order, "Khách hàng", message)


def book_money(conn, user, order, data, request_key):
    require_role(user, "cashier")
    request_key = key(request_key)
    old = one(conn, "SELECT * FROM errand_money WHERE request_key=?", (request_key,))
    if old:
        if old["order_id"] != order["id"] or old["request_hash"] != digest(data):
            fail("Mã giao dịch bị dùng lại với dữ liệu khác.", 409)
        return
    check_version(order, data)
    kind = data.get("kind")
    amount = money(data.get("amount"))
    if not amount:
        fail("Số tiền phải lớn hơn 0.")
    balance = finances(conn, order)
    if kind == "RECEIVE":
        if order["status"] not in {
            "ESTIMATE_APPROVED",
            "SHOPPING",
            "CHANGE_REVIEW",
            "FINAL_REVIEW",
            "APPROVED",
            "PURCHASED",
            "SHIPPING",
            "DELIVERED",
        }:
            fail("Khách chưa duyệt khoản thu.", 409)
        cap = (
            order["total"]
            if order["status"] in {"APPROVED", "PURCHASED", "SHIPPING", "DELIVERED"}
            else order["estimate"]
        )
        if amount > max(0, cap - order["credit"] - balance["net_received"]):
            fail("Khoản thu vượt số khách đã duyệt.", 409)
        sign = 1
    elif kind == "REFUND":
        if (
            order["status"]
            not in {
                "APPROVED",
                "PURCHASED",
                "SHIPPING",
                "DELIVERED",
                "SETTLED",
                "CANCELLED",
            }
            or amount > balance["refund_due"]
        ):
            fail("Khoản hoàn vượt tiền dư / khoản hoàn được duyệt.", 409)
        sign = -1
    elif kind == "EXPENSE":
        if (
            order["status"] not in {"PURCHASED", "SHIPPING", "DELIVERED", "SETTLED"}
            or amount > balance["expense_due"]
        ):
            fail("Chi mua ngoài vượt chứng từ hàng đã mua.", 409)
        sign = -1
    else:
        fail("Loại giao dịch không hợp lệ.")
    method = data.get("method")
    if method not in {"CASH", "TRANSFER"}:
        fail("Chọn tiền mặt hoặc chuyển khoản.")
    reference = required(data, "reference", "Mã giao dịch / biên nhận thực tế", 100)
    if one(conn, "SELECT id FROM errand_money WHERE reference=?", (reference,)):
        fail("Mã giao dịch đã ghi nhận.", 409)
    recipient = required(data, "recipient", "Người/tài khoản nhận hoặc nộp tiền", 200)
    reason = required(data, "reason", "Nội dung đối soát", 500)
    payment(
        conn,
        user,
        sign * amount,
        method,
        "ERRAND_" + kind,
        order["code"] + ":" + reference,
    )
    payment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO errand_money(order_id,kind,amount,method,reference,recipient,reason,user_id,payment_id,request_key,request_hash,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            order["id"],
            kind,
            amount,
            method,
            reference,
            recipient,
            reason,
            user["id"],
            payment_id,
            request_key,
            digest(data),
            now(),
        ),
    )
    update(conn, order)
    event(
        conn,
        order,
        user["name"],
        {
            "RECEIVE": "Đã xác nhận thu",
            "REFUND": "Đã hoàn thực tế",
            "EXPENSE": "Đã chi mua ngoài",
        }[kind]
        + " "
        + str(amount)
        + "đ; "
        + reference
        + "; "
        + recipient
        + ".",
    )


def complain(conn, user, order, data):
    scope(order, user, True)
    check_version(order, data)
    if order["status"] not in {"DELIVERED", "SETTLED"} or not order["delivered_at"]:
        fail("Chỉ phản hồi sau khi nhận/giao hàng.", 409)
    if datetime.now() > datetime.fromisoformat(order["delivered_at"]) + timedelta(
        hours=order["complaint_hours"]
    ):
        fail(
            "Đã quá thời hạn khiếu nại của đơn; vui lòng liên hệ trực tiếp cửa hàng.",
            409,
        )
    item = record(conn, "errand_items", data.get("item_id"))
    if item["order_id"] != order["id"] or item["skipped"]:
        fail("Món không thuộc hàng đã nhận.", 404)
    if one(
        conn,
        "SELECT id FROM errand_complaints WHERE item_id=? AND status IN ('OPEN','REVIEW')",
        (item["id"],),
    ):
        fail("Món này đã có phản hồi đang xử lí.", 409)
    if datetime.now() > datetime.fromisoformat(order["delivered_at"]) + timedelta(
        hours=order["complaint_hours"]
    ):
        fail(
            "Đã qua thời hạn phản hồi của đơn. Liên hệ cửa hàng để được hỗ trợ trực tiếp.",
            409,
        )
    conn.execute(
        "INSERT INTO errand_complaints(order_id,item_id,reason,photo,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (
            order["id"],
            item["id"],
            required(data, "reason", "Vấn đề chất lượng / thiếu hàng", 1000),
            photo(conn, order, data.get("photo")),
            now(),
            now(),
        ),
    )
    update(conn, order, status="DELIVERED")
    event(
        conn,
        order,
        "Khách hàng",
        "Có khiếu nại mới về " + item["selected_name"] + ". Cửa hàng đang tiếp nhận.",
    )


def resolve_complaint(conn, user, order, data):
    require_role(user, "cashier")
    check_version(order, data)
    complaint = record(conn, "errand_complaints", data.get("complaint_id"))
    if complaint["order_id"] != order["id"] or complaint["status"] not in {
        "OPEN",
        "REVIEW",
    }:
        fail("Khiếu nại không còn chờ xử lí.", 409)
    resolution = data.get("resolution")
    if resolution not in {"REFUND", "REPLACE", "REJECT"}:
        fail("Chọn hoàn tiền, đổi hàng hoặc từ chối có lý do.")
    credit = money(data.get("credit", 0))
    if (resolution == "REFUND" and not credit) or (resolution != "REFUND" and credit):
        fail("Số tiền điều chỉnh không phù hợp phương án.")
    item = record(conn, "errand_items", complaint["item_id"])
    previous = one(
        conn,
        "SELECT COALESCE(SUM(credit),0) n FROM errand_complaints WHERE item_id=?",
        (item["id"],),
    )["n"]
    if (
        credit + previous > item["subtotal"]
        or order["credit"] + credit > order["total"]
    ):
        fail("Hoàn khiếu nại vượt tiền hàng được nhận.", 409)
    reply = required(
        data, "reply", "Kết quả xác minh, cách đổi/nhận trả và lý do", 1000
    )
    conn.execute(
        "UPDATE errand_complaints SET status=?,resolution=?,credit=?,reply=?,handler_id=?,updated_at=? WHERE id=?",
        (
            "REJECTED" if resolution == "REJECT" else "RESOLVED",
            resolution,
            credit,
            reply,
            user["id"],
            now(),
            complaint["id"],
        ),
    )
    update(conn, order, credit=order["credit"] + credit)
    event(
        conn,
        order,
        user["name"],
        "Đã xử lí phản hồi: "
        + reply
        + (
            "; khoản giảm/hoàn được duyệt "
            + str(credit)
            + "đ, chờ giao dịch hoàn thực tế."
            if credit
            else ""
        ),
    )
    audit(
        conn,
        user,
        "ERRAND_COMPLAINT_RESOLVED",
        complaint["id"],
        {"credit": credit, "resolution": resolution},
    )


def report_summary(conn, start, end):
    delivered = rows(
        conn,
        "SELECT * FROM errand_orders WHERE date(delivered_at) BETWEEN ? AND ?",
        (start, end),
    )
    received = one(
        conn,
        "SELECT COALESCE(SUM(amount),0) amount FROM errand_money WHERE kind='RECEIVE' AND date(created_at) BETWEEN ? AND ?",
        (start, end),
    )["amount"]
    refunded = one(
        conn,
        "SELECT COALESCE(SUM(amount),0) amount FROM errand_money WHERE kind='REFUND' AND date(created_at) BETWEEN ? AND ?",
        (start, end),
    )["amount"]
    expenses = one(
        conn,
        "SELECT COALESCE(SUM(amount),0) amount FROM errand_money WHERE kind='EXPENSE' AND date(created_at) BETWEEN ? AND ?",
        (start, end),
    )["amount"]
    outstanding = [
        finances(conn, o)
        for o in rows(
            conn,
            "SELECT * FROM errand_orders WHERE status IN ('DELIVERED','CANCELLED')",
        )
    ]
    return {
        "delivered_count": len(delivered),
        "delivered_value": sum(o["total"] - o["credit"] for o in delivered),
        "received": received,
        "refunded": refunded,
        "expenses": expenses,
        "collect_due": sum(f["collect_due"] for f in outstanding),
        "refund_due": sum(f["refund_due"] for f in outstanding),
    }
