"""Personal-shopping workflow tests on disposable SQLite, including money and permissions."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import uuid
import unittest
from PIL import Image
from retail.database import reading, transaction, one, rows, migrate, SCHEMA_VERSION
import config


class ErrandTests(unittest.TestCase):
    def setUp(self):
        from test_commerce import CommerceTests

        self.e = CommerceTests("test_vietqr_payload_round_trip_and_crc")
        self.e.setUp()
        self.staff = self.e.staff
        self.customer = self.e.client
        self.order = self.create()

    def tearDown(self):
        self.e.tearDown()

    def create(self, **extra):
        with reading() as conn:
            branch = one(
                conn,
                "SELECT id,province_code FROM errand_branches WHERE province_code=1 ORDER BY id LIMIT 1",
            )
        return self.e.post(
            "/api/shop/errands",
            {
                "receiver": "Khách thử",
                "phone": "0900000000",
                "address": "Địa chỉ thử",
                "province_code": branch["province_code"],
                "branch_id": branch["id"],
                "delivery_window": "Trước 11 giờ ngày mai",
                "budget": 300000,
                "preferences": "Phải hỏi trước khi thay; không tự mua nếu chưa xác nhận.",
                "items": [
                    {
                        "name": "Thịt nạc",
                        "quantity": 1,
                        "unit": "kg",
                        "criteria": "Tươi, ít mỡ, thái lát; bảo quản lạnh.",
                    }
                ],
                **extra,
            },
            client=self.customer,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )

    def current(self):
        result = self.customer.get("/api/shop/errands/" + str(self.order["id"]))
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def action(self, name, data=None, status=200, customer=False, key=None):
        order = self.current()
        result = self.e.post(
            ("/api/shop/errands/" if customer else "/api/v1/errands/")
            + str(order["id"])
            + "/"
            + name,
            {"version": order["version"], **(data or {})},
            status,
            client=self.customer if customer else self.staff,
            headers={"Idempotency-Key": key or uuid.uuid4().hex},
        )
        if status == 200:
            self.order = result
        return result

    def prepared(self, price=268000):
        self.action(
            "estimate",
            {
                "estimate": 300000,
                "note": "Tiền hàng dự kiến và các phí trong ngân sách.",
            },
        )
        self.action("approve-estimate", customer=True)
        self.action("assign", {"shopper_id": 1, "shipper_id": 1})
        item = self.current()["items"][0]
        self.action(
            "select",
            {
                "item_id": item["id"],
                "selected_name": "Thịt nạc",
                "quantity": 1,
                "unit": "kg",
                "unit_price": price,
                "source": "EXTERNAL",
                "vendor": "Quầy thịt chợ",
                "quality": "Tươi, không dập, ít mỡ, đã sơ chế, giữ lạnh.",
            },
        )

    def final(self):
        self.action(
            "final",
            {"note": "Đã kiểm tra lượng và chất lượng; vui lòng duyệt tổng cuối."},
        )
        self.action("approve-final", customer=True)

    def delivered(self):
        self.action(
            "purchase", {"note": "Hóa đơn QUAY-001, kiểm hàng và đóng gói giữ lạnh."}
        )
        self.action("ship")
        self.action(
            "deliver", {"note": "Biên nhận giao tận tay, khách đang kiểm hàng."}
        )

    def money(self, kind, amount, **extra):
        return self.action(
            "money",
            {
                "kind": kind,
                "amount": amount,
                "method": "TRANSFER",
                "reference": uuid.uuid4().hex,
                "recipient": "Khách thử / tài khoản xác nhận",
                "reason": "Đối soát thực tế",
                **extra,
            },
        )

    def photo(self):
        output = BytesIO()
        Image.new("RGB", (20, 20), "green").save(output, format="PNG")
        result = self.staff.post(
            "/api/errands/" + str(self.order["id"]) + "/photos?staff=1",
            files={"image": ("quality.png", output.getvalue(), "image/png")},
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["url"]

    def test_300k_deposit_295k_final_refund_5000_with_receipt_and_settlement(self):
        self.prepared()
        self.money("RECEIVE", 300000)
        self.final()
        self.assertEqual(self.order["total"], 295000)
        self.assertEqual(self.order["finance"]["refund_due"], 5000)
        self.delivered()
        self.action("settle", status=409)
        self.action("receive", customer=True)
        self.action("settle", status=409)
        self.money("REFUND", 5000)
        self.money("EXPENSE", 268000)
        self.action("settle")
        self.assertEqual(self.order["status"], "SETTLED")
        self.assertEqual(self.order["finance"]["net_received"], 295000)
        with reading() as conn:
            self.assertEqual(
                one(
                    conn,
                    "SELECT SUM(amount) n FROM payments WHERE kind IN ('ERRAND_RECEIVE','ERRAND_REFUND')",
                )["n"],
                295000,
            )
            self.assertEqual(
                one(
                    conn,
                    "SELECT SUM(amount) n FROM payments WHERE kind='ERRAND_EXPENSE'",
                )["n"],
                -268000,
            )

    def test_no_purchasing_shipping_or_collection_before_required_approval(self):
        self.action("purchase", {"note": "Too early"}, 409)
        self.action("ship", status=409)
        self.action(
            "money",
            {
                "kind": "RECEIVE",
                "amount": 1,
                "method": "TRANSFER",
                "reference": "early",
                "recipient": "a",
                "reason": "b",
            },
            409,
        )
        self.prepared()
        self.action("final", {"note": "Khách cần duyệt"})
        self.action("purchase", {"note": "Still too early"}, 409)
        self.action(
            "money",
            {
                "kind": "RECEIVE",
                "amount": 300001,
                "method": "TRANSFER",
                "reference": "over",
                "recipient": "a",
                "reason": "b",
            },
            409,
        )
        self.action("approve-final", customer=True)
        self.delivered()
        self.action(
            "money",
            {
                "kind": "RECEIVE",
                "amount": 295001,
                "method": "TRANSFER",
                "reference": "extra",
                "recipient": "a",
                "reason": "b",
            },
            409,
        )

    def test_substitution_notifies_customer_and_needs_explicit_decision(self):
        self.prepared()
        item = self.order["items"][0]
        change = {
            "item_id": item["id"],
            "selected_name": "Thịt vai",
            "quantity": 2,
            "unit": "kg",
            "unit_price": 121500,
            "source": "EXTERNAL",
            "vendor": "Quầy mới",
            "quality": "Tươi; giữ lạnh",
            "reason": "Hết nạc theo yêu cầu",
        }
        self.action("select", change, 409)
        self.action("propose", change, 400)
        self.action("propose", {**change, "photo": self.photo()})
        self.assertEqual(self.order["status"], "CHANGE_REVIEW")
        self.assertTrue(
            any("Cần khách duyệt" in event["message"] for event in self.order["events"])
        )
        self.action("final", {"note": "Không được bỏ qua duyệt"}, 409)
        self.action(
            "decide-item", {"item_id": item["id"], "decision": "APPROVE"}, customer=True
        )
        self.assertEqual(self.order["items"][0]["selected_name"], "Thịt vai")
        self.final()
        self.assertEqual(self.order["total"], 270000)

    def test_unavailable_can_be_skipped_or_rejected_by_customer(self):
        second = self.create(
            items=[
                {"name": "Rau", "quantity": 1, "unit": "bó", "criteria": "Tươi"},
                {"name": "Thịt nạc", "quantity": 1, "unit": "kg", "criteria": "Tươi"},
            ]
        )
        self.order = second
        self.action("estimate", {"estimate": 300000, "note": "Dự kiến"})
        self.action("approve-estimate", customer=True)
        self.action("assign", {"shopper_id": 1, "shipper_id": 1})
        item = self.order["items"][0]
        self.action(
            "unavailable", {"item_id": item["id"], "reason": "Rau héo, không đạt"}
        )
        self.action(
            "decide-item", {"item_id": item["id"], "decision": "REJECT"}, customer=True
        )
        self.assertEqual(self.order["items"][0]["decision"], "REJECTED")
        self.action(
            "unavailable", {"item_id": item["id"], "reason": "Chưa có nguồn đạt"}
        )
        self.action(
            "decide-item", {"item_id": item["id"], "decision": "SKIP"}, customer=True
        )
        self.assertTrue(self.order["items"][0]["skipped"])

    def test_stale_approval_and_expired_reviews_do_not_authorize_purchase(self):
        self.prepared()
        self.action("final", {"note": "Bản chốt"})
        stale = self.order["version"]
        self.action("final", {"note": "Gửi lại bản mới"})
        self.e.post(
            "/api/shop/errands/" + str(self.order["id"]) + "/approve-final",
            {"version": stale},
            409,
            client=self.customer,
        )
        with transaction() as conn:
            conn.execute(
                "UPDATE errand_orders SET review_deadline='2000-01-01T00:00:00' WHERE id=?",
                (self.order["id"],),
            )
        self.action("approve-final", customer=True, status=409)
        self.action("purchase", {"note": "Không được"}, 409)

    def test_over_budget_requires_final_approval_and_revision_unlocks_selection(self):
        self.prepared(price=400000)
        self.action("final", {"note": "Vượt ngân sách, chờ khách"})
        self.assertEqual(self.order["total"], 427000)
        self.action(
            "revise", {"note": "Giảm giá / chọn lại trước khi mua"}, customer=True
        )
        self.assertEqual(self.order["status"], "SHOPPING")
        self.assertEqual(self.order["total"], 0)
        self.action("purchase", {"note": "Không"}, 409)

    def test_deposit_cancel_requires_actual_refund_and_cannot_cancel_after_purchase(
        self,
    ):
        self.prepared()
        self.money("RECEIVE", 300000)
        self.action("cancel", {"note": "Không mua nữa"}, customer=True)
        self.assertEqual(self.order["finance"]["refund_due"], 300000)
        self.action("settle", status=409)
        self.money("REFUND", 300000)
        self.action("settle")
        self.assertEqual(self.order["finance"]["net_received"], 0)
        self.order = self.create()
        self.prepared()
        self.final()
        self.delivered()
        self.action("cancel", {"note": "Đã mua"}, 409, customer=True)

    def test_financial_retries_are_idempotent_and_conflicting_reference_rejected(self):
        self.prepared()
        order = self.current()
        key = uuid.uuid4().hex
        body = {
            "version": order["version"],
            "kind": "RECEIVE",
            "amount": 300000,
            "method": "TRANSFER",
            "reference": "BANK-UNIQUE",
            "recipient": "Khách",
            "reason": "Đã đối chiếu ngân hàng",
        }
        path = "/api/v1/errands/" + str(order["id"]) + "/money"
        self.e.post(path, body, headers={"Idempotency-Key": key})
        self.e.post(path, body, headers={"Idempotency-Key": key})
        self.e.post(path, {**body, "amount": 1}, 409, headers={"Idempotency-Key": key})
        self.action("money", {**body, "version": self.current()["version"]}, 409)
        with reading() as conn:
            self.assertEqual(len(rows(conn, "SELECT * FROM errand_money")), 1)

    def test_cash_transactions_require_open_shift_and_affect_expected_cash(self):
        self.prepared()
        data = {
            "kind": "RECEIVE",
            "amount": 300000,
            "method": "CASH",
            "reference": "CASH-1",
            "recipient": "Khách",
            "reason": "Biên nhận tiền",
        }
        self.action("money", data, 409)
        shift = self.e.post("/api/v1/cash-shifts", {"opening_cash": 0})["id"]
        self.action("money", data)
        self.final()
        self.money("REFUND", 5000, method="CASH")
        result = self.e.post(
            f"/api/v1/cash-shifts/{shift}/close", {"counted_cash": 295000}
        )
        self.assertEqual(result["expected"], 295000)

    def test_complaint_after_receipt_creates_payable_refund_not_fake_paid_refund(self):
        self.prepared()
        self.final()
        self.money("RECEIVE", 295000)
        self.delivered()
        self.action("receive", customer=True)
        self.action(
            "complaints",
            {
                "item_id": self.order["items"][0]["id"],
                "reason": "Thịt không tươi như yêu cầu",
                "photo": self.photo(),
            },
            customer=True,
        )
        complaint = self.order["complaints"][0]
        self.action("settle", status=409)
        self.action(
            "resolve",
            {
                "complaint_id": complaint["id"],
                "resolution": "REFUND",
                "credit": 280000,
                "reply": "Quá tiền món",
            },
            409,
        )
        self.action(
            "resolve",
            {
                "complaint_id": complaint["id"],
                "resolution": "REFUND",
                "credit": 20000,
                "reply": "Đã xác minh, nhận trả phần lỗi; tách hàng để kiểm tra.",
            },
        )
        self.assertEqual(self.order["finance"]["refund_due"], 20000)
        self.assertEqual(self.order["finance"]["refunded"], 0)
        self.money("REFUND", 20000)
        self.money("EXPENSE", 268000)
        self.action("settle")
        self.assertEqual(self.order["finance"]["net_received"], 275000)

    def test_photo_access_is_private_and_invalid_files_rejected(self):
        url = self.photo()
        self.assertEqual(self.customer.get(url).status_code, 200)
        self.e.register("0900000001")
        self.assertEqual(self.customer.get(url).status_code, 404)
        bad = self.staff.post(
            f"/api/errands/{self.order['id']}/photos?staff=1",
            files={"image": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.staff.get(url + "?staff=1").status_code, 200)

    def test_separate_customer_and_staff_scope_and_csrf(self):
        ident = self.order["id"]
        self.e.register("0900000001")
        self.assertEqual(
            self.customer.get("/api/shop/errands/" + str(ident)).status_code, 404
        )
        self.e.post(
            "/api/shop/errands/" + str(ident) + "/approve-estimate",
            {"version": 1},
            404,
            client=self.customer,
        )
        self.assertEqual(self.customer.get("/api/v1/errands").status_code, 401)
        self.e.post(
            "/api/v1/users",
            {
                "username": "warehouse",
                "name": "Kho",
                "role": "inventory",
                "password": "commerce-password-123",
            },
        )
        result = self.e.post(
            "/api/login", {"username": "warehouse", "password": "commerce-password-123"}
        )
        self.staff.headers["X-CSRF-Token"] = result["csrf"]
        self.assertEqual(self.staff.get("/api/v1/errands").json()["orders"], [])
        self.e.post(
            "/api/v1/errands/" + str(ident) + "/estimate",
            {"version": 1, "estimate": 1, "note": "No"},
            403,
        )
        self.e.post(
            "/api/v1/errands/settings",
            {"service_fee": 0, "complaint_hours": 24, "policy": "No"},
            403,
        )

    def test_purchase_replay_and_shortage_do_not_double_decrement_store_stock(self):
        self.order = self.create(
            items=[
                {
                    "name": "Sữa tươi",
                    "quantity": 2,
                    "unit": "hộp",
                    "criteria": "Hộp nguyên, hạn xa",
                }
            ]
        )
        self.action("estimate", {"estimate": 67000, "note": "Gồm phí"})
        self.action("approve-estimate", customer=True)
        self.action("assign", {"shopper_id": 1, "shipper_id": 1})
        item = self.order["items"][0]
        self.action(
            "select",
            {
                "item_id": item["id"],
                "selected_name": "Sữa tươi",
                "quantity": 2,
                "unit": "hộp",
                "unit_price": 20000,
                "source": "STORE",
                "product_id": self.e.p,
                "vendor": "Tiệm",
                "quality": "Nguyên hộp; lạnh; hạn đủ",
            },
        )
        self.final()
        self.action("purchase", {"note": "Xuất kho theo FEFO"})
        self.action("purchase", {"note": "Gửi lại"}, 409)
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT stock FROM products WHERE id=?", (self.e.p,))[
                    "stock"
                ],
                8,
            )
            self.assertEqual(
                one(conn, "SELECT SUM(quantity) n FROM errand_allocations")["n"], 2
            )

    def test_migration_is_additive_and_customer_pages_available(self):
        with reading() as conn:
            before = rows(conn, "SELECT * FROM products")
        migrate()
        migrate()
        with reading() as conn:
            self.assertEqual(rows(conn, "SELECT * FROM products"), before)
            self.assertEqual(rows(conn, "PRAGMA foreign_key_check"), [])
            self.assertEqual(
                one(conn, "SELECT MAX(version) n FROM schema_migrations")["n"],
                SCHEMA_VERSION,
            )
        self.assertTrue(
            list((Path(config.SQLITE_PATH).parent / "backups").glob("before-v12-*.db"))
        )
        self.assertEqual(self.customer.get("/shop/errands").status_code, 200)
        self.assertIn("Đi chợ hộ", self.customer.get("/shop").text)
        self.assertEqual(self.staff.get("/errands").status_code, 200)

    def test_concurrent_purchase_is_atomic(self):
        self.prepared()
        self.final()
        order = self.current()
        body = {"version": order["version"], "note": "Hóa đơn chỉ ghi nhận một lần"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(
                pool.map(
                    lambda _: self.staff.post(
                        "/api/v1/errands/" + str(order["id"]) + "/purchase", json=body
                    ).status_code,
                    range(2),
                )
            )
        self.assertEqual(sorted(statuses), [200, 409])

    def test_warehouse_can_select_only_assigned_orders_and_cannot_handle_money(self):
        self.e.post(
            "/api/v1/users",
            {
                "username": "shopper",
                "name": "Đi chợ",
                "role": "inventory",
                "password": "commerce-password-123",
            },
        )
        with reading() as conn:
            shopper = one(conn, "SELECT id FROM users WHERE username='shopper'")["id"]
        self.prepared()
        self.action("assign", {"shopper_id": shopper, "shipper_id": 1})
        login = self.e.post(
            "/api/login", {"username": "shopper", "password": "commerce-password-123"}
        )
        self.staff.headers["X-CSRF-Token"] = login["csrf"]
        self.assertEqual(len(self.staff.get("/api/v1/errands").json()["orders"]), 1)
        self.action("money", {"kind": "RECEIVE", "amount": 300000}, 403)
        self.action("final", {"note": "Không có quyền đối soát"}, 403)

    def test_reopen_complaint_after_settlement_and_reject_with_reason(self):
        self.prepared()
        self.final()
        self.money("RECEIVE", 295000)
        self.delivered()
        self.action("receive", customer=True)
        self.money("EXPENSE", 268000)
        self.action("settle")
        self.action(
            "complaints",
            {
                "item_id": self.order["items"][0]["id"],
                "reason": "Phản hồi sau nhận hàng",
            },
            customer=True,
        )
        self.assertEqual(self.order["status"], "DELIVERED")
        complaint = self.order["complaints"][0]
        self.action(
            "resolve",
            {
                "complaint_id": complaint["id"],
                "resolution": "REJECT",
                "credit": 0,
                "reply": "Đã kiểm tra ảnh và biên nhận; giải thích rõ với khách.",
            },
        )
        self.assertEqual(self.order["complaints"][0]["status"], "REJECTED")
        self.action("settle")

    def test_expired_complaint_policy_and_client_payment_claim_do_not_book_money(self):
        self.prepared()
        self.action("report-payment", {"note": "Khách báo chuyển"}, customer=True)
        self.assertEqual(self.order["finance"]["received"], 0)
        self.final()
        self.delivered()
        with transaction() as conn:
            conn.execute(
                "UPDATE errand_orders SET delivered_at='2000-01-01T00:00:00' WHERE id=?",
                (self.order["id"],),
            )
        self.action(
            "complaints",
            {"item_id": self.order["items"][0]["id"], "reason": "Quá hạn"},
            409,
            customer=True,
        )

    def test_amount_validation_request_replay_and_private_photo_cross_order(self):
        self.action("estimate", {"estimate": -1, "note": "Invalid"}, 400)
        self.prepared()
        self.action(
            "select",
            {
                "item_id": self.order["items"][0]["id"],
                "selected_name": "Thịt nạc",
                "quantity": "NaN",
                "unit": "kg",
                "unit_price": 100,
                "source": "EXTERNAL",
                "vendor": "Chợ",
                "quality": "Tươi",
            },
            400,
        )
        url = self.photo()
        other = self.create()
        self.assertEqual(
            self.customer.get(
                url.replace(
                    str(self.order["id"]) + "/photos", str(other["id"]) + "/photos"
                )
            ).status_code,
            404,
        )
        data = {
            "version": self.current()["version"],
            "estimate": 300000,
            "note": "Stale",
        }
        self.e.post(
            "/api/shop/errands/" + str(other["id"]) + "/approve-estimate",
            data,
            409,
            client=self.customer,
        )

    def test_pre_purchase_change_requires_new_customer_approval(self):
        self.prepared()
        self.final()
        self.action(
            "revise-approved",
            {"note": "Nguồn hàng thay đổi trước khi mua; gửi lại khách"},
        )
        self.assertEqual(self.order["status"], "SHOPPING")
        self.assertEqual(self.order["total"], 0)
        self.action("purchase", {"note": "Không được dùng bản chốt cũ"}, 409)
        self.final()
        self.action("purchase", {"note": "Mua sau khách duyệt lại"})


if __name__ == "__main__":
    unittest.main()
