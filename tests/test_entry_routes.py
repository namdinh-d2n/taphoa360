"""Public landing and internal entry use the existing authenticated staff roles."""

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import app
import config
import db
from retail.database import transaction


class EntryRouteTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(
            tempfile.TemporaryDirectory(prefix="taphoa-entry-")
        )
        database = str(Path(folder) / "shop.db")
        self.stack.enter_context(
            patch.multiple(
                config, SQLITE_PATH=database, SEED_DEMO=False, SETUP_TOKEN=""
            )
        )
        self.stack.enter_context(patch.object(db, "SQLITE_PATH", database))
        self.client = self.stack.enter_context(TestClient(app))

    def redirect(self, path, destination):
        response = self.client.get(path, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], destination)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def setup_owner(self):
        response = self.client.post(
            "/api/setup",
            json={
                "username": "owner",
                "name": "Owner",
                "password": "entry-password-123",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def login(self, username):
        response = self.client.post(
            "/api/login", json={"username": username, "password": "entry-password-123"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers["X-CSRF-Token"] = response.json()["csrf"]

    def test_first_run_keeps_customer_and_store_setup_entries_separate(self):
        self.redirect("/", "/shop")
        self.assertEqual(self.client.get("/shop").status_code, 200)
        self.redirect("/admin", "/setup")
        self.assertIn("Họ tên chủ tiệm", self.client.get("/admin").text)

    def test_guest_opens_shop_and_internal_entry_requires_login(self):
        self.setup_owner()
        self.redirect("/", "/shop")
        self.redirect("/admin", "/login")
        self.assertIn("/admin", self.client.get("/shop").text)
        self.assertIn("Đăng nhập nội bộ", self.client.get("/admin").text)
        self.assertIn("Về trang mua hàng", self.client.get("/login/owner").text)
        self.redirect("/owner", "/login/owner")
        self.assertEqual(self.client.get("/api/v1/users").status_code, 401)

    def test_staff_goes_to_own_workspace_from_both_entries(self):
        self.setup_owner()
        self.login("owner")
        for role in ["cashier", "inventory", "shipper"]:
            response = self.client.post(
                "/api/v1/users",
                json={
                    "username": role,
                    "name": role,
                    "role": role,
                    "password": "entry-password-123",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
        for role in ["owner", "cashier", "inventory", "shipper"]:
            self.login(role)
            self.redirect("/", "/" + role)
            self.redirect("/admin", "/" + role)
            self.assertEqual(self.client.get("/admin").status_code, 200)
            self.assertEqual(self.client.get("/shop").status_code, 200)

    def test_customer_account_cannot_be_used_as_staff_session(self):
        self.setup_owner()
        data = {
            "phone": "0900000000",
            "name": "Customer",
            "password": "entry-password-123",
            "confirm_password": "entry-password-123",
        }
        response = self.client.post("/api/shop/register", json=data)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/shop/login", json=data)
        self.assertEqual(response.status_code, 200, response.text)
        self.redirect("/", "/shop")
        self.redirect("/admin", "/login")
        self.assertEqual(self.client.get("/api/v1/users").status_code, 401)
        self.login("owner")
        self.redirect("/", "/owner")
        self.assertEqual(self.client.get("/shop").status_code, 200)

    def test_expired_or_locked_staff_session_falls_back_to_public_shop(self):
        self.setup_owner()
        self.login("owner")
        with transaction() as conn:
            conn.execute("UPDATE sessions SET expires_at=0")
        self.redirect("/", "/shop")
        self.redirect("/admin", "/login")
        self.login("owner")
        with transaction() as conn:
            conn.execute("UPDATE users SET active=0 WHERE username='owner'")
        self.redirect("/", "/shop")
        self.redirect("/admin", "/login")

    def test_logout_returns_entry_to_customer_mode(self):
        self.setup_owner()
        self.login("owner")
        self.redirect("/", "/owner")
        response = self.client.post("/api/logout")
        self.assertEqual(response.status_code, 200, response.text)
        self.redirect("/", "/shop")
        self.redirect("/admin", "/login")


if __name__ == "__main__":
    unittest.main()
