import {
  replace,
  api,
  el,
  button,
  panel,
  toolbar,
  table,
  money,
  qty,
  badge,
  label,
  actions,
  formModal,
  owner,
  state,
  tabs,
  refresh,
  today,
  csv,
} from "./ui.js?v=3.1";
let activeTab = "attendance",
  selectedMonth = Number(today().slice(5, 7)),
  selectedYear = Number(today().slice(0, 4));
const n = (name, label, value = 0, extra = {}) => ({
  name,
  label,
  type: "number",
  value,
  ...extra,
});
const t = (name, label, extra = {}) => ({ name, label, ...extra });
const s = (name, label, options, extra = {}) => ({
  name,
  label,
  options,
  ...extra,
});

export async function renderHR(content) {
  const data = await api("/hr");
  const body = el("div"),
    tabBox = el("div");
  const employees = data.employees.map((e) => [e.id, e.name]),
    colleagues = data.colleagues.map((e) => [e.id, e.name]);
  const chooseEmployee = () =>
    owner()
      ? [s("employee_id", "Nhân viên", employees, { numeric: true })]
      : [];
  function employeeForm(emp = {}) {
    formModal(
      emp.id ? "Chỉnh hồ sơ nhân viên" : "Thêm nhân viên",
      [
        t("name", "Họ tên"),
        s("role", "Vị trí", [
          ["Chu tiem", "Chủ tiệm"],
          ["Thu ngan", "Thu ngân"],
          ["Kiem kho", "Kiểm kho"],
          ["Tai xe giao hang", "Giao hàng"],
        ]),
        t("phone", "Điện thoại", { required: false }),
        s("salary_mode", "Cách tính lương", [
          ["MONTHLY", "Theo công / tháng"],
          ["HOURLY", "Theo giờ"],
        ]),
        n("base_salary", "Lương tháng"),
        n("hourly_rate", "Đơn giá giờ"),
        n("working_days", "Ngày công chuẩn", 26, { min: 1, max: 31 }),
        s("status", "Trạng thái", [
          ["ACTIVE", "Đang làm"],
          ["INACTIVE", "Đã nghỉ"],
        ]),
      ],
      (d) =>
        api(
          "/hr/employees" + (emp.id ? "/" + emp.id : ""),
          d,
          emp.id ? "PATCH" : "POST",
        ),
      emp,
    );
  }
  function shiftForm(shift = {}) {
    formModal(
      shift.id ? "Sửa ca làm" : "Tạo ca làm",
      [
        t("name", "Tên ca"),
        t("start_time", "Bắt đầu", { type: "time", value: "08:00" }),
        t("end_time", "Kết thúc", { type: "time", value: "16:00" }),
      ],
      (d) =>
        api(
          "/hr/shifts" + (shift.id ? "/" + shift.id : ""),
          d,
          shift.id ? "PATCH" : "POST",
        ),
      shift,
    );
  }
  async function draw(tab) {
    activeTab = tab;
    replace(
      tabBox,
      tabs(
        [
          ["attendance", "Chấm công"],
          ["schedule", "Lịch ca"],
          ["requests", "Xin nghỉ / đổi ca"],
          ...(owner() ? [["employees", "Nhân viên"]] : []),
          ["payroll", "Bảng lương"],
        ],
        tab,
        draw,
      ),
    );
    replace(body);
    if (tab === "employees") {
      body.append(
        panel(
          "Hồ sơ đội ngũ",
          toolbar(button("+ Nhân viên", () => employeeForm(), "primary")),
          table(data.employees, [
            { label: "Họ tên", key: "name" },
            { label: "Vị trí", key: "role" },
            { label: "Điện thoại", key: "phone" },
            { label: "Loại lương", render: (e) => label(e.salary_mode) },
            {
              label: "Lương tháng / giờ",
              render: (e) =>
                money(e.base_salary) + " / " + money(e.hourly_rate),
            },
            { label: "Trạng thái", render: (e) => badge(e.status) },
            {
              label: "Thao tác",
              render: (e) =>
                button("Chỉnh sửa", () => employeeForm(e), "small"),
            },
          ]),
        ),
      );
    }
    if (tab === "attendance") {
      body.append(
        panel(
          "Chấm công vào / ra",
          toolbar(
            button(
              "Vào ca",
              () =>
                formModal(
                  "Chấm công vào",
                  [
                    ...chooseEmployee(),
                    t("gps_location", "Tọa độ GPS (nếu có)", {
                      required: false,
                    }),
                  ],
                  (d) => api("/hr/clock", { ...d, action: "IN" }),
                ),
              "primary",
            ),
            button("Ra ca", () =>
              formModal("Chấm công ra", chooseEmployee(), (d) =>
                api("/hr/clock", { ...d, action: "OUT" }),
              ),
            ),
            owner()
              ? button("Điều chỉnh công", () =>
                  formModal(
                    "Điều chỉnh giờ công",
                    [
                      s("employee_id", "Nhân viên", employees, {
                        numeric: true,
                      }),
                      t("work_date", "Ngày ca", {
                        type: "date",
                        value: today(),
                      }),
                      t("check_in_at", "Thời điểm vào", {
                        type: "datetime-local",
                      }),
                      t("check_out_at", "Thời điểm ra", {
                        type: "datetime-local",
                      }),
                      t("note", "Lý do điều chỉnh"),
                    ],
                    (d) => api("/hr/attendance/correct", d),
                  ),
                )
              : null,
          ),
          el(
            "p",
            { class: "hint" },
            "Chấm công theo ca được phân. Đi trễ khi vượt giờ bắt đầu 5 phút. Tọa độ được ghi nhận từ người dùng, chưa xác thực phạm vi GPS.",
          ),
          table(data.attendance, [
            { label: "Ngày", key: "work_date" },
            { label: "Nhân viên", key: "employee_name" },
            { label: "Vào", key: "check_in" },
            { label: "Ra", key: "check_out" },
            { label: "Giờ công", render: (a) => qty(a.hours_worked) },
            { label: "Trễ (phút)", key: "late_minutes" },
            { label: "Trạng thái", render: (a) => badge(a.status) },
            { label: "Ghi chú", key: "note" },
          ]),
        ),
      );
    }
    if (tab === "schedule") {
      body.append(
        panel(
          "Lịch làm việc",
          owner()
            ? toolbar(
                button(
                  "+ Xếp ca",
                  () =>
                    formModal(
                      "Xếp ca làm việc",
                      [
                        s("employee_id", "Nhân viên", employees, {
                          numeric: true,
                        }),
                        s(
                          "shift_id",
                          "Ca làm",
                          data.shifts.map((sh) => [
                            sh.id,
                            sh.name + " " + sh.start_time + "–" + sh.end_time,
                          ]),
                          { numeric: true },
                        ),
                        t("work_date", "Ngày", {
                          type: "date",
                          value: today(),
                        }),
                      ],
                      (d) => api("/hr/schedule", d),
                    ),
                  "primary",
                ),
                button("+ Tạo ca", () => shiftForm()),
              )
            : null,
          table(data.schedule, [
            { label: "Ngày", key: "work_date" },
            { label: "Nhân viên", key: "employee_name" },
            { label: "Ca", key: "shift_name" },
            { label: "Bắt đầu", key: "start_time" },
            { label: "Kết thúc", key: "end_time" },
          ]),
        ),
        panel(
          "Định nghĩa ca",
          el(
            "p",
            { class: "hint" },
            "Giờ kết thúc nhỏ hơn giờ bắt đầu được tính là ca qua đêm.",
          ),
          table(data.shifts, [
            { label: "Tên", key: "name" },
            { label: "Bắt đầu", key: "start_time" },
            { label: "Kết thúc", key: "end_time" },
            ...(owner()
              ? [
                  {
                    label: "Thao tác",
                    render: (sh) => button("Sửa", () => shiftForm(sh), "small"),
                  },
                ]
              : []),
          ]),
        ),
      );
    }
    if (tab === "requests") {
      body.append(
        panel(
          "Yêu cầu nghỉ / đổi ca",
          toolbar(
            button(
              "+ Gửi yêu cầu",
              () =>
                formModal(
                  "Xin nghỉ hoặc đổi ca",
                  [
                    ...chooseEmployee(),
                    s("kind", "Loại yêu cầu", [
                      ["LEAVE", "Xin nghỉ"],
                      ["SWAP", "Đổi ca"],
                    ]),
                    t("work_date", "Ngày", { type: "date", value: today() }),
                    s("target_employee_id", "Đổi cùng nhân viên", colleagues, {
                      numeric: true,
                      required: false,
                    }),
                    t("reason", "Lý do"),
                  ],
                  (d) => api("/hr/requests", d),
                ),
              "primary",
            ),
          ),
          table(data.requests, [
            { label: "Nhân viên", key: "employee_name" },
            { label: "Yêu cầu", render: (r) => label(r.kind) },
            { label: "Ngày", key: "work_date" },
            { label: "Đổi cùng", key: "target_name" },
            { label: "Lý do", key: "reason" },
            { label: "Trạng thái", render: (r) => badge(r.status) },
            ...(owner()
              ? [
                  {
                    label: "Xét duyệt",
                    render: (r) =>
                      r.status === "PENDING"
                        ? actions(
                            button(
                              "Duyệt",
                              async () => {
                                await api("/hr/requests/" + r.id + "/review", {
                                  status: "APPROVED",
                                });
                                await refresh();
                              },
                              "small primary",
                            ),
                            button(
                              "Từ chối",
                              async () => {
                                await api("/hr/requests/" + r.id + "/review", {
                                  status: "REJECTED",
                                });
                                await refresh();
                              },
                              "small danger",
                            ),
                          )
                        : null,
                  },
                ]
              : []),
          ]),
        ),
      );
    }
    if (tab === "payroll") {
      const month = el(
        "select",
        { ariaLabel: "Tháng" },
        Array.from({ length: 12 }, (_, i) =>
          el("option", { value: i + 1 }, "Tháng " + (i + 1)),
        ),
      );
      month.value = selectedMonth;
      const year = el("input", {
          type: "number",
          min: 2000,
          max: 2100,
          value: selectedYear,
          ariaLabel: "Năm",
        }),
        payBody = el("div");
      month.addEventListener("change", () => {
        selectedMonth = Number(month.value);
      });
      year.addEventListener("change", () => {
        selectedYear = Number(year.value);
      });
      async function load() {
        selectedMonth = Number(month.value);
        selectedYear = Number(year.value);
        const payroll = await api(
          "/hr/payroll?month=" + selectedMonth + "&year=" + selectedYear,
        );
        replace(
          payBody,
          payroll.some((p) => !p.calculated_at)
            ? el(
                "div",
                { class: "notice" },
                "Bảng hiện tại có dữ liệu mẫu/cũ. Hãy tính lại từ chấm công trước khi duyệt.",
              )
            : null,
          table(payroll, [
            { label: "Nhân viên", key: "employee_name" },
            { label: "Ngày công", key: "days_worked" },
            { label: "Giờ công", render: (p) => qty(p.hours_worked) },
            { label: "Theo công", render: (p) => money(p.base_salary) },
            { label: "Thưởng", render: (p) => money(p.bonus) },
            { label: "Khấu trừ", render: (p) => money(p.deduction) },
            {
              label: "Thực lĩnh",
              render: (p) => el("strong", {}, money(p.total)),
            },
            { label: "Trạng thái", render: (p) => badge(p.status) },
          ]),
          toolbar(
            button("Xuất CSV", () =>
              csv("bang-luong.csv", payroll, [
                { key: "employee_name", label: "Nhân viên" },
                { key: "days_worked", label: "Ngày công" },
                { key: "hours_worked", label: "Giờ công" },
                { key: "base_salary", label: "Lương công" },
                { key: "bonus", label: "Thưởng" },
                { key: "deduction", label: "Khấu trừ" },
                { key: "total", label: "Thực lĩnh" },
              ]),
            ),
          ),
        );
      }
      function calculate() {
        const fields = data.employees
          .filter((e) => e.status === "ACTIVE")
          .flatMap((e) => [
            n("bonus_" + e.id, "Thưởng · " + e.name),
            n("deduction_" + e.id, "Khấu trừ · " + e.name),
          ]);
        formModal(
          "Tính lương tháng " + month.value + "/" + year.value,
          fields,
          (d) => {
            const adjustments = {};
            for (const emp of data.employees)
              adjustments[emp.id] = {
                bonus: d["bonus_" + emp.id] || 0,
                deduction: d["deduction_" + emp.id] || 0,
              };
            return api("/hr/payroll/calculate", {
              month: Number(month.value),
              year: Number(year.value),
              adjustments,
            });
          },
        );
      }
      body.append(
        panel(
          "Bảng lương",
          toolbar(
            month,
            year,
            button("Xem", load, "primary"),
            owner() ? button("Tính từ chấm công", calculate) : null,
            owner()
              ? button("Duyệt & khóa bảng lương", () =>
                  formModal(
                    "Duyệt lương tháng " + month.value + "/" + year.value,
                    [],
                    () =>
                      api("/hr/payroll/approve", {
                        month: Number(month.value),
                        year: Number(year.value),
                      }),
                  ),
                )
              : null,
          ),
          el(
            "p",
            { class: "hint" },
            "Chỉ các ca có đủ thời điểm vào/ra mới được tính. Lương tháng phân bổ theo ngày công chuẩn; lương giờ theo giờ thực tế. Bảng đã duyệt không được sửa công hoặc tính lại.",
          ),
          payBody,
        ),
      );
      await load();
    }
  }
  replace(
    content,
    toolbar(
      button("Đổi mật khẩu của tôi", () =>
        formModal(
          "Đổi mật khẩu",
          [
            t("current_password", "Mật khẩu hiện tại", { type: "password" }),
            t("password", "Mật khẩu mới từ 10 ký tự", { type: "password" }),
          ],
          async (d) => {
            await api("/api/password", d);
            location.href = "/login";
          },
        ),
      ),
    ),
    !owner() && !state.user.employee_id
      ? el(
          "div",
          { class: "notice" },
          "Tài khoản chưa liên kết hồ sơ nhân viên. Chủ tiệm có thể liên kết tại Cài đặt → Tài khoản.",
        )
      : null,
    tabBox,
    body,
  );
  await draw(activeTab);
}

let settingsTab = "users";
export async function renderSettings(content) {
  const body = el("div"),
    nav = el("div");
  async function draw(tab) {
    settingsTab = tab;
    replace(
      nav,
      tabs(
        [
          ["users", "Tài khoản & quyền"],
          ["registrations", "Duyệt đăng ký"],
          ["backups", "Sao lưu & khôi phục"],
          ["audit", "Nhật ký thao tác"],
        ],
        tab,
        draw,
      ),
    );
    replace(body);
    if (tab === "users") {
      const [users, hr, registrations] = await Promise.all([
        api("/users"),
        api("/hr"),
        api("/registrations"),
      ]);
      const pendingCount = registrations.filter(
        (r) => r.status === "PENDING",
      ).length;
      function edit(user = {}) {
        const fields = [
          ...(!user.id
            ? [t("username", "Tên đăng nhập"), t("name", "Họ tên")]
            : []),
          t(
            "password",
            user.id
              ? "Mật khẩu mới (để trống nếu giữ nguyên)"
              : "Mật khẩu từ 10 ký tự",
            { type: "password", required: !user.id },
          ),
          s("role", "Vai trò", [
            ["owner", "Chủ tiệm"],
            ["cashier", "Thu ngân"],
            ["inventory", "Kiểm kho"],
            ["shipper", "Giao hàng"],
          ]),
          s(
            "employee_id",
            "Hồ sơ nhân viên liên kết",
            hr.employees.map((e) => [e.id, e.name]),
            { numeric: true, required: false },
          ),
          ...(user.id
            ? [
                {
                  name: "active",
                  label: "Được phép đăng nhập",
                  type: "checkbox",
                },
              ]
            : []),
        ];
        formModal(
          user.id ? "Cập nhật tài khoản" : "Tạo tài khoản",
          fields,
          (d) =>
            api(
              "/users" + (user.id ? "/" + user.id : ""),
              d,
              user.id ? "PATCH" : "POST",
            ),
          user,
        );
      }
      body.append(
        panel(
          "Tài khoản cửa hàng",
          toolbar(
            button("+ Tạo tài khoản", () => edit(), "primary"),
            button(`Duyệt đăng ký (${pendingCount})`, () =>
              draw("registrations"),
            ),
          ),
          el(
            "p",
            { class: "hint" },
            "Chủ tiệm: toàn quyền. Thu ngân: bán hàng, khách hàng và tiền mặt. Kiểm kho: kho, nhà cung cấp và soạn hàng. Giao hàng: chỉ các đơn được phân công. Nhân viên xem công/lương của mình.",
          ),
          table(users, [
            { label: "Tên đăng nhập", key: "username" },
            { label: "Họ tên", key: "name" },
            { label: "Vai trò", render: (u) => badge(u.role) },
            {
              label: "Trạng thái",
              render: (u) => (u.active ? "Hoạt động" : "Đã khóa"),
            },
            {
              label: "Thao tác",
              render: (u) => button("Quyền / mật khẩu", () => edit(u), "small"),
            },
          ]),
        ),
      );
    }
    if (tab === "registrations") {
      const [requests, hr, users] = await Promise.all([
        api("/registrations"),
        api("/hr"),
        api("/users"),
      ]);
      const availableEmployees = hr.employees.filter(
        (e) =>
          e.status === "ACTIVE" && !users.some((u) => u.employee_id === e.id),
      );
      const approve = (registration) =>
        formModal(
          "Duyệt tài khoản " +
            registration.username +
            " · " +
            label(registration.role),
          [
            s(
              "employee_id",
              "Liên kết nhân viên (để trống: tạo hồ sơ mới)",
              availableEmployees.map((e) => [e.id, e.name]),
              { numeric: true, required: false },
            ),
            t("note", "Ghi chú duyệt", { required: false }),
          ],
          (data) =>
            api("/registrations/" + registration.id + "/review", {
              ...data,
              status: "APPROVED",
            }),
        );
      body.append(
        panel(
          "Yêu cầu đăng ký tài khoản",
          toolbar(button("Tải lại danh sách", () => draw("registrations"))),
          el(
            "p",
            { class: "hint" },
            "Chỉ tài khoản được duyệt mới được đăng nhập. Để trống hồ sơ liên kết sẽ tạo nhân viên mới với mức lương 0; chủ tiệm cập nhật mức lương tại Nhân sự. Duyệt vai trò Chủ tiệm sẽ cấp toàn quyền quản lý cửa hàng.",
          ),
          table(requests, [
            {
              label: "Người đăng ký",
              render: (r) =>
                el(
                  "div",
                  {},
                  el("strong", {}, r.name),
                  el("small", {}, r.username),
                ),
            },
            { label: "Điện thoại", key: "phone" },
            { label: "Vai trò yêu cầu", render: (r) => badge(r.role) },
            { label: "Ngày đăng ký", key: "created_at" },
            {
              label: "Trạng thái",
              render: (r) =>
                r.status === "PENDING"
                  ? el("span", { class: "badge warn" }, "Chờ duyệt")
                  : badge(r.status),
            },
            { label: "Ghi chú", key: "review_note" },
            {
              label: "Xử lý",
              render: (r) =>
                r.status === "PENDING"
                  ? actions(
                      button("Duyệt", () => approve(r), "small primary"),
                      button(
                        "Từ chối",
                        () =>
                          formModal(
                            "Từ chối đăng ký " + r.username,
                            [t("note", "Lý do từ chối")],
                            (data) =>
                              api("/registrations/" + r.id + "/review", {
                                ...data,
                                status: "REJECTED",
                              }),
                          ),
                        "small danger",
                      ),
                    )
                  : el("small", {}, r.reviewer || "—"),
            },
          ]),
        ),
      );
    }
    if (tab === "backups") {
      const backups = await api("/backups");
      body.append(
        panel(
          "Bản sao lưu dữ liệu",
          toolbar(
            button(
              "+ Sao lưu ngay",
              async () => {
                await api("/backups", {});
                toast("Đã tạo bản sao lưu");
                await draw("backups");
              },
              "primary",
            ),
          ),
          el(
            "div",
            { class: "notice" },
            "Khôi phục thay thế dữ liệu hiện tại và đăng xuất mọi tài khoản. Hệ thống tự tạo thêm bản sao an toàn trước khi khôi phục. Chỉ bản sao Retail v3 có tài khoản chủ tiệm và toàn vẹn dữ liệu mới được chấp nhận.",
          ),
          table(backups, [
            { label: "Tên bản sao", key: "name" },
            { label: "Tạo lúc", key: "created_at" },
            { label: "Kích thước", render: (b) => qty(b.size / 1024) + " KB" },
            {
              label: "Thao tác",
              render: (b) =>
                actions(
                  el(
                    "a",
                    {
                      href:
                        "/api/v1/backups/" +
                        encodeURIComponent(b.name) +
                        "/download",
                      class: "button small",
                    },
                    "Tải xuống",
                  ),
                  button(
                    "Khôi phục",
                    () =>
                      formModal(
                        "Khôi phục " + b.name,
                        [
                          t(
                            "confirmation",
                            "Nhập KHOI PHUC để xác nhận thay thế dữ liệu",
                          ),
                        ],
                        async (d) => {
                          await api(
                            "/backups/" +
                              encodeURIComponent(b.name) +
                              "/restore",
                            d,
                          );
                          location.href = "/login";
                        },
                      ),
                    "small danger",
                  ),
                ),
            },
          ]),
        ),
      );
    }
    if (tab === "audit") {
      const entries = await api("/audit");
      body.append(
        panel(
          "Nhật ký hoạt động gần đây",
          table(entries, [
            { label: "Thời gian", key: "created_at" },
            { label: "Người thực hiện", key: "actor" },
            { label: "Hành động", key: "action" },
            { label: "Đối tượng", key: "entity" },
            {
              label: "Chi tiết",
              render: (e) => el("span", { class: "mono" }, e.details),
            },
          ]),
        ),
      );
    }
  }
  replace(content, nav, body);
  await draw(settingsTab);
}
