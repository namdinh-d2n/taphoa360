"""
HR (Human Resources) module for Tạp hóa 360.
Manages employees, shifts, attendance, and payroll.
"""

from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

ROLE_MAP = {
    "Chu tiem": "Chủ tiệm",
    "Thu ngan": "Thu ngân",
    "Kiem kho": "Kiểm kho",
    "Tai xe giao hang": "Tài xế giao hàng",
}

SHIFT_COLOR_MAP = {
    "SANG":  {"bg": "bg-emerald-100", "text": "text-emerald-800", "badge": "bg-emerald-500"},
    "CHIEU": {"bg": "bg-blue-100",    "text": "text-blue-800",    "badge": "bg-blue-500"},
    "TOI":   {"bg": "bg-purple-100",  "text": "text-purple-800",  "badge": "bg-purple-500"},
    "NGHI":  {"bg": "bg-slate-100",   "text": "text-slate-500",   "badge": "bg-slate-400"},
}

STATUS_COLOR_MAP = {
    "DUNG_GIO": {"bg": "bg-emerald-100", "text": "text-emerald-700", "label": "Đúng giờ"},
    "DI_TRE":   {"bg": "bg-amber-100",   "text": "text-amber-700",   "label": "Đi trễ"},
    "VANG":     {"bg": "bg-rose-100",    "text": "text-rose-700",    "label": "Vắng"},
    "ABSENT":   {"bg": "bg-slate-100",   "text": "text-slate-500",   "label": "Chưa cập nhật"},
}


def get_hr_stats():
    total_emp = db.query_one("SELECT COUNT(*) as c FROM employees WHERE status='ACTIVE'")
    today_str = date.today().isoformat()
    checked = db.query_one(
        "SELECT COUNT(*) as c FROM attendance WHERE work_date=? AND status!='VANG' AND status!='ABSENT'",
        (today_str,)
    )
    absent = db.query_one(
        "SELECT COUNT(*) as c FROM attendance WHERE work_date=? AND status='VANG'",
        (today_str,)
    )
    total_active = total_emp["c"] if total_emp else 0
    checked_count = checked["c"] if checked else 0

    # Ca cần người thay = số người vắng có lịch làm
    shift_today = db.query_one(
        "SELECT COUNT(DISTINCT employee_id) as c FROM shift_schedule WHERE work_date=?",
        (today_str,)
    )
    missing_shifts = max(0, (shift_today["c"] if shift_today else 0) - checked_count)

    # Lương tạm tính tháng hiện tại
    m = date.today().month
    y = date.today().year
    salary_total = db.query_one(
        "SELECT SUM(total) as s FROM payroll WHERE month=? AND year=?",
        (m, y)
    )
    salary_sum = salary_total["s"] if salary_total and salary_total.get("s") else 0

    return {
        "total_employees": total_active,
        "checked_today": checked_count,
        "total_scheduled": shift_today["c"] if shift_today else total_active,
        "missing_shifts": missing_shifts,
        "salary_sum_million": round(salary_sum / 1_000_000, 1),
        "current_month": m,
        "current_year": y,
    }


def get_week_schedule(week_offset: int = 0):
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_dates = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    day_labels = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    employees = db.query_all("SELECT id, name, role FROM employees WHERE status='ACTIVE' ORDER BY id")
    shifts = db.query_all("SELECT * FROM shifts")
    shift_map = {s["id"]: s for s in shifts}

    schedule_rows = []
    for emp in employees:
        emp_id = emp["id"]
        row = {
            "employee": emp,
            "role_display": ROLE_MAP.get(emp["role"], emp["role"]),
            "days": []
        }
        for work_date in week_dates:
            sched = db.query_one(
                "SELECT shift_id FROM shift_schedule WHERE employee_id=? AND work_date=?",
                (emp_id, work_date)
            )
            if sched:
                shift = shift_map.get(sched["shift_id"], {})
                shift_name = shift.get("name", "NGHI")
                colors = SHIFT_COLOR_MAP.get(shift_name, SHIFT_COLOR_MAP["NGHI"])
                row["days"].append({"shift": shift_name, **colors})
            else:
                row["days"].append({"shift": "NGHI", **SHIFT_COLOR_MAP["NGHI"]})
        schedule_rows.append(row)

    return {
        "week_dates": week_dates,
        "day_labels": day_labels,
        "schedule_rows": schedule_rows,
        "week_start": monday.strftime("%d/%m"),
        "week_end": (monday + timedelta(days=6)).strftime("%d/%m/%Y"),
    }


def get_today_attendance():
    today_str = date.today().isoformat()
    rows = db.query_all(
        """SELECT a.*, e.name, e.role, e.avatar_initials
           FROM attendance a
           JOIN employees e ON a.employee_id = e.id
           WHERE a.work_date = ?
           ORDER BY a.id""",
        (today_str,)
    )
    result = []
    for r in rows:
        row = dict(r)
        status = row.get("status", "ABSENT")
        row["status_info"] = STATUS_COLOR_MAP.get(status, STATUS_COLOR_MAP["ABSENT"])
        row["role_display"] = ROLE_MAP.get(row.get("role", ""), row.get("role", ""))
        result.append(row)
    return result


def get_payroll_data(month: int, year: int):
    rows = db.query_all(
        """SELECT p.*, e.name, e.avatar_initials, e.role
           FROM payroll p
           JOIN employees e ON p.employee_id = e.id
           WHERE p.month=? AND p.year=?
           ORDER BY p.employee_id""",
        (month, year)
    )
    result = []
    for r in rows:
        row = dict(r)
        row["role_display"] = ROLE_MAP.get(row.get("role", ""), row.get("role", ""))
        row["total_fmt"] = f"{int(row.get('total', 0)):,}".replace(",", ".")
        row["base_salary_fmt"] = f"{int(row.get('base_salary', 0)):,}".replace(",", ".")
        result.append(row)
    return result


def get_employees_list():
    rows = db.query_all("SELECT * FROM employees ORDER BY id")
    result = []
    for r in rows:
        row = dict(r)
        row["role_display"] = ROLE_MAP.get(row.get("role", ""), row.get("role", ""))
        result.append(row)
    return result


def get_role_permissions():
    employees = db.query_all("SELECT role FROM employees WHERE status='ACTIVE'")
    role_counts = {}
    for e in employees:
        role = e["role"]
        role_counts[role] = role_counts.get(role, 0) + 1

    permissions = [
        {
            "key": "Chu tiem",
            "label": "Chủ tiệm",
            "color": "emerald",
            "icon": "crown",
            "perms": ["Toàn quyền hệ thống"],
            "count": role_counts.get("Chu tiem", 0)
        },
        {
            "key": "Thu ngan",
            "label": "Thu ngân",
            "color": "blue",
            "icon": "calculator",
            "perms": ["Tạo đơn hàng", "Xem báo cáo ca"],
            "count": role_counts.get("Thu ngan", 0)
        },
        {
            "key": "Kiem kho",
            "label": "Kiểm kho",
            "color": "purple",
            "icon": "package",
            "perms": ["Xuất/Nhập kho", "Xem tồn kho"],
            "count": role_counts.get("Kiem kho", 0)
        },
        {
            "key": "Tai xe giao hang",
            "label": "Tài xế giao hàng",
            "color": "amber",
            "icon": "truck",
            "perms": ["Xem đơn giao", "Chấm công GPS"],
            "count": role_counts.get("Tai xe giao hang", 0)
        },
    ]
    return permissions


# ---- PAGE ROUTES ----

@router.get("/hr.php", response_class=HTMLResponse)
@router.get("/hr",     response_class=HTMLResponse)
async def hr_dashboard(request: Request):
    tab = request.query_params.get("tab", "overview")
    week_offset = int(request.query_params.get("week", 0))
    month = int(request.query_params.get("month", date.today().month))
    year  = int(request.query_params.get("year",  date.today().year))

    stats = get_hr_stats()
    schedule = get_week_schedule(week_offset)
    attendance = get_today_attendance()
    payroll = get_payroll_data(month, year)
    employees = get_employees_list()
    permissions = get_role_permissions()

    return templates.TemplateResponse(
        request=request,
        name="hr.html",
        context={
            "tab": tab,
            "stats": stats,
            "schedule": schedule,
            "attendance": attendance,
            "payroll": payroll,
            "employees": employees,
            "permissions": permissions,
            "week_offset": week_offset,
            "month": month,
            "year": year,
            "today": date.today().strftime("%d/%m/%Y"),
            "SHIFT_COLOR_MAP": SHIFT_COLOR_MAP,
        }
    )


# ---- API ROUTES ----

@router.get("/api/hr/stats")
async def api_hr_stats():
    return JSONResponse(content=get_hr_stats())


@router.get("/api/hr/employees")
async def api_hr_employees():
    return JSONResponse(content={"success": True, "data": get_employees_list()})


@router.post("/api/hr/employees")
async def api_add_employee(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(content={"success": False, "message": "Invalid JSON"}, status_code=400)

    name = data.get("name", "").strip()
    if not name:
        return JSONResponse(content={"success": False, "message": "Tên nhân viên không được để trống"}, status_code=400)

    role = data.get("role", "Thu ngan")
    phone = data.get("phone", "")
    base_salary = float(data.get("base_salary", 5000000))
    hourly_rate = float(data.get("hourly_rate", 30000))
    initials = "".join([w[0].upper() for w in name.split()[:2]])

    new_id = db.execute(
        """INSERT INTO employees (name, role, phone, base_salary, hourly_rate, avatar_initials, status)
           VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')""",
        (name, role, phone, base_salary, hourly_rate, initials)
    )
    return JSONResponse(content={"success": True, "id": new_id, "message": "Thêm nhân viên thành công"})


@router.get("/api/hr/schedule")
async def api_hr_schedule(week: int = 0):
    return JSONResponse(content={"success": True, "data": get_week_schedule(week)})


@router.get("/api/hr/attendance")
async def api_hr_attendance():
    return JSONResponse(content={"success": True, "data": get_today_attendance()})


@router.post("/api/hr/attendance/checkin")
async def api_checkin(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(content={"success": False, "message": "Invalid JSON"}, status_code=400)

    emp_id = data.get("employee_id")
    gps = data.get("gps_location", "10.7769,106.7009")
    today_str = date.today().isoformat()
    now_str = datetime.now().strftime("%H:%M")

    existing = db.query_one(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
        (emp_id, today_str)
    )

    if not existing:
        db.execute(
            "INSERT INTO attendance (employee_id, work_date, check_in, status, gps_location) VALUES (?, ?, ?, 'DUNG_GIO', ?)",
            (emp_id, today_str, now_str, gps)
        )
        message = f"Chấm công vào lúc {now_str} thành công!"
    else:
        db.execute(
            "UPDATE attendance SET check_out=? WHERE employee_id=? AND work_date=?",
            (now_str, emp_id, today_str)
        )
        message = f"Chấm công ra lúc {now_str} thành công!"

    return JSONResponse(content={"success": True, "message": message, "time": now_str})


@router.get("/api/hr/payroll")
async def api_hr_payroll(month: int = None, year: int = None):
    m = month or date.today().month
    y = year or date.today().year
    return JSONResponse(content={"success": True, "data": get_payroll_data(m, y)})


@router.post("/api/hr/payroll/approve")
async def api_approve_payroll(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    m = data.get("month", date.today().month)
    y = data.get("year", date.today().year)
    db.execute("UPDATE payroll SET status='APPROVED' WHERE month=? AND year=?", (m, y))
    return JSONResponse(content={"success": True, "message": f"Đã duyệt bảng lương tháng {m}/{y}"})
