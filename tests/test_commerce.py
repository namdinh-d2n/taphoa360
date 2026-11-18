"""Real checkout/fulfilment against an isolated store; no bank or network calls."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import hashlib, json, tempfile, unittest, uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
import config, db
from app import app
from retail import commerce as shop
from retail.database import reading, transaction, one, rows, migrate, SCHEMA_VERSION
from retail.shop_api import qr_payload


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="th360-commerce-")
        self.previous = config.SQLITE_PATH, db.SQLITE_PATH, config.SEED_DEMO
        config.SQLITE_PATH = db.SQLITE_PATH = str(Path(self.folder.name) / "shop.db")
        config.SEED_DEMO = False
        self.staff = TestClient(app)
        self.staff.__enter__()
        self.post(
            "/api/setup",
            {"username": "owner", "name": "Owner", "password": "commerce-password-123"},
        )
        login = self.post(
            "/api/login", {"username": "owner", "password": "commerce-password-123"}
        )
        self.staff.headers["X-CSRF-Token"] = login["csrf"]
        self.supplier = self.post("/api/v1/suppliers", {"name": "Supplier"})["id"]
        self.p = self.product("Sữa tươi", 20000, 12000, 10, "CHILLED", "Bữa sáng")
        self.bread = self.product("Bánh mì", 10000, 5000, 10, "DRY", "Bữa sáng")
        self.post(
            "/api/v1/shop/zones",
            {"name": "Chung cư A", "fee": 12000, "eta": "Sau xác nhận"},
        )
        with reading() as conn:
            self.zone = one(conn, "SELECT id FROM delivery_zones")["id"]
        self.client = TestClient(app)
        self.register()

    def tearDown(self):
        self.client.close()
        self.staff.__exit__(None, None, None)
        config.SQLITE_PATH, db.SQLITE_PATH, config.SEED_DEMO = self.previous
        self.folder.cleanup()

    def post(self, path, data, status=200, client=None, **kwargs):
        r = (client or self.staff).post(path, json=data, **kwargs)
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def register(self, phone="0900000000"):
        data = {
            "phone": phone,
            "name": "Customer",
            "password": "customer-password-123",
            "confirm_password": "customer-password-123",
        }
        self.post("/api/shop/register", data, client=self.client)
        self.post("/api/shop/login", data, client=self.client)
        result = self.client.get("/api/shop/me").json()
        self.client.headers["X-CSRF-Token"] = result["csrf"]
        return result

    def product(self, name, price, cost, count, storage="DRY", category="Thiết yếu"):
        p = self.post(
            "/api/v1/products",
            {
                "product_name": name,
                "price": price,
                "unit": "hộp",
                "zone_code": "A1",
                "storage_kind": storage,
                "category": category,
            },
        )["id"]
        self.post(
            "/api/v1/purchases",
            {
                "supplier_id": self.supplier,
                "paid": 0,
                "items": [
                    {
                        "product_id": p,
                        "quantity": count,
                        "cost_price": cost,
                        "expires_on": (
                            datetime.fromisoformat(shop.clock()) + timedelta(days=5)
                        )
                        .date()
                        .isoformat(),
                    }
                ],
            },
        )
        return p

    def payload(self, **extra):
        return {
            "items": [
                {"product_id": self.p, "quantity": 2},
                {"product_id": self.bread, "quantity": 2},
            ],
            "zone_id": self.zone,
            "receiver": "Customer",
            "phone": "0900000000",
            "address": "Test private address",
            "payment_method": "COD",
            "substitution": "CALL",
            **extra,
        }

    def place(self, data=None, key=None):
        data = data or self.payload()
        q = self.post("/api/shop/quote", data, client=self.client)
        return self.post(
            "/api/shop/orders",
            {**data, "fingerprint": q["fingerprint"]},
            client=self.client,
            headers={"Idempotency-Key": key or uuid.uuid4().hex},
        )

    def action(self, order, action, data=None, status=200):
        return self.post(
            f"/api/v1/shop/orders/{order['id']}/{action}", data or {}, status
        )

    def confirm_ship(self, order, qr=False):
        if qr:
            self.post('/api/shop/orders/'+str(order['id'])+'/report-payment',{},client=self.client)
            self.action(
                order,
                "paid",
                {"amount": 72000, "reference": "BANK-" + uuid.uuid4().hex},
            )
            with reading() as conn:items=rows(conn,'SELECT id FROM online_items WHERE online_order_id=?',(order['id'],))
            self.action(order,'prepare',{'items':[{'item_id':i['id'],'picked':True} for i in items]})
        else:self.action(order,'confirm')
        shipper = self.post(
            "/api/v1/users",
            {
                "username": "s" + uuid.uuid4().hex[:8],
                "name": "Shipper",
                "role": "shipper",
                "password": "commerce-password-123",
            },
        )["id"]
        self.action(order, "ship", {"shipper_id": shipper})

    def inspect(self, order, accepted=2, handling="QUARANTINE", collected=72000):
        with reading() as conn:
            items = rows(
                conn,
                "SELECT id,product_id FROM online_items WHERE online_order_id=?",
                (order["id"],),
            )
        return {
            "items": [
                {
                    "item_id": i["id"],
                    "accepted": accepted if i["product_id"] == self.p else 2,
                    "handling": handling,
                }
                for i in items
            ],
            "reason": "Kiểm hàng khi nhận",
            "collected": collected,
        }

    def test_public_catalog_redacts_cost_and_shows_storage_and_budget(self):
        r = TestClient(app).get("/api/shop/catalog")
        self.assertEqual(r.status_code, 200)
        p = next(p for p in r.json()["products"] if p["id"] == self.p)
        self.assertEqual(p["storage_kind"], "CHILLED")
        self.assertNotIn("cost_price", p)
        self.assertNotIn("supplier_sku", p)
        r = self.client.get("/api/shop/budget?amount=50000&kind=breakfast").json()
        self.assertLessEqual(r["total"], 50000)
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(TestClient(app).get("/shop").status_code, 200)

    def test_customer_auth_cannot_access_staff_and_staff_cannot_checkout_as_customer(
        self,
    ):
        self.assertEqual(self.client.get("/api/v1/products").status_code, 401)
        self.post("/api/shop/quote", self.payload(), 401, client=self.staff)
        self.post(
            "/api/shop/quote",
            self.payload(),
            403,
            client=self.client,
            headers={"X-CSRF-Token": ""},
        )
        self.post(
            "/api/shop/register",
            {
                "phone": "0900000001",
                "name": "X",
                "password": "123",
                "confirm_password": "123",
            },
            400,
            client=self.client,
        )

    def test_pending_and_idempotent_checkout_no_stock_or_payment_until_confirm(self):
        key = uuid.uuid4().hex
        data = self.payload()
        quote = self.post("/api/shop/quote", data, client=self.client)
        payload = {**data, "fingerprint": quote["fingerprint"]}
        a = self.post(
            "/api/shop/orders",
            payload,
            client=self.client,
            headers={"Idempotency-Key": key},
        )
        b = self.post(
            "/api/shop/orders",
            payload,
            client=self.client,
            headers={"Idempotency-Key": key},
        )
        self.assertEqual(a["id"], b["id"])
        self.assertTrue(b["replayed"])
        self.assertEqual(a["token"], b["token"])
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT stock FROM products WHERE id=?", (self.p,))["stock"],
                10,
            )
            self.assertEqual(one(conn, "SELECT COUNT(*) n FROM payments")["n"], 0)
        self.action(a, "confirm")
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT stock FROM products WHERE id=?", (self.p,))["stock"],
                8,
            )

    def test_stale_price_or_stock_is_detected_at_checkout(self):
        data = self.payload()
        q = self.post("/api/shop/quote", data, client=self.client)
        self.post("/api/v1/products/" + str(self.p), {"price": 23000}, 405)
        with transaction() as conn:
            conn.execute("UPDATE products SET price=23000 WHERE id=?", (self.p,))
        self.post(
            "/api/shop/orders",
            {**data, "fingerprint": q["fingerprint"]},
            409,
            client=self.client,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )

    def test_cod_partial_refusal_only_collects_actual_received_and_awards_points(self):
        order = self.place()
        self.confirm_ship(order)
        result = self.action(
            order, "deliver", self.inspect(order, accepted=1, collected=52000)
        )
        self.assertEqual(result["total"], 52000)
        self.assertEqual(result["refund_due"], 0)
        with reading() as conn:
            o = one(conn, "SELECT * FROM online_orders WHERE id=?", (order["id"],))
            self.assertEqual(o["points_earned"], 4)
            self.assertEqual(
                one(
                    conn,
                    "SELECT SUM(remaining) n FROM stock_batches WHERE product_id=? AND quality_status='HOLD'",
                    (self.p,),
                )["n"],
                1,
            )
            self.assertEqual(
                one(conn, "SELECT SUM(amount) n FROM payments WHERE kind='ONLINE_COD'")[
                    "n"
                ],
                52000,
            )
            report = one(
                conn,
                "SELECT total_amount,shipping_fee FROM orders WHERE id=?",
                (result["sale_order_id"],),
            )
            self.assertEqual(
                (report["total_amount"], report["shipping_fee"]), (52000, 12000)
            )
            self.assertEqual(
                one(
                    conn,
                    "SELECT SUM(quantity) n FROM stock_movements WHERE product_id=?",
                    (self.p,),
                )["n"],
                9,
            )

    def test_qr_partial_refusal_creates_refund_due_then_confirms_real_refund(self):
        self.post(
            "/api/v1/shop/settings",
            {
                "store_name": "Test shop",
                "bank_bin": "970436",
                "bank_account": "123456789",
                "bank_name": "TEST",
            },
        )
        order = self.place(self.payload(payment_method="QR"))
        self.confirm_ship(order, True)
        qr = self.client.get("/api/shop/orders/" + str(order["id"]) + "/qr")
        self.assertEqual(qr.status_code, 409)
        self.assertIn('không cần chuyển thêm',qr.json()['detail'])
        result = self.action(order, "deliver", self.inspect(order, accepted=1))
        self.assertEqual(result["refund_due"], 20000)
        self.action(
            order,
            "refund",
            {"amount": 20000, "method": "TRANSFER", "reference": "REFUND-REAL-01"},
        )
        self.action(
            order,
            "refund",
            {"amount": 20000, "method": "TRANSFER", "reference": "REFUND-REAL-01"},
            409,
        )
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT SUM(amount) n FROM payments")["n"], 52000
            )

    def test_full_refusal_waives_shipping_and_restores_points(self):
        with transaction() as conn:
            conn.execute("UPDATE customers SET points=100")
        order = self.place(self.payload(points_used=10))
        self.confirm_ship(order)
        request = self.inspect(order, accepted=0, collected=0)
        for item in request["items"]:
            item["accepted"] = 0
        self.action(order, "deliver", request)
        me = self.client.get("/api/shop/me").json()
        self.assertEqual(me["points"], 100)
        with reading() as conn:
            o = one(conn, "SELECT * FROM online_orders WHERE id=?", (order["id"],))
            self.assertEqual(o["shipping_fee"], 0)
            self.assertEqual(o["points_earned"], 0)

    def test_points_held_then_released_on_expiry_and_cancel(self):
        with transaction() as conn:
            conn.execute("UPDATE customers SET points=100")
        order = self.place(self.payload(points_used=20))
        self.assertEqual(self.client.get("/api/shop/me").json()["points"], 80)
        with transaction() as conn:
            conn.execute(
                "UPDATE online_orders SET expires_at='2000-01-01T00:00:00' WHERE id=?",
                (order["id"],),
            )
        self.client.get("/api/shop/orders")
        self.assertEqual(self.client.get("/api/shop/me").json()["points"], 100)
        another = self.place(self.payload(points_used=30))
        self.action(another, "confirm")
        self.action(another, "cancel", {"reason": "Cancel held order"})
        self.assertEqual(self.client.get("/api/shop/me").json()["points"], 100)
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT stock FROM products WHERE id=?", (self.p,))["stock"],
                10,
            )

    def test_customer_must_approve_substitution_before_staff_confirmation(self):
        order = self.place()
        self.action(
            order,
            "propose",
            {
                "items": [{"product_id": self.bread, "quantity": 3}],
                "reason": "Sữa hết hàng, khách xem lại",
            },
        )
        self.action(order, "confirm", status=409)
        self.post(
            "/api/shop/orders/" + str(order["id"]) + "/approve",
            {"version": 1},
            409,
            client=self.client,
        )
        self.post(
            "/api/shop/orders/" + str(order["id"]) + "/approve",
            {"version": 2},
            client=self.client,
        )
        self.action(order, "confirm")
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT stock FROM products WHERE id=?", (self.p,))["stock"],
                10,
            )

    def test_tracking_is_private_unguessable_and_account_scoped(self):
        order = self.place()
        anon = TestClient(app)
        result = anon.get("/api/shop/track/" + order["token"]).json()
        for field in [
            "address",
            "receiver",
            "phone",
            "account_id",
            "note",
            "token_hash",
        ]:
            self.assertNotIn(field, result)
        self.assertEqual(anon.get("/api/shop/track/" + "0" * 64).status_code, 404)
        self.register("0900000001")
        self.post(
            "/api/shop/orders/" + str(order["id"]) + "/approve",
            {"version": 1},
            404,
            client=self.client,
        )
        self.assertEqual(
            self.client.get("/api/shop/orders/" + str(order["id"]) + "/qr").status_code,
            404,
        )

    def test_perishable_cutoff_and_quarantine_block_pos_and_public_stock(self):
        with reading() as conn:
            b = one(conn, "SELECT * FROM stock_batches WHERE product_id=?", (self.p,))
        past = (datetime.fromisoformat(shop.clock()) - timedelta(minutes=1)).isoformat()
        self.post(
            "/api/v1/shop/batches/" + str(b["id"]) + "/quality",
            {
                "quality_status": "HOLD",
                "sell_until": past,
                "reason": "End of day check",
            },
        )
        p = next(
            p
            for p in self.client.get("/api/shop/catalog").json()["products"]
            if p["id"] == self.p
        )
        self.assertEqual(p["stock"], 0)
        self.post(
            "/api/v1/orders",
            {
                "items": [{"product_id": self.p, "quantity": 1}],
                "payment_method": "TRANSFER",
            },
            409,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        self.post(
            "/api/v1/shop/batches/" + str(b["id"]) + "/quality",
            {
                "quality_status": "SELLABLE",
                "sell_until": None,
                "reason": "Do not extend",
            },
            400,
        )

    def test_timed_sale_boundary_cap_shared_by_online_and_pos(self):
        at = datetime.fromisoformat(shop.clock())
        self.post(
            "/api/v1/shop/sales",
            {
                "name": "Golden hour",
                "product_id": self.p,
                "price": 15000,
                "max_units": 3,
                "starts_at": (at - timedelta(minutes=2)).isoformat(),
                "ends_at": (at + timedelta(minutes=30)).isoformat(),
            },
        )
        order = self.place(self.payload(items=[{"product_id": self.p, "quantity": 2}]))
        self.action(order, "confirm")
        self.post(
            "/api/v1/orders",
            {
                "items": [{"product_id": self.p, "quantity": 2}],
                "payment_method": "TRANSFER",
            },
            409,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        sale = self.post(
            "/api/v1/orders",
            {
                "items": [{"product_id": self.p, "quantity": 1}],
                "payment_method": "TRANSFER",
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        self.assertEqual(sale["total_amount"], 15000)
        p = next(
            p
            for p in self.client.get("/api/shop/catalog").json()["products"]
            if p["id"] == self.p
        )
        self.assertIsNone(p["sale"])
        with patch(
            "retail.commerce.clock", return_value=(at + timedelta(hours=1)).isoformat()
        ):
            with reading() as conn:
                self.assertEqual(
                    shop.effective_price(
                        conn, one(conn, "SELECT * FROM products WHERE id=?", (self.p,))
                    )[0],
                    20000,
                )

    def test_confirmation_is_atomic_against_pos_inventory(self):
        data = self.payload(items=[{"product_id": self.p, "quantity": 8}])
        order = self.place(data)

        def confirm(_):
            return self.staff.post(
                f"/api/v1/shop/orders/{order['id']}/confirm", json={}
            ).status_code

        def pos(_):
            return self.staff.post(
                "/api/v1/orders",
                json={
                    "items": [{"product_id": self.p, "quantity": 8}],
                    "payment_method": "TRANSFER",
                },
                headers={"Idempotency-Key": uuid.uuid4().hex},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda f: f(0), [confirm, pos]))
        self.assertEqual(sorted(results), [200, 409])
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT stock FROM products WHERE id=?", (self.p,))["stock"],
                2,
            )

    def test_media_and_settings_require_staff_not_customer(self):
        self.assertEqual(self.client.get("/api/v1/shop/overview").status_code, 401)
        self.post(
            "/api/v1/shop/settings", {"store_name": "Attack"}, 401, client=self.client
        )
        self.post("/api/v1/shop/banners", {"title": "Test promo", "theme": "ORANGE"})
        banner = self.client.get("/api/shop/catalog").json()["banners"][0]
        self.assertEqual(banner["title"], "Test promo")
        self.post(
            "/api/v1/shop/banners",
            {"title": "Invalid path", "image_path": "https://tracker.example/pixel"},
            400,
        )

    def test_vietqr_payload_round_trip_and_crc(self):
        payload = qr_payload("970436", "123456789", 72000, "WEB-TEST")
        self.assertTrue(payload.startswith("000201010212"))
        self.assertIn("A000000727", payload)
        self.assertIn("QRIBFTTA", payload)
        self.assertIn("540572000", payload)
        crc = 0xFFFF
        for byte in payload[:-4].encode():
            crc ^= byte << 8
            for _ in range(8):
                crc = (
                    ((crc << 1) ^ 0x1021) & 0xFFFF
                    if crc & 0x8000
                    else (crc << 1) & 0xFFFF
                )
        self.assertEqual(payload[-4:], f"{crc:04X}")

    def test_owner_order_shows_qr_immediately_after_order_and_accepts_png(self):
        self.post('/api/v1/shop/settings',{'store_name':'QR Test','bank_bin':'970422','bank_account':'1234567890','bank_name':'MB Bank'})
        order=self.place(self.payload(payment_method='QR'))
        path='/api/shop/orders/'+str(order['id'])
        self.assertIn('bank',self.client.get(path).json())
        self.assertEqual(self.client.get(path+'/qr?format=png').status_code,200)
        detail=self.client.get(path)
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertEqual(detail.json()['bank']['amount'],72000)
        self.assertEqual(detail.json()['bank']['bank_bin'],'970422')
        png=self.client.get(path+'/qr?format=png')
        self.assertEqual(png.status_code,200,png.text[:50] if png.status_code!=200 else '')
        self.assertEqual(png.headers['content-type'],'image/png')
        self.assertTrue(png.content.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn('.png',png.headers['content-disposition'])
        self.assertEqual(png.headers['cache-control'],'no-store')
        from PIL import Image
        from io import BytesIO
        image=Image.open(BytesIO(png.content));image.load()
        self.assertEqual(image.width,image.height);self.assertGreater(image.width,200)
        self.assertEqual(self.client.get(path+'/qr?format=svg').status_code,200)
        self.assertEqual(self.client.get(path+'/qr?format=unknown').status_code,400)
        self.post(path+'/report-payment',{},client=self.client)
        self.action(order,'paid',{'amount':72000,'reference':'BANK-QR-TEST-ONE'})
        self.assertEqual(self.client.get(path).json()['bank']['amount'],0)
        self.assertEqual(self.client.get(path+'/qr?format=png').status_code,409)

    def test_qr_order_detail_is_available_only_to_order_customer(self):
        order=self.place();path='/api/shop/orders/'+str(order['id'])
        self.assertEqual(TestClient(app).get(path).status_code,401)
        self.assertEqual(self.staff.get(path).status_code,401)
        self.assertEqual(self.client.get(path).status_code,200)
        self.register('0900000001')
        self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get(path+'/qr?format=png').status_code,404)

    def test_migration_is_idempotent_and_keeps_existing_values(self):
        order = self.place()
        before = self.client.get("/api/shop/orders").json()
        migrate()
        migrate()
        self.assertEqual(self.client.get("/api/shop/orders").json(), before)
        with reading() as conn:
            self.assertEqual(
                one(conn, "SELECT MAX(version) n FROM schema_migrations")["n"],
                SCHEMA_VERSION,
            )
            self.assertEqual(rows(conn, "PRAGMA foreign_key_check"), [])


if __name__ == "__main__":
    unittest.main()
