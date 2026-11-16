import {
  el,
  api,
  button,
  link,
  panel,
  toolbar,
  table,
  money,
  metric,
  formModal,
  refresh,
  csv,
  state,
} from "./ui.js?v=3.1";
export const onlineStatus = (o) =>
  o.status === "PENDING" && o.payment_flow === "PREPAY"
    ? "Chờ khách chuyển QR"
    : {
        PENDING: "Chờ duyệt COD",
        PAYMENT_REVIEW: "Chờ đối chiếu chuyển khoản",
        REVIEW: "Chờ khách duyệt thay đổi",
        CONFIRMED: "Đã duyệt · chuẩn bị giao",
        SHIPPING: "Đang giao",
        COMPLETED: "Hoàn tất",
        CANCELLED: "Đã hủy",
        EXPIRED: "Hết hạn",
      }[o.status] || o.status;
export function operationsBoard(data, openOrder) {
  const search = el("input", {
    placeholder: "Tìm mã đơn, tên hoặc số điện thoại",
    ariaLabel: "Tìm đơn online",
  });
  const filter = el(
    "select",
    { ariaLabel: "Nhóm xử lý đơn" },
    [
      ["ALL", "Tất cả"],
      ["MONEY", "Cần đối chiếu tiền"],
      ["PENDING", "Chờ khách/COD"],
      ["CONFIRMED", "Soạn & phân công"],
      ["SHIPPING", "Đang giao"],
      ["REFUND", "Cần hoàn tiền"],
      ["COMPLETED", "Hoàn tất"],
    ].map(([value, label]) => el("option", { value }, label)),
  );
  const list = el("div");
  function draw() {
    const term = search.value.trim().toLocaleLowerCase("vi");
    const result = data.orders
      .filter((o) =>
        [o.code, o.receiver, o.phone]
          .join(" ")
          .toLocaleLowerCase("vi")
          .includes(term),
      )
      .filter(
        (o) =>
          filter.value === "ALL" ||
          (filter.value === "MONEY"
            ? o.payment_status === "REPORTED" && o.paid === 0
            : filter.value === "REFUND"
              ? o.refund_due > o.refund_paid
              : o.status === filter.value),
      );
    list.replaceChildren(
      table(result, [
        {
          label: "Đơn",
          render: (o) => el("div", {}, o.code, el("small", {}, o.created_at)),
        },
        {
          label: "Khách",
          render: (o) => el("div", {}, o.receiver, el("small", {}, o.phone)),
        },
        {
          label: "Xử lý",
          render: (o) =>
            el(
              "div",
              {},
              onlineStatus(o),
              el(
                "small",
                {},
                "Soạn " +
                  o.items.filter((i) => i.is_picked).length +
                  "/" +
                  o.items.length +
                  " món",
              ),
            ),
        },
        {
          label: "Tiền",
          render: (o) =>
            el(
              "div",
              {},
              money(o.total),
              el(
                "small",
                {},
                o.payment_status === "REPORTED"
                  ? "Khách báo chuyển · chưa đối chiếu"
                  : "Đã nhận " + money(o.paid),
              ),
            ),
        },
        {
          label: "Phân công",
          render: (o) =>
            el(
              "div",
              {},
              data.workers?.find((p) => p.id === o.picker_id)?.name ||
                "Chưa giao người soạn",
              el(
                "small",
                {},
                data.shippers?.find((p) => p.id === o.shipper_id)?.name ||
                  "Chưa phân công giao",
              ),
            ),
        },
        {
          label: "Thao tác",
          render: (o) =>
            button("Xem / xử lý", () => openOrder(o, data), "small"),
        },
      ]),
    );
  }
  search.oninput = filter.onchange = draw;
  draw();
  const r = data.responsibilities || {};
  return panel(
    "Điều phối đơn online",
    el(
      "div",
      { class: "cards" },
      metric(
        "Cần đối chiếu tiền",
        data.orders.filter(
          (o) => o.payment_status === "REPORTED" && o.paid === 0,
        ).length,
        "Thu ngân kiểm tra giao dịch thật",
      ),
      metric(
        "Đang soạn",
        data.orders.filter((o) => o.status === "CONFIRMED").length,
        "Duyệt xong mới soạn/giao",
      ),
      metric(
        "Đang giao",
        data.orders.filter((o) => o.status === "SHIPPING").length,
        "Shipper kiểm nhận tại nơi giao",
      ),
    ),
    el(
      "p",
      { class: "notice" },
      "Phụ trách thu chi: " +
        (r.online_cashier_id?.name || "Chủ tiệm / thu ngân") +
        " · Điều phối hàng: " +
        (r.online_dispatcher_id?.name || "Chủ tiệm / đội kiểm kho"),
    ),
    toolbar(
      search,
      filter,
      button("Tải lại", refresh),
      link("Mở cửa hàng khách", "/shop"),
    ),
    list,
  );
}
export async function financePanel() {
  const data = await api("/shop/finance");
  function expense() {
    const key = crypto.randomUUID();
    formModal(
      "Ghi khoản chi online",
      [
        { name: "amount", label: "Số tiền thực chi", type: "number", min: 1 },
        {
          name: "method",
          label: "Phương thức",
          options: [
            ["CASH", "Tiền mặt"],
            ["TRANSFER", "Chuyển khoản"],
          ],
        },
        {
          name: "note",
          label: "Lý do / mã biên nhận (giao hàng, đóng gói...)",
        },
      ],
      (d) =>
        api("/shop/finance/expenses", d, "POST", { "Idempotency-Key": key }),
    );
  }
  function handover(c) {
    formModal(
      "Nhận bàn giao COD từ " + c.name,
      [
        {
          name: "amount",
          label: "Số tiền nhận",
          type: "number",
          value: c.outstanding,
          min: 1,
          max: c.outstanding,
        },
        { name: "reference", label: "Mã biên nhận bàn giao" },
        { name: "note", label: "Ghi chú", required: false },
      ],
      (d) => api("/shop/finance/handovers", { ...d, collector_id: c.id }),
    );
  }
  return panel(
    "Thu – chi online & bàn giao COD",
    el(
      "div",
      { class: "cards" },
      metric(
        "Đã thực nhận",
        money(data.totals.income),
        "Chỉ tiền đã đối chiếu / COD đã thu",
      ),
      metric(
        "Đã chi / hoàn",
        money(data.totals.expense),
        "Theo biên nhận đã ghi",
      ),
      metric(
        "Thu – chi ròng",
        money(data.totals.net),
        "Toàn bộ lịch sử online",
      ),
    ),
    el(
      "p",
      { class: "notice" },
      data.totals.payment_reports +
        " đơn khách báo chuyển đang chờ đối chiếu · Còn cần hoàn " +
        money(data.totals.refund_pending) +
        ". Bàn giao COD chỉ đổi người giữ tiền, không tính thu lần hai.",
    ),
    toolbar(
      button("+ Ghi chi phí thực tế", expense, "primary"),
      button("Xuất CSV", () =>
        csv("thu-chi-online.csv", data.entries, [
          { key: "created_at", label: "Ngày" },
          { key: "code", label: "Đơn" },
          { key: "kind", label: "Loại" },
          { key: "method", label: "Phương thức" },
          { key: "amount", label: "Số tiền" },
          { key: "actor", label: "Người ghi" },
          { key: "reference", label: "Giao dịch" },
          { key: "online_note", label: "Ghi chú" },
        ]),
      ),
    ),
    table(data.entries, [
      { label: "Thời gian", key: "created_at" },
      {
        label: "Đơn / giao dịch",
        render: (p) =>
          el(
            "div",
            {},
            p.code || "Chi phí online",
            el("small", {}, p.reference),
          ),
      },
      {
        label: "Loại",
        render: (p) =>
          ({
            ONLINE_PREPAY: "Thu QR đã đối chiếu",
            ONLINE_COD: "Thu COD khi giao",
            ONLINE_REFUND: "Hoàn tiền",
            ONLINE_EXPENSE: "Chi phí online",
          })[p.kind] || p.kind,
      },
      { label: "Phương thức", key: "method" },
      { label: "Số tiền", render: (p) => money(p.amount) },
      { label: "Người ghi", key: "actor" },
      { label: "Ghi chú", key: "online_note" },
    ]),
    el("h3", {}, "Tiền COD nhân viên cần bàn giao"),
    table(data.collectors, [
      { label: "Nhân viên thu", key: "name" },
      { label: "Đã thu", render: (c) => money(c.collected) },
      { label: "Đã nộp", render: (c) => money(c.handed_over) },
      { label: "Còn phải nộp", render: (c) => money(c.outstanding) },
      {
        label: "Xác nhận",
        render: (c) =>
          c.outstanding > 0
            ? button("Nhận bàn giao", () => handover(c), "small")
            : "Đủ",
      },
    ]),
    el("h3", {}, "Biên nhận bàn giao"),
    table(data.handovers, [
      { label: "Ngày", key: "created_at" },
      { label: "Người giao", key: "collector" },
      { label: "Người nhận", key: "receiver" },
      { label: "Số tiền", render: (h) => money(h.amount) },
      { label: "Biên nhận", key: "reference" },
    ]),
  );
}
export function responsibilityForm(data) {
  const current = data.settings;
  formModal(
    "Phân công phụ trách online",
    [
      {
        name: "online_cashier_id",
        label: "Thu ngân phụ trách đối chiếu tiền / thu chi",
        options: data.workers
          .filter((w) => w.role === "cashier")
          .map((w) => [w.id, w.name]),
        numeric: true,
        required: false,
      },
      {
        name: "online_dispatcher_id",
        label: "Nhân viên điều phối hàng / giao",
        options: data.workers.map((w) => [w.id, w.name]),
        numeric: true,
        required: false,
      },
    ],
    (d) => api("/shop/responsibilities", d),
    current,
  );
}
