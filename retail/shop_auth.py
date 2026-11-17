"""Customer identities are separate from staff accounts and their permissions."""

import hashlib
import hmac
import re
import secrets
import time
from fastapi import APIRouter, Depends, Request, Response
import config
from .auth import password_hash, verify, same_origin
from .common import fail, required, validate_payload
from .database import reading, transaction, one, rows

router = APIRouter(prefix="/api/shop", dependencies=[Depends(validate_payload)])


def phone_number(value):
    value = re.sub(r"[ ()-]", "", str(value or ""))
    if value.startswith("+84"):
        value = "0" + value[3:]
    if not re.fullmatch(r"0[0-9]{9}", value):
        fail("Số điện thoại cần 10 chữ số, bắt đầu bằng 0.")
    return value


def limited(conn, key, maximum=10, seconds=900):
    ident = "shop:" + hashlib.sha256(key.encode()).hexdigest()
    value = one(conn, "SELECT * FROM login_attempts WHERE key=?", (ident,))
    count = (
        value["failures"] + 1 if value and value["locked_until"] > time.time() else 1
    )
    expiry = (
        value["locked_until"]
        if value and value["locked_until"] > time.time()
        else time.time() + seconds
    )
    if count > maximum:
        fail("Quá nhiều yêu cầu. Vui lòng thử lại sau.", 429)
    conn.execute(
        "INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)", (ident, count, expiry)
    )


def customer_user(request: Request):
    token = request.cookies.get("taphoa_shop", "")
    with reading() as conn:
        user = one(
            conn,
            """SELECT a.id,a.phone,a.name,a.customer_id,c.points,s.csrf FROM shop_sessions s
            JOIN shop_accounts a ON a.id=s.account_id JOIN customers c ON c.id=a.customer_id
            WHERE s.token_hash=? AND s.expires_at>? AND a.active=1""",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        )
    if not user:
        fail("Vui lòng đăng nhập tài khoản khách hàng để đặt mua.", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        same_origin(request)
        if not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), user["csrf"].encode()
        ):
            fail("Phiên thao tác hết hạn. Hãy tải lại trang.", 403)
    return user


@router.post("/register")
def register(data: dict, request: Request):
    same_origin(request)
    with transaction() as conn:
        limited(conn, "register:" + request.client.host, 6, 3600)
    phone = phone_number(data.get("phone"))
    name = required(data, "name", "Họ tên", 100)
    if data.get("password") != data.get("confirm_password"):
        fail("Mật khẩu xác nhận không khớp.")
    hashed = password_hash(data.get("password"))
    with transaction() as conn:
        if one(conn, "SELECT id FROM shop_accounts WHERE phone=?", (phone,)):
            fail("Số điện thoại đã có tài khoản.", 409)
        # Never attach an unverified phone to an existing POS customer's points.
        customer = conn.execute(
            "INSERT INTO customers(name,phone) VALUES(?,?)", (name, phone)
        ).lastrowid
        conn.execute(
            "INSERT INTO shop_accounts(phone,name,password_hash,customer_id) VALUES(?,?,?,?)",
            (phone, name, hashed, customer),
        )
    return {"success": True}


@router.post("/login")
def login(data: dict, request: Request, response: Response):
    same_origin(request)
    with transaction() as conn:
        limited(
            conn, "login:" + request.client.host + ":" + str(data.get("phone", ""))[:30]
        )
    phone = phone_number(data.get("phone"))
    with reading() as conn:
        user = one(conn, "SELECT * FROM shop_accounts WHERE phone=?", (phone,))
    dummy = "pbkdf2_sha256$600000$" + "0" * 32 + "$" + "0" * 64
    valid = verify(
        str(data.get("password", ""))[:200], user["password_hash"] if user else dummy
    )
    if not valid or not user or not user["active"]:
        fail("Số điện thoại hoặc mật khẩu chưa đúng.", 401)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    with transaction() as conn:
        conn.execute("DELETE FROM shop_sessions WHERE expires_at<?", (time.time(),))
        conn.execute(
            "INSERT INTO shop_sessions VALUES(?,?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                user["id"],
                csrf,
                time.time() + 7 * 86400,
            ),
        )
    response.set_cookie(
        "taphoa_shop",
        token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )
    return {"success": True}


@router.get("/me")
def me(user=Depends(customer_user)):
    from .shop_addresses import saved_address

    with reading() as conn:
        ledger = rows(
            conn,
            "SELECT amount,reason,created_at FROM shop_points_ledger WHERE account_id=? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        )
        address = saved_address(conn, user["id"])
    return {**user, "ledger": ledger, "saved_address": address}


@router.get("/address")
def get_delivery_address(user=Depends(customer_user)):
    from .shop_addresses import saved_address

    with reading() as conn:
        return {"saved_address": saved_address(conn, user["id"])}


@router.put("/address")
def update_delivery_address(data: dict, user=Depends(customer_user)):
    from .shop_addresses import save_address

    if "expected_account_id" in data and data["expected_account_id"] != user["id"]:
        fail("Tài khoản đã thay đổi. Hãy mở lại biểu mẫu địa chỉ.", 409)
    with transaction() as conn:
        return {"saved_address": save_address(conn, user, data)}


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(customer_user)):
    with transaction() as conn:
        conn.execute(
            "DELETE FROM shop_sessions WHERE token_hash=?",
            (
                hashlib.sha256(
                    request.cookies.get("taphoa_shop", "").encode()
                ).hexdigest(),
            ),
        )
    response.delete_cookie("taphoa_shop", path="/")
    return {"success": True}
