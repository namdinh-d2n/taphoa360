"""Live updates, provincial demo branches, integer input and protected bank QR."""

import asyncio
from io import BytesIO
import unittest
import uuid
from unittest.mock import patch
from starlette.requests import Request
from PIL import Image
from retail.database import one, reading, transaction, migrate
from retail.errand_api import event_stream, live_revision
import config


class ErrandUpdateTests(unittest.TestCase):
    def setUp(self):
        from test_errands import ErrandTests

        self.e = ErrandTests("test_migration_is_additive_and_customer_pages_available")
        self.e.setUp()
        self.e.e.post(
            "/api/v1/shop/settings",
            {
                "store_name": "Test store",
                "bank_bin": "970422",
                "bank_account": "1234567890",
                "bank_name": "Bank Test",
            },
        )

    def tearDown(self):
        self.e.tearDown()

    def request_create(self, **extra):
        order = self.e.current()
        data = {
            k: order[k]
            for k in (
                "receiver",
                "phone",
                "address",
                "province_code",
                "branch_id",
                "delivery_window",
                "budget",
                "preferences",
            )
        }
        data["items"] = [
            {"name": "Thịt", "quantity": 1, "unit": "kg", "criteria": "Tươi"}
        ]
        response = self.e.customer.post(
            "/api/shop/errands",
            json={**data, **extra},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        return response

    def test_directory_has_one_or_more_demo_stores_per_province_and_no_inventory(self):
        from retail.locations import provinces

        result = self.e.customer.get("/api/shop/errands/directory").json()
        self.assertEqual(
            {p["code"] for p in result["provinces"]},
            {p["code"] for p in provinces()["provinces"]},
        )
        for province in result["provinces"]:
            self.assertTrue(
                any(b["province_code"] == province["code"] for b in result["branches"])
            )
        for code in [1, 79]:
            self.assertGreaterEqual(
                sum(b["province_code"] == code for b in result["branches"]), 2
            )
        with reading() as conn:
            before = one(conn, "SELECT COUNT(*) n FROM products")["n"]
        migrate()
        migrate()
        with reading() as conn:
            self.assertEqual(before, one(conn, "SELECT COUNT(*) n FROM products")["n"])

    def test_mismatched_province_or_inactive_branch_rejected(self):
        with reading() as conn:
            branch = one(
                conn, "SELECT * FROM errand_branches WHERE province_code=1 LIMIT 1"
            )
        self.assertEqual(
            self.request_create(province_code=79, branch_id=branch["id"]).status_code,
            400,
        )
        with transaction() as conn:
            conn.execute(
                "UPDATE errand_branches SET active=0 WHERE id=?", (branch["id"],)
            )
        self.assertEqual(
            self.request_create(province_code=1, branch_id=branch["id"]).status_code,
            400,
        )

    def test_customer_and_picker_reject_fractional_quantity_but_allow_integer_grams(
        self,
    ):
        self.assertEqual(
            self.request_create(
                items=[
                    {
                        "name": "Thịt",
                        "quantity": 1.001,
                        "unit": "kg",
                        "criteria": "Tươi",
                    }
                ]
            ).status_code,
            400,
        )
        self.e.prepared()
        item = self.e.order["items"][0]
        self.e.action(
            "select",
            {
                "item_id": item["id"],
                "selected_name": "Thịt nạc",
                "quantity": 1.001,
                "unit": "kg",
                "unit_price": 1,
                "source": "EXTERNAL",
                "vendor": "Shop",
                "quality": "Tươi",
            },
            400,
        )
        order = self.e.create(
            items=[{"name": "Thịt", "quantity": 500, "unit": "g", "criteria": "Tươi"}]
        )
        self.assertEqual(order["items"][0]["requested_qty"], 500)

    def test_qr_uses_approved_cap_not_unapproved_final_or_client_amount(self):
        e = self.e
        e.prepared()
        order = e.current()
        path = f"/api/shop/errands/{order['id']}/qr?version={order['version']}"
        with patch("retail.shop_api.qr_payload", return_value="TEST-QR") as payload:
            response = e.customer.get(path + "&amount=1")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(Image.open(BytesIO(response.content)).format, "PNG")
            self.assertEqual(payload.call_args.args[2], 300000)
        e.action("final", {"note": "Chờ duyệt tổng cuối"})
        with patch("retail.shop_api.qr_payload", return_value="TEST-QR") as payload:
            response = e.customer.get(
                f"/api/shop/errands/{order['id']}/qr?version={e.order['version']}"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload.call_args.args[2], 300000)
        e.action("approve-final", customer=True)
        e.money("RECEIVE", 100000)
        with patch("retail.shop_api.qr_payload", return_value="TEST-QR") as payload:
            self.assertEqual(
                e.customer.get(
                    f"/api/shop/errands/{order['id']}/qr?version={e.order['version']}"
                ).status_code,
                200,
            )
            self.assertEqual(payload.call_args.args[2], 195000)
        self.assertEqual(e.customer.get(path).status_code, 409)

    def test_qr_customer_scope_cash_paid_cancelled_and_not_approved(self):
        e = self.e
        o = e.current()

        def qr():
            return e.customer.get(
                f"/api/shop/errands/{o['id']}/qr?version={e.current()['version']}"
            )

        self.assertEqual(qr().status_code, 409)
        e.prepared()
        e.action("payment-method", {"method": "CASH"}, customer=True)
        self.assertEqual(qr().status_code, 409)
        e.action("payment-method", {"method": "TRANSFER"}, customer=True)
        e.final()
        e.money("RECEIVE", 295000)
        self.assertEqual(qr().status_code, 409)
        e.action("cancel", {"note": "Hủy trước mua"}, customer=True)
        self.assertEqual(qr().status_code, 409)
        e.e.register("0900000001")
        response = e.customer.get(
            f"/api/shop/errands/{o['id']}/qr?version={e.order['version']}"
        )
        self.assertEqual(response.status_code, 404)

    def test_live_revision_is_scoped_to_customer_and_assigned_staff(self):
        e = self.e
        me = e.customer.get("/api/shop/me").json()
        with reading() as conn:
            before = live_revision(conn, me, True)
        e.e.register("0900000001")
        e.order = e.create()
        with reading() as conn:
            self.assertEqual(before, live_revision(conn, me, True))
        with reading() as conn:
            base = live_revision(conn, {"id": 999, "role": "inventory"}, False)
        e.action("estimate", {"estimate": 300000, "note": "Changed"})
        with reading() as conn:
            self.assertEqual(
                base, live_revision(conn, {"id": 999, "role": "inventory"}, False)
            )

    def test_stream_emits_after_commit_and_revokes_expired_session(self):
        e = self.e
        cookie = e.customer.cookies.get("taphoa_shop")

        async def check():
            async def receive():
                await asyncio.sleep(0)
                return {"type": "http.request", "body": b"", "more_body": False}

            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/shop/errands/events",
                    "headers": [(b"cookie", ("taphoa_shop=" + cookie).encode())],
                    "server": ("testserver", 80),
                    "scheme": "http",
                    "query_string": b"",
                    "client": ("testclient", 123),
                },
                receive,
            )
            response = await event_stream(request, True)
            stream = response.body_iterator
            first = await anext(stream)
            self.assertIn("event: changed", first)
            await asyncio.to_thread(
                e.action, "estimate", {"estimate": 300000, "note": "Live test"}
            )
            changed = await asyncio.wait_for(anext(stream), 2)
            self.assertIn("event: changed", changed)
            self.assertNotEqual(first, changed)

            def expire():
                with transaction() as conn:
                    conn.execute("DELETE FROM shop_sessions")

            await asyncio.to_thread(expire)
            expired = await asyncio.wait_for(anext(stream), 2)
            self.assertIn("session-expired", expired)
            await stream.aclose()

        asyncio.run(check())

    def test_rollback_does_not_publish_change(self):
        from retail.live_events import subscribe

        async def check():
            with subscribe(config.SQLITE_PATH) as signal:

                def rollback():
                    try:
                        with transaction() as conn:
                            conn.execute("UPDATE errand_orders SET version=version+1")
                            raise ValueError("abort")
                    except ValueError:
                        pass

                await asyncio.to_thread(rollback)
                self.assertFalse(signal.is_set())

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
