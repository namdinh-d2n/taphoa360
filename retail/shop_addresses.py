"""One saved delivery location per customer, separate from immutable order addresses."""

from datetime import datetime
from pathlib import Path
import sqlite3
import config
from .database import reading, transaction, one
from .common import fail, required, now, record
from .locations import address_snapshot

ADDRESS_FIELDS = (
    "address_mode",
    "province_code",
    "ward_code",
    "address_line",
    "address",
)


def migrate_addresses():
    with reading() as conn:
        if one(conn, "SELECT version FROM schema_migrations WHERE version=14"):
            return
        folder = Path(config.SQLITE_PATH).parent / "backups"
        folder.mkdir(exist_ok=True)
        target = sqlite3.connect(
            folder
            / ("before-v14-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
        )
        try:
            conn.backup(target)
        finally:
            target.close()
    with transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS customer_delivery_addresses(
            account_id INTEGER PRIMARY KEY REFERENCES shop_accounts(id),
            receiver TEXT NOT NULL,phone TEXT NOT NULL,
            address_mode TEXT NOT NULL CHECK(address_mode IN ('SELECT','MANUAL')),
            province_code INTEGER,ward_code INTEGER,address_line TEXT NOT NULL,address TEXT NOT NULL,
            zone_id INTEGER REFERENCES delivery_zones(id),branch_id INTEGER REFERENCES errand_branches(id),
            updated_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO schema_migrations(version) VALUES(14)")


def saved_address(conn, account_id):
    saved = one(
        conn,
        "SELECT * FROM customer_delivery_addresses WHERE account_id=?",
        (account_id,),
    )
    if not saved:
        return None
    saved.pop("account_id")
    zone = (
        one(
            conn,
            "SELECT name,active FROM delivery_zones WHERE id=?",
            (saved["zone_id"],),
        )
        if saved["zone_id"]
        else None
    )
    branch = (
        one(
            conn,
            "SELECT name,province_code,active FROM errand_branches WHERE id=?",
            (saved["branch_id"],),
        )
        if saved["branch_id"]
        else None
    )
    saved["zone_available"] = bool(zone and zone["active"])
    saved["zone_name"] = zone["name"] if zone else ""
    saved["branch_available"] = bool(branch and branch["active"])
    saved["errand_province_code"] = (
        branch["province_code"] if branch else saved["province_code"]
    )
    return saved


def save_address(conn, user, data):
    from .shop_auth import phone_number

    old = (
        one(
            conn,
            "SELECT * FROM customer_delivery_addresses WHERE account_id=?",
            (user["id"],),
        )
        or {}
    )
    merged = {**old, **data}
    address = address_snapshot(merged)
    receiver = required(
        {"receiver": merged.get("receiver", user["name"])},
        "receiver",
        "Người nhận",
        100,
    )
    phone = phone_number(merged.get("phone", user["phone"]))
    zone_id = merged.get("zone_id") or None
    if "zone_id" in data and zone_id:
        zone = record(conn, "delivery_zones", zone_id)
        if not zone["active"]:
            fail("Khu giao này đã ngừng phục vụ. Vui lòng chọn khu khác.")
        zone_id = zone["id"]
    branch_id = merged.get("branch_id") or None
    if branch_id:
        branch = record(conn, "errand_branches", branch_id)
        compatible = (
            not address["province_code"]
            or branch["province_code"] == address["province_code"]
        )
        if "branch_id" in data and (not branch["active"] or not compatible):
            fail(
                "Cửa hàng không thuộc tỉnh/thành của địa chỉ nhận hoặc đã ngừng phục vụ."
            )
        if not branch["active"] or not compatible:
            branch_id = None
        else:
            branch_id = branch["id"]
    values = {
        "account_id": user["id"],
        "receiver": receiver,
        "phone": phone,
        **address,
        "zone_id": zone_id,
        "branch_id": branch_id,
        "updated_at": now(),
    }
    columns = tuple(values)
    updates = ",".join(
        name + "=excluded." + name for name in columns if name != "account_id"
    )
    conn.execute(
        "INSERT INTO customer_delivery_addresses("
        + ",".join(columns)
        + ") VALUES("
        + ",".join("?" for _ in columns)
        + ") ON CONFLICT(account_id) DO UPDATE SET "
        + updates,
        tuple(values.values()),
    )
    return saved_address(conn, user["id"])


def remember_order_address(conn, user, data, errand=False):
    """Called only for newly committed orders, never for idempotent replays."""
    old = saved_address(conn, user["id"])
    address = {name: data[name] for name in ADDRESS_FIELDS if name in data}
    if errand and old and data.get("address") == old["address"]:
        address = {name: old[name] for name in ADDRESS_FIELDS}
    elif "address_mode" not in address:
        address = {"address_mode": "MANUAL", "address": data["address"]}
    preferences = (
        {"branch_id": data["branch_id"]} if errand else {"zone_id": data["zone_id"]}
    )
    return save_address(
        conn,
        user,
        {
            **address,
            **preferences,
            "receiver": data["receiver"],
            "phone": data["phone"],
        },
    )
