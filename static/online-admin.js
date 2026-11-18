import {
  el,
  api,
  button,
  link,
  panel,
  toolbar,
  table,
  money,
  qty,
  tabs,
  replace,
  formModal,
  showModal,
  closeModal,
  refresh,
  toast,
  owner,
  state,
  field,
  readFields,
} from "./ui.js?v=3.1";
import {
  operationsBoard,
  financePanel,
  responsibilityForm,
  onlineStatus,
} from "./online-control.js?v=5.0";
let lastOnlineTab = "orders";
let onlineRefreshTimer = null;
const text = (name, label, extra = {}) => ({ name, label, ...extra });
const num = (name, label, value = 0, extra = {}) => ({
  name,
  label,
  type: "number",
  value,
  ...extra,
});
const select = (name, label, options, extra = {}) => ({
  name,
  label,
  options,
  ...extra,
});
const check = (name, label, value = true) => ({
  name,
  label,
  type: "checkbox",
  value,
});
const datetime = (name, label, required = true) => ({
  name,
  label,
  type: "datetime-local",
  required,
});
const statuses = {
  PENDING: "Chờ xác nhận",
  REVIEW: "Chờ khách duyệt",
  CONFIRMED: "Đã giữ hàng",
  SHIPPING: "Đang giao",
  COMPLETED: "Đã kiểm nhận",
  CANCELLED: "Đã hủy",
  EXPIRED: "Hết thời gian chờ",
};
async function upload(file) {
  const data = new FormData();
  data.append("image", file);
  const response = await fetch("/api/v1/shop/upload", {
    method: "POST",
    headers: { "X-CSRF-Token": state.user.csrf },
    body: data,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail);
  return result.path;
}
function imageUpload(label, onDone) {
  const input = el("input", {
    type: "file",
    accept: "image/png,image/jpeg,image/webp",
    ariaLabel: label,
  });
  input.addEventListener("change", async () => {
    if (!input.files[0]) return;
    input.disabled = true;
    try {
      await onDone(await upload(input.files[0]));
      toast("Đã tải ảnh");
      await refresh();
    } catch (error) {
      toast(error.message);
    } finally {
      input.disabled = false;
    }
  });
  return el("label", {}, label, input);
}
function orderDetails(order, data) {
  const body = el(
    "div",
    {},
    el("p", {}, order.receiver + " · " + order.phone),
    el("p", {}, order.address),
    el(
      "p",
      { class: "notice" },
      "Xử lý hết món: " +
        {
          CALL: "Gọi trước khi thay",
          DROP: "Đề nghị bỏ món hết",
          CONTACT: "Liên hệ lại",
        }[order.substitution] +
        " · " +
        order.note,
    ),
    el(
      "p",
      {},
      "Tổng " +
        money(order.total) +
        " · đã thu " +
        money(order.paid) +
        " · cần hoàn " +
        money(order.refund_due) +
        " · đã hoàn " +
        money(order.refund_paid),
    ),
    table(order.items, [
      { label: "Món", key: "product_name" },
      { label: "SL", key: "quantity" },
      { label: "Đơn vị", key: "unit" },
      { label: "Tiền trước đổi điểm", render: (i) => money(i.total) },
      { label: "Thực nhận", render: (i) => i.accepted ?? "Chưa kiểm" },
    ]),
  );
  const actions = toolbar();
  const permissions = data.permissions || {};
  if (
    order.payment_flow === "PREPAY" &&
    order.payment_status === "REPORTED" &&
    permissions.money
  ) {
    actions.append(
      button(
        "Đối chiếu & duyệt thanh toán",
        () =>
          formModal(
            "Duyệt tiền thực nhận · " + order.code,
            [
              num("amount", "Số tiền đã vào ngân hàng", order.total),
              text("reference", "Mã giao dịch ngân hàng đã đối chiếu"),
              ...(permissions.dispatch
                ? [
                    select(
                      "picker_id",
                      "Phân công soạn hàng",
                      data.workers.map((p) => [p.id, p.name]),
                      { numeric: true, required: false },
                    ),
                    select(
                      "shipper_id",
                      "Dự kiến nhân viên giao",
                      data.shippers.map((p) => [p.id, p.name]),
                      { numeric: true, required: false },
                    ),
                  ]
                : []),
            ],
            (d) => api("/shop/orders/" + order.id + "/paid", d),
          ),
        "primary",
      ),
      button("Chưa xác minh được tiền", () =>
        formModal(
          "Yêu cầu khách kiểm tra lại",
          [text("reason", "Lý do chưa xác minh được")],
          (d) => api("/shop/orders/" + order.id + "/reject-payment", d),
        ),
      ),
    );
  }
  if (order.payment_reported_at)
    body.prepend(
      el(
        "p",
        { class: "notice" },
        "Khách báo chuyển lúc " +
          order.payment_reported_at +
          " · " +
          (order.payment_note || "Chưa có ghi chú thêm"),
      ),
    );
  if (order.invoice)
    actions.append(
      el(
        "a",
        {
          href: "/online/invoices/" + order.id,
          target: "_blank",
          rel: "noopener",
          class: "button",
        },
        "Mở / in hóa đơn " + order.invoice.code,
      ),
    );
  if (
    order.status === "CONFIRMED" &&
    (permissions.dispatch || order.picker_id === state.user.id)
  )
    actions.append(
      button("Soạn hàng & phân công", () => {
        const fields = [
          ...(permissions.dispatch
            ? [
                select(
                  "picker_id",
                  "Người soạn",
                  data.workers.map((p) => [p.id, p.name]),
                  { numeric: true, required: false },
                ),
              ]
            : []),
          ...order.items.map((i) =>
            check(
              "pick_" + i.id,
              "Đã soạn " + i.quantity + " " + i.unit + " " + i.product_name,
              !!i.is_picked,
            ),
          ),
        ];
        formModal(
          "Chuẩn bị giao " + order.code,
          fields,
          (d) =>
            api("/shop/orders/" + order.id + "/prepare", {
              ...(d.picker_id ? { picker_id: d.picker_id } : {}),
              items: order.items.map((i) => ({
                item_id: i.id,
                picked: d["pick_" + i.id],
              })),
            }),
          { picker_id: order.picker_id },
        );
      }),
    );
  const operation = (name, action, payload) =>
    button(
      name,
      async () => {
        await api("/shop/orders/" + order.id + "/" + action, payload || {});
        closeModal();
        toast("Đã cập nhật đơn");
        await refresh();
      },
      "small",
    );
  if (
    ["PENDING", "REVIEW"].includes(order.status) &&
    order.payment_flow !== "PREPAY" &&
    permissions.dispatch
  ) {
    actions.append(operation("Xác nhận & giữ hàng", "confirm"));
    actions.append(
      button("Đề nghị sửa / thay món", () => proposeForm(order, data)),
    );
  }
  if (order.status === "CONFIRMED") {
    if (
      order.payment_method === "QR" &&
      !order.paid &&
      ["owner", "cashier"].includes(state.user.role)
    )
      actions.append(
        button("Đối chiếu tiền QR", () =>
          formModal(
            "Xác nhận tiền đã vào ngân hàng",
            [
              num("amount", "Số tiền", order.total),
              text("reference", "Mã giao dịch ngân hàng"),
            ],
            (d) => api("/shop/orders/" + order.id + "/paid", d),
          ),
        ),
      );
    if (permissions.dispatch)
      actions.append(
        button("Phân công & bắt đầu giao", () =>
          formModal(
            "Giao đơn " + order.code,
            [
              select(
                "shipper_id",
                "Nhân viên giao",
                data.shippers.map((s) => [s.id, s.name]),
                { numeric: true },
              ),
            ],
            (d) => api("/shop/orders/" + order.id + "/ship", d),
          ),
        ),
      );
  }
  if (order.status === "SHIPPING")
    actions.append(
      button(
        "Kiểm hàng khi giao / thực thu",
        () => deliveryForm(order),
        "primary",
      ),
    );
  if (
    ["PENDING", "REVIEW", "PAYMENT_REVIEW", "CONFIRMED"].includes(
      order.status,
    ) &&
    permissions.dispatch
  )
    actions.append(
      button("Hủy đơn", () =>
        formModal("Hủy " + order.code, [text("reason", "Lý do hủy")], (d) =>
          api("/shop/orders/" + order.id + "/cancel", d),
        ),
      ),
    );
  if (order.refund_due > order.refund_paid && permissions.money)
    actions.append(
      button("Xác nhận đã hoàn tiền", () =>
        formModal(
          "Hoàn tiền sau kiểm nhận",
          [
            num("amount", "Số tiền", order.refund_due - order.refund_paid),
            select("method", "Hoàn bằng", [
              ["TRANSFER", "Chuyển khoản"],
              ["CASH", "Tiền mặt"],
            ]),
            text("reference", "Mã giao dịch / biên nhận hoàn"),
          ],
          (d) => api("/shop/orders/" + order.id + "/refund", d),
        ),
      ),
    );
  body.append(
    actions,
    el(
      "ol",
      {},
      order.events.map((e) => el("li", {}, e.created_at + " · " + e.note)),
    ),
  );
  showModal(order.code + " · " + onlineStatus(order), body);
}
function proposeForm(order, data) {
  const form = el("form");
  const lines = order.items.map((item) => {
    const p = el(
      "select",
      { ariaLabel: "Thay món " + item.product_name },
      data.products
        .filter((p) => p.active && p.online_enabled)
        .map((p) => el("option", { value: p.id }, p.product_name)),
    );
    p.value = item.product_id;
    const q = el("input", {
      type: "number",
      min: 0,
      step: 1,
      value: item.quantity,
      required: true,
      ariaLabel: "Số lượng " + item.product_name,
    });
    form.append(
      el(
        "div",
        { class: "form-grid form-section" },
        el("label", {}, "Sản phẩm", p),
        el("label", {}, "SL mới (0 để bỏ)", q),
      ),
    );
    return { p, q };
  });
  const reason = el("input", {
    required: true,
    name: "reason",
    maxLength: 400,
  });
  const error = el("p", { class: "error", role: "alert" });
  const save = el(
    "button",
    { type: "submit", class: "primary" },
    "Gửi phương án cho khách duyệt",
  );
  form.append(
    el(
      "p",
      { class: "hint" },
      "Phương án mới chưa giữ hàng. Khách phải đồng ý trên Đơn của tôi trước khi tiệm xác nhận; điểm giữ của phương án cũ được trả lại.",
    ),
    el("label", {}, "Lý do / ghi chú đã liên hệ", reason),
    error,
    el("div", { class: "form-actions" }, save),
  );
  form.onsubmit = async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const items = lines
        .filter((l) => Number(l.q.value) > 0)
        .map((l) => ({
          product_id: Number(l.p.value),
          quantity: Number(l.q.value),
        }));
      await api("/shop/orders/" + order.id + "/propose", {
        items,
        reason: reason.value,
      });
      closeModal();
      await refresh();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  };
  showModal("Điều chỉnh đơn thiếu hàng", form);
}
function deliveryForm(order) {
  const form = el("form");
  const total = el("p", { class: "notice", role: "status" });
  const lines = order.items.map((item) => {
    const count = el("input", {
      type: "number",
      min: 0,
      max: item.quantity,
      step: 1,
      value: item.quantity,
      required: true,
      ariaLabel: "Thực nhận " + item.product_name,
    });
    const handling = el(
      "select",
      {},
      [
        ["QUARANTINE", "Cách ly kiểm tra"],
        ["DAMAGE", "Loại bỏ / hỏng"],
        ...(["FRESH", "FROZEN", "CHILLED"].includes(item.storage_kind)
          ? []
          : [["RESTOCK", "Hàng khô nguyên vẹn, trả lại kho"]]),
      ].map(([v, t]) => el("option", { value: v }, t)),
    );
    form.append(
      el(
        "div",
        { class: "form-section" },
        el(
          "h3",
          {},
          item.product_name + " · đã giao " + item.quantity + " " + item.unit,
        ),
        el(
          "div",
          { class: "form-grid" },
          el("label", {}, "Số lượng khách thực nhận", count),
          el("label", {}, "Xử lý phần từ chối", handling),
        ),
      ),
    );
    return { item, count, handling };
  });
  const fields = [
    text("reason", "Lý do từ chối / biên bản kiểm hàng", {
      required: false,
      maxLength: 500,
    }),
    num(
      "collected",
      "Tiền COD thực thu",
      order.payment_method === "COD" ? order.total : 0,
    ),
  ];
  fields.forEach((f) => form.append(field(f)));
  const collected = form.elements.collected;
  if (order.payment_method === "QR") collected.closest("label").hidden = true;
  function due() {
    let goods = 0,
      received = 0;
    for (const l of lines) {
      const n = Number(l.count.value);
      const base = Math.round((l.item.total * n) / l.item.quantity);
      const points = Math.min(
        Math.floor((l.item.points_part * n) / l.item.quantity),
        Math.floor(base / 100),
      );
      goods += base - points * 100;
      received += n;
    }
    return goods + (received ? order.shipping_fee : 0);
  }
  function update() {
    const amount = due();
    if (order.payment_method === "COD") collected.value = amount;
    total.textContent =
      "Khách nhận: " +
      money(amount) +
      (order.payment_method === "QR"
        ? " · Cần hoàn: " + money(Math.max(0, order.paid - amount))
        : " · COD chỉ thu đúng số này.");
  }
  lines.forEach((l) => (l.count.oninput = update));
  const error = el("p", { class: "error", role: "alert" });
  const save = el(
    "button",
    { type: "submit", class: "primary" },
    "Xác nhận kiểm nhận & tiền thực tế",
  );
  form.append(
    total,
    el(
      "p",
      { class: "hint" },
      "Điểm cộng theo hàng thực nhận. Hàng tươi/lạnh từ chối được cách ly kiểm tra; hoàn QR chỉ đánh dấu đã hoàn sau khi đối chiếu giao dịch.",
    ),
    error,
    el("div", { class: "form-actions" }, save),
  );
  form.onsubmit = async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      await api("/shop/orders/" + order.id + "/deliver", {
        ...readFields(form, fields),
        items: lines.map((l) => ({
          item_id: l.item.id,
          accepted: Number(l.count.value),
          handling: l.handling.value,
        })),
      });
      closeModal();
      toast("Đã ghi nhận kiểm hàng và khoản cần hoàn");
      await refresh();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  };
  update();
  showModal("Khách kiểm hàng · " + order.code, form);
}
export async function renderOnline(content) {
  if (!onlineRefreshTimer)
    onlineRefreshTimer = setInterval(() => {
      if (
        !document.hidden &&
        !document.getElementById("modal").open &&
        !document.activeElement?.matches("input,select,textarea")
      )
        refresh();
    }, 15000);
  const data = await api("/shop/overview");
  let current = lastOnlineTab;
  const nav = el("div"),
    body = el("div");
  const isShipper = state.user.role === "shipper";
  const canInventory = ["owner", "inventory"].includes(state.user.role);
  async function draw(tab) {
    current = tab;
    lastOnlineTab = tab;
    replace(
      nav,
      tabs(
        [
          ["orders", "Đơn online"],
          ...(data.permissions.money ? [["finance", "Thu – chi online"]] : []),
          ...(canInventory
            ? [
                ["products", "Ảnh & danh mục"],
                ["fresh", "Hàng cuối ngày"],
              ]
            : []),
          ...(owner()
            ? [
                ["sales", "Giờ sale vàng"],
                ["banners", "Quảng cáo"],
                ["settings", "Giao hàng & QR"],
              ]
            : []),
        ],
        tab,
        draw,
      ),
    );
    replace(body);
    if (tab === "finance") body.append(await financePanel());
    if (tab === "orders") {
      body.append(operationsBoard(data, orderDetails));
      if (owner())
        body.append(
          toolbar(
            button("Phân công người phụ trách online", () =>
              responsibilityForm(data),
            ),
          ),
        );
    }
    if (tab === "products") {
      body.append(
        panel(
          "Ảnh và danh mục hàng bán online",
          toolbar(link("Thêm / sửa sản phẩm", "/products")),
          el(
            "p",
            { class: "hint" },
            "Các SKU REF-BHX là danh mục tham khảo có nguồn giá/ảnh. Giá nhập và NCC mẫu cần sửa theo báo giá thật; nhập kho qua phiếu nhập để có tồn bán được.",
          ),
          table(data.products, [
            { label: "Sản phẩm", key: "product_name" },
            { label: "Danh mục", key: "category" },
            { label: "Loại bảo quản", key: "storage_kind" },
            {
              label: "Online",
              render: (p) => (p.online_enabled ? "Đang mở" : "Đang tắt"),
            },
            {
              label: "Ảnh",
              render: (p) =>
                el(
                  "div",
                  {},
                  p.image_path
                    ? el("img", {
                        src: p.image_path,
                        alt: p.product_name,
                        width: 70,
                        height: 70,
                        style: "object-fit:contain",
                      })
                    : null,
                  imageUpload("Chọn ảnh " + p.product_name, async (path) =>
                    api("/shop/products/" + p.id + "/image", { path }),
                  ),
                ),
            },
          ]),
        ),
      );
    }
    if (tab === "settings") {
      const s = data.settings;
      const settingsFields = [
        text("store_name", "Tên tiệm"),
        text("delivery_note", "Thông báo giờ giao", { required: false }),
        text("bank_bin", "BIN ngân hàng (6 số)", { required: false }),
        text("bank_account", "Số tài khoản nhận", { required: false }),
        text("bank_name", "Tên chủ tài khoản / ngân hàng", { required: false }),
        check("accepting_orders", "Đang nhận đơn online"),
      ];
      body.append(
        panel(
          "Cấu hình cửa hàng",
          toolbar(
            button("Sửa thông tin / QR", () =>
              formModal(
                "Cửa hàng & ngân hàng nhận",
                settingsFields,
                (d) => api("/shop/settings", d),
                s,
              ),
            ),
          ),
          el("p", {}, s.store_name + " · " + s.delivery_note),
          el(
            "p",
            { class: "hint" },
            "QR được sinh cục bộ theo số tiền và mã đơn. Nhân viên luôn đối chiếu giao dịch trước khi xác nhận đã nhận tiền. Số điện thoại khách dùng mật khẩu, chưa có OTP/SMS.",
          ),
        ),
      );
      function editZone(z = {}) {
        formModal(
          z.id ? "Sửa vùng giao" : "Thêm vùng giao",
          [
            text("name", "Khu / phường / chung cư"),
            num("fee", "Phí giao"),
            num("minimum_order", "Đơn tối thiểu"),
            text("eta", "Khung giờ / thời gian dự kiến", { required: false }),
            check("active", "Đang phục vụ"),
          ],
          (d) => api("/shop/zones", { ...d, ...(z.id ? { id: z.id } : {}) }),
          z,
        );
      }
      body.append(
        panel(
          "Vùng giao do tiệm phục vụ",
          toolbar(button("+ Thêm vùng", () => editZone(), "primary")),
          table(data.zones, [
            { label: "Khu", key: "name" },
            { label: "Phí", render: (z) => money(z.fee) },
            { label: "Tối thiểu", render: (z) => money(z.minimum_order) },
            { label: "Dự kiến", key: "eta" },
            { label: "Mở", render: (z) => (z.active ? "Có" : "Không") },
            {
              label: "",
              render: (z) => button("Sửa", () => editZone(z), "small"),
            },
          ]),
        ),
      );
    }
    if (tab === "banners") {
      function editBanner(b = {}) {
        const specs = [
          text("title", "Tiêu đề"),
          text("subtitle", "Nội dung", { required: false, maxLength: 250 }),
          select("theme", "Bảng màu", [
            ["GREEN", "Xanh tiệm"],
            ["ORANGE", "Cam / vàng sale"],
            ["BLUE", "Xanh giao nhanh"],
          ]),
          text("image_path", "Ảnh đã tải lên (tùy chọn)", {
            required: false,
            value: b.image_path || "",
          }),
          text("category", "Danh mục mở khi bấm", { required: false }),
          datetime("starts_at", "Bắt đầu hiển thị", false),
          datetime("ends_at", "Ngừng hiển thị", false),
          num("position", "Thứ tự"),
          check("active", "Đang bật"),
        ];
        const form = formModal(
          b.id ? "Sửa quảng cáo" : "Thêm quảng cáo",
          specs,
          (d) => api("/shop/banners", { ...d, ...(b.id ? { id: b.id } : {}) }),
          b,
        );
        form.prepend(
          imageUpload("Ảnh banner (JPG/PNG/WebP)", (path) => {
            form.elements.image_path.value = path;
          }),
        );
      }
      body.append(
        panel(
          "Quảng cáo bắt mắt theo thời gian",
          toolbar(button("+ Quảng cáo", () => editBanner(), "primary")),
          el(
            "p",
            { class: "hint" },
            "Dùng ảnh của tiệm hoặc nền màu có sẵn. Nội dung ưu đãi cần khớp khung sale thật; banner tự hiện/ẩn theo thời gian đã đặt.",
          ),
          table(data.banners, [
            { label: "Tiêu đề", key: "title" },
            { label: "Nội dung", key: "subtitle" },
            { label: "Từ", key: "starts_at" },
            { label: "Đến", key: "ends_at" },
            {
              label: "",
              render: (b) => button("Sửa", () => editBanner(b), "small"),
            },
          ]),
        ),
      );
    }
    if (tab === "sales") {
      const specs = [
        text("name", "Tên chương trình"),
        select(
          "product_id",
          "Sản phẩm",
          data.products
            .filter((p) => p.active)
            .map((p) => [p.id, p.product_name]),
          { numeric: true },
        ),
        num("price", "Giá sale"),
        num("max_units", "Giới hạn số đơn vị", 1, { min: 1 }),
        datetime("starts_at", "Bắt đầu (giờ Việt Nam)"),
        datetime("ends_at", "Kết thúc (giờ Việt Nam)"),
      ];
      body.append(
        panel(
          "Giờ sale vàng",
          toolbar(
            button(
              "+ Lên lịch sale",
              () =>
                formModal("Sale theo giờ", specs, (d) => api("/shop/sales", d)),
              "primary",
            ),
          ),
          el(
            "p",
            { class: "hint" },
            "Giá online áp dụng đúng khung giờ, số lượng được kiểm tra khi tiệm giữ hàng. Không cộng sale giờ với combo dùng sớm; bảng POS giữ giá vận hành riêng.",
          ),
          table(data.sales, [
            { label: "Sale", key: "name" },
            { label: "Món", key: "product_name" },
            { label: "Giá", render: (s) => money(s.price) },
            { label: "Tối đa", key: "max_units" },
            { label: "Từ", key: "starts_at" },
            { label: "Đến", key: "ends_at" },
            {
              label: "",
              render: (s) =>
                button(
                  s.active ? "Tắt" : "Bật",
                  async () => {
                    await api("/shop/sales", { id: s.id, active: !s.active });
                    await refresh();
                  },
                  "small",
                ),
            },
          ]),
        ),
      );
    }
    if (tab === "fresh") {
      const batches = await api("/shop/perishables");
      function quality(b) {
        formModal(
          "Kiểm tra lô " + b.lot_code,
          [
            select("quality_status", "Kết luận kiểm tra", [
              ["HOLD", "Cách ly / chờ kiểm tra"],
              ["SELLABLE", "Đủ điều kiện bán"],
              ["DISPOSED", "Loại bỏ toàn bộ tồn lô"],
            ]),
            datetime("sell_until", "Giờ ngừng bán", false),
            text("reason", "Lý do / biên bản kiểm tra"),
          ],
          (d) => api("/shop/batches/" + b.id + "/quality", d),
          b,
        );
      }
      function saleBatch(b) {
        formModal(
          "Sale cuối ngày · " + b.product_name,
          [
            text("name", "Tên chương trình", {
              value: "Ngon hôm nay · " + b.product_name,
            }),
            num("price", "Giá sale", Math.round(b.price * 0.8)),
            num("max_units", "Giới hạn số lượng", Math.floor(b.remaining), {
              min: 1,
            }),
            datetime("starts_at", "Bắt đầu (giờ Việt Nam)"),
            datetime("ends_at", "Kết thúc (trước giờ ngừng bán)"),
          ],
          (d) =>
            api("/shop/sales", {
              ...d,
              product_id: b.product_id,
              batch_id: b.id,
            }),
        );
      }
      body.append(
        panel(
          "Hàng tươi, lạnh và cuối ngày",
          el(
            "p",
            { class: "hint" },
            "Kiểm tra thực tế → đặt giờ ngừng bán → lên sale hợp lệ hoặc cách ly/loại bỏ. Giờ ngừng bán áp dụng cả POS và online; không tự kéo dài hạn dùng. Hàng tươi/lạnh khách trả được cách ly để kiểm tra.",
          ),
          table(batches, [
            {
              label: "Hàng / lô",
              render: (b) => b.product_name + " · " + b.lot_code,
            },
            { label: "Loại", key: "storage_kind" },
            { label: "Còn", render: (b) => qty(b.remaining) + " " + b.unit },
            { label: "HSD", key: "expires_on" },
            { label: "Ngừng bán", key: "sell_until" },
            { label: "Chất lượng", key: "quality_status" },
            {
              label: "Xử lý",
              render: (b) =>
                toolbar(
                  button("Kiểm tra / ngừng bán", () => quality(b), "small"),
                  owner()
                    ? button("Sale cuối ngày", () => saleBatch(b), "small")
                    : null,
                ),
            },
          ]),
        ),
      );
    }
  }
  replace(
    content,
    toolbar(
      link("Mở cửa hàng online", "/shop", "button primary"),
      link("Quản lý hàng hóa", "/products"),
    ),
    nav,
    body,
  );
  await draw(current);
}
