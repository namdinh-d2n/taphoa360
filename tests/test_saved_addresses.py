"""Saved locations belong to authenticated accounts, not shared browser storage."""

from pathlib import Path
import tempfile
import unittest
import uuid
from fastapi.testclient import TestClient
from retail.database import one, rows, reading, transaction, migrate, SCHEMA_VERSION
from retail.locations import dataset
from scripts.store_snapshot import export_snapshot, restore_snapshot
import config


class SavedAddressTests(unittest.TestCase):
    def setUp(self):
        from test_commerce import CommerceTests

        self.e = CommerceTests("test_vietqr_payload_round_trip_and_crc")
        self.e.setUp()
        self.client = self.e.client

    def tearDown(self):
        self.e.tearDown()

    def save(self, data, expected=200):
        response = self.client.put("/api/shop/address", json=data)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json().get("saved_address")

    def manual(self, **extra):
        return {
            "address_mode": "MANUAL",
            "address": "Căn A1, đường Thử, Hà Nội",
            "receiver": "Người nhận A",
            "phone": "0900000001",
            "zone_id": self.e.zone,
            **extra,
        }

    def structured(self, **extra):
        p = dataset()["provinces"][0]
        w = p["wards"][0]
        return {
            "address_mode": "SELECT",
            "province_code": p["code"],
            "ward_code": w["code"],
            "address_line": "Căn A1, 12 đường Thử",
            "receiver": "Người nhận A",
            "phone": "0900000001",
            "zone_id": self.e.zone,
            **extra,
        }

    def test_save_survives_logout_relogin_new_session_and_partial_zone_update(self):
        self.assertIsNone(self.client.get("/api/shop/me").json()["saved_address"])
        saved = self.save(self.manual())
        self.assertEqual(saved["address"], self.manual()["address"])
        self.assertTrue(saved["zone_available"])
        self.e.post("/api/shop/logout", {}, client=self.client)
        fresh = TestClient(self.e.staff.app)
        try:
            response = fresh.post(
                "/api/shop/login",
                json={"phone": "0900000000", "password": "customer-password-123"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(fresh.get("/api/shop/me").json()["saved_address"], saved)
        finally:
            fresh.close()
        self.e.post(
            "/api/shop/login",
            {"phone": "0900000000", "password": "customer-password-123"},
            client=self.client,
        )
        self.client.headers["X-CSRF-Token"] = self.client.get("/api/shop/me").json()[
            "csrf"
        ]
        self.e.post("/api/v1/shop/zones", {"name": "Khu B", "fee": 9000})
        with reading() as conn:
            new_zone = one(conn, "SELECT id FROM delivery_zones WHERE name='Khu B'")[
                "id"
            ]
        changed = self.save({"zone_id": new_zone})
        self.assertEqual(changed["address"], saved["address"])
        self.assertEqual(changed["zone_id"], new_zone)
        self.assertEqual(
            self.client.get("/api/shop/address").json()["saved_address"], changed
        )

    def test_address_isolated_per_account_even_if_payload_names_another_account(self):
        first = self.save(self.manual())
        with reading() as conn:
            first_id = one(
                conn, "SELECT id FROM shop_accounts WHERE phone=?", ("0900000000",)
            )["id"]
        self.e.register("0900000002")
        self.assertIsNone(self.client.get("/api/shop/me").json()["saved_address"])
        self.save(self.manual(expected_account_id=first_id), 409)
        self.assertIsNone(self.client.get("/api/shop/me").json()["saved_address"])
        self.save(self.manual(address="Địa chỉ B, không phải A", account_id=first_id))
        self.e.post(
            "/api/shop/login",
            {"phone": "0900000000", "password": "customer-password-123"},
            client=self.client,
        )
        self.assertEqual(self.client.get("/api/shop/me").json()["saved_address"], first)
        self.assertNotIn("saved_address", self.e.staff.get("/api/shop/catalog").json())

    def test_structured_address_is_normalized_and_rejects_mismatched_ward_atomically(
        self,
    ):
        saved = self.save(self.structured(address="FORGED"))
        self.assertNotIn("FORGED", saved["address"])
        wrong = dataset()["provinces"][1]["wards"][0]["code"]
        self.save(self.structured(ward_code=wrong), 400)
        self.assertEqual(self.client.get("/api/shop/me").json()["saved_address"], saved)
        self.save(self.manual(phone="invalid"), 400)
        self.save(self.manual(address=""), 400)

    def test_address_requires_customer_auth_csrf_and_same_origin(self):
        self.assertEqual(self.e.staff.get("/api/shop/address").status_code, 401)
        self.assertEqual(
            self.e.staff.put("/api/shop/address", json=self.manual()).status_code, 401
        )
        self.assertEqual(
            self.client.put(
                "/api/shop/address", json=self.manual(), headers={"X-CSRF-Token": ""}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(
                "/api/shop/address",
                json=self.manual(),
                headers={"Origin": "https://other.invalid"},
            ).status_code,
            403,
        )
        self.assertIsNone(self.client.get("/api/shop/me").json()["saved_address"])

    def test_unavailable_zone_does_not_erase_saved_location_and_invalid_save_is_rejected(
        self,
    ):
        saved = self.save(self.manual())
        with transaction() as conn:
            conn.execute(
                "UPDATE delivery_zones SET active=0 WHERE id=?", (self.e.zone,)
            )
        current = self.client.get("/api/shop/me").json()["saved_address"]
        self.assertFalse(current["zone_available"])
        self.assertEqual(current["address"], saved["address"])
        self.save(self.manual(), 400)
        self.assertEqual(
            self.client.get("/api/shop/me").json()["saved_address"], current
        )

    def test_successful_checkout_remembers_location_but_replay_cannot_overwrite_new_location(
        self,
    ):
        data = self.e.payload(address="Địa chỉ lúc đặt đơn")
        key = uuid.uuid4().hex
        quote = self.e.post("/api/shop/quote", data, client=self.client)
        payload = {**data, "fingerprint": quote["fingerprint"]}
        order = self.e.post(
            "/api/shop/orders",
            payload,
            client=self.client,
            headers={"Idempotency-Key": key},
        )
        saved = self.client.get("/api/shop/me").json()["saved_address"]
        self.assertEqual(saved["address"], data["address"])
        self.save(self.manual(address="Nơi nhận mới cho lần sau"))
        replay = self.e.post(
            "/api/shop/orders",
            payload,
            client=self.client,
            headers={"Idempotency-Key": key},
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            self.client.get("/api/shop/me").json()["saved_address"]["address"],
            "Nơi nhận mới cho lần sau",
        )
        with reading() as conn:
            self.assertEqual(
                one(
                    conn, "SELECT address FROM online_orders WHERE id=?", (order["id"],)
                )["address"],
                data["address"],
            )

    def test_failed_checkout_does_not_save_address(self):
        payload = self.e.payload(
            address="Không được lưu khi đơn lỗi", fingerprint="bad"
        )
        self.e.post(
            "/api/shop/orders",
            payload,
            409,
            client=self.client,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        self.assertIsNone(self.client.get("/api/shop/me").json()["saved_address"])

    def test_errand_reuses_structured_address_and_remembers_branch(self):
        saved = self.save(self.structured())
        with reading() as conn:
            branch = one(
                conn,
                "SELECT * FROM errand_branches WHERE province_code=? ORDER BY id LIMIT 1",
                (saved["province_code"],),
            )
        data = {
            "receiver": saved["receiver"],
            "phone": saved["phone"],
            "address": saved["address"],
            "province_code": branch["province_code"],
            "branch_id": branch["id"],
            "delivery_window": "Ngày mai 10 giờ",
            "budget": 300000,
            "preferences": "Hỏi trước khi thay",
            "items": [{"name": "Rau", "quantity": 1, "unit": "bó", "criteria": "Tươi"}],
        }
        key = uuid.uuid4().hex
        response = self.e.post(
            "/api/shop/errands",
            data,
            client=self.client,
            headers={"Idempotency-Key": key},
        )
        remembered = self.client.get("/api/shop/me").json()["saved_address"]
        self.assertEqual(remembered["address_mode"], "SELECT")
        self.assertEqual(remembered["ward_code"], saved["ward_code"])
        self.assertEqual(remembered["branch_id"], branch["id"])
        self.save(self.manual(address="Địa chỉ mới sau đặt"))
        self.e.post(
            "/api/shop/errands",
            data,
            client=self.client,
            headers={"Idempotency-Key": key},
        )
        self.assertEqual(
            self.client.get("/api/shop/me").json()["saved_address"]["address"],
            "Địa chỉ mới sau đặt",
        )
        self.assertEqual(
            self.client.get("/api/shop/errands/" + str(response["id"])).json()[
                "address"
            ],
            saved["address"],
        )

    def test_changing_province_clears_incompatible_branch_and_explicit_wrong_branch_is_rejected(
        self,
    ):
        with reading() as conn:
            branch = one(
                conn, "SELECT * FROM errand_branches WHERE province_code=1 LIMIT 1"
            )
        saved = self.save(self.structured(branch_id=branch["id"]))
        p = dataset()["provinces"][1]
        w = p["wards"][0]
        data = self.structured(province_code=p["code"], ward_code=w["code"])
        self.save({**data, "branch_id": branch["id"]}, 400)
        self.assertEqual(self.client.get("/api/shop/me").json()["saved_address"], saved)
        changed = self.save(data)
        self.assertIsNone(changed["branch_id"])

    def test_migration_is_additive_and_review_export_excludes_saved_location(self):
        self.save(self.manual())
        with reading() as conn:
            before = rows(conn, "SELECT * FROM customer_delivery_addresses")
        migrate()
        migrate()
        with reading() as conn:
            self.assertEqual(
                before, rows(conn, "SELECT * FROM customer_delivery_addresses")
            )
            self.assertEqual(rows(conn, "PRAGMA foreign_key_check"), [])
            self.assertEqual(
                one(conn, "SELECT MAX(version) v FROM schema_migrations")["v"],
                SCHEMA_VERSION,
            )
        snapshot = export_snapshot(config.SQLITE_PATH)
        self.assertNotIn("customer_delivery_addresses", snapshot["tables"])
        self.assertNotIn(self.manual()["address"], str(snapshot))
        self.assertTrue(
            list((Path(config.SQLITE_PATH).parent / "backups").glob("before-v14-*.db"))
        )
        with tempfile.TemporaryDirectory(prefix="saved-address-review-") as folder:
            target = Path(folder) / "review.db"
            restore_snapshot(
                snapshot, target, "review_owner", "Owner", "review-password-123"
            )


if __name__ == "__main__":
    unittest.main()
