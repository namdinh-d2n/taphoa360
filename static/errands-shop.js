import {
  el,
  button,
  panel,
  toolbar,
  money,
  field,
  closeModal,
} from "./ui.js?v=3.1";
import {
  form,
  spec,
  select,
  card,
  fillCard,
  renderDetail,
} from "./errands-view.js?v=2";
import { connectErrands } from "./errands-live.js?v=2";
export function mountErrands(root) {
  let live = null;
  const indicator = el(
    "span",
    { class: "errand-live", role: "status" },
    "Đang kết nối…",
  );
  let data = null,
    selected = null,
    user = null,
    loading = false,
    pending = false;
  document.getElementById("modal-close").onclick = closeModal;
  async function api(path = "", body, key) {
    const response = await fetch("/api/shop/errands" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": user?.csrf || "",
        ...(key ? { "Idempotency-Key": key } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });
    const result = await response.json();
    if (!response.ok)
      throw Error(
        typeof result.detail === "string"
          ? result.detail
          : "Không xử lí được yêu cầu.",
      );
    return result;
  }
  async function init() {
    const response = await fetch("/api/shop/me");
    if (!response.ok) {
      login();
      return;
    }
    user = await response.json();
    await refresh();
    live?.close();
    live = connectErrands("/api/shop/errands/events", refresh, (text) => {
      indicator.textContent = text;
    });
  }
  function login() {
    const phone = field(spec("phone", "Số điện thoại", "tel"));
    const password = field(
      spec("password", "Mật khẩu tài khoản khách", "password"),
    );
    const error = el("p", { class: "error", role: "alert" });
    const save = el(
      "button",
      { type: "submit", class: "primary" },
      "Đăng nhập để đi chợ hộ",
    );
    const node = el("form", {}, phone, password, error, save);
    node.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        const response = await fetch("/api/shop/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(Object.fromEntries(new FormData(node))),
        });
        const result = await response.json();
        if (!response.ok) throw Error(result.detail);
        await init();
      } catch (e) {
        error.textContent = e.message;
      } finally {
        save.disabled = false;
      }
    });
    root.replaceChildren(
      panel(
        "Dùng tài khoản khách hàng của bạn",
        node,
        el(
          "p",
          {},
          "Chưa có tài khoản? ",
          el("a", { href: "/shop" }, "Vào cửa hàng để đăng ký"),
        ),
      ),
    );
  }
  function createForm() {
    const requestKey = crypto.randomUUID();
    const lines = el("div");
    const rows = [];
    function add() {
      const specs = [
        spec("name", "Tên món"),
        spec("quantity", "Số lượng", "number", { step: "1", min: 1 }),
        spec("unit", "Đơn vị (kg, bó, hộp…)"),
        spec(
          "criteria",
          "Độ tươi, kích cỡ, thương hiệu, hạn dùng hoặc sơ chế",
          "textarea",
        ),
      ];
      const block = el("div", { class: "errand-line-form" });
      const grid = el(
        "div",
        { class: "form-grid" },
        specs.map((s) => field(s, s.name === "quantity" ? 1 : undefined)),
      );
      const row = { block, grid, specs };
      rows.push(row);
      block.append(
        grid,
        button("Bỏ dòng", () => {
          if (rows.length === 1) throw Error("Cần ít nhất một món");
          rows.splice(rows.indexOf(row), 1);
          block.remove();
        }),
      );
      lines.append(block);
    }
    add();
    const extra = el(
      "div",
      {},
      el("h3", {}, "Danh sách đi chợ"),
      lines,
      button("+ Thêm món", add),
      el(
        "p",
        { class: "hint" },
        "Ví dụ: cà chua 500 g, quả vừa chín, không dập; thịt nạc vai 300 g, ít mỡ, thái lát. Số lượng dùng số nguyên.",
      ),
      el(
        "p",
        {},
        `Phí mua hộ ${money(data.settings.service_fee)}; phí giao theo vùng. Cửa hàng gửi dự kiến để bạn duyệt, sau đó gửi bản chốt thực tế trước khi mua.`,
      ),
    );
    const specs = [
      spec("receiver", "Người nhận"),
      spec("phone", "Số điện thoại", "tel"),
      spec("address", "Địa chỉ giao", "textarea"),
      select("province_code", "Tỉnh/thành", [
        ["", "Chọn tỉnh/thành"],
        ...data.provinces.map((p) => [p.code, p.name]),
      ]),
      select("branch_id", "Cửa hàng phục vụ", [["", "Chọn tỉnh/thành trước"]]),
      select("payment_method", "Thanh toán", [
        ["TRANSFER", "Chuyển khoản qua QR"],
        ["CASH", "Tiền mặt khi nhận hàng"],
      ]),
      spec("delivery_window", "Khung giờ mong muốn"),
      spec("budget", "Ngân sách gồm hàng và các phí (đ)", "number"),
      spec(
        "preferences",
        "Yêu cầu chung; khi không liên lạc được thì xử lí thế nào?",
        "textarea",
      ),
    ];
    const requestForm = form(
      "Lên danh sách đi chợ",
      specs,
      {
        receiver: user.name,
        phone: user.phone,
        budget: 300000,
        preferences:
          "Phải hỏi trước khi thay hàng hoặc tăng tiền. Không liên lạc được thì chờ xác nhận, không tự mua.",
      },
      async (values) => {
        const items = rows.map((row) =>
          Object.fromEntries(
            [...row.grid.querySelectorAll("input,textarea")].map((input) => [
              input.name,
              input.name === "quantity" ? Number(input.value) : input.value,
            ]),
          ),
        );
        const order = await api(
          "",
          {
            ...values,
            province_code: Number(values.province_code),
            branch_id: Number(values.branch_id),
            items,
          },
          requestKey,
        );
        selected = order.id;
        await refresh();
      },
      extra,
    );
    const branchSelect = requestForm.elements.branch_id;
    const branchNote = el(
      "p",
      { class: "hint", role: "status" },
      "Các điểm phục vụ được bố trí để trải nghiệm demo. Chọn tỉnh/thành và cửa hàng trước khi gửi.",
    );
    branchSelect.closest("label").append(branchNote);
    requestForm.elements.province_code.addEventListener("change", () => {
      const branches = data.branches.filter(
        (b) =>
          String(b.province_code) === requestForm.elements.province_code.value,
      );
      branchSelect.replaceChildren(
        el("option", { value: "" }, "Chọn cửa hàng"),
        ...branches.map((b) =>
          el("option", { value: b.id }, b.name + " · " + money(b.fee)),
        ),
      );
      if (branches.length === 1) branchSelect.value = branches[0].id;
      branchSelect.dispatchEvent(new Event("change"));
    });
    branchSelect.addEventListener("change", () => {
      const branch = data.branches.find(
        (b) => String(b.id) === branchSelect.value,
      );
      branchNote.textContent = branch
        ? `${branch.address} · Phí giao ${money(branch.fee)} · Phí mua hộ ${money(data.settings.service_fee)}`
        : "Chọn cửa hàng để xem phí và điểm phục vụ demo.";
    });
  }
  async function action(order, name, body = {}, key) {
    const result = await api(
      `/${order.id}/${name}`,
      { ...body, version: order.version },
      key,
    );
    const i = data.orders.findIndex((o) => o.id === order.id);
    if (i >= 0) data.orders[i] = result;
    else data.orders.unshift(result);
    draw();
  }
  function draw() {
    const header = toolbar(
      button(
        "+ Tạo yêu cầu đi chợ",
        () => {
          if (!data.branches.length) throw Error("Tiệm chưa mở điểm phục vụ.");
          createForm();
        },
        "primary",
      ),
      indicator,
      el("span", { class: "muted" }, "Xin chào " + user.name),
    );
    const list = el("aside", { class: "errand-list" });
    const detail = el("div", { class: "errand-detail" });
    for (const o of data.orders) {
      const node = card(o, selected, (id) => {
        selected = id;
        draw();
      });
      fillCard(node, o);
      list.append(node);
    }
    if (!data.orders.length)
      list.append(
        el(
          "div",
          { class: "errand-empty" },
          el("h3", {}, "Bữa ngon bắt đầu từ danh sách"),
          el("p", {}, "Gửi nhu cầu; tiệm sẽ kiểm tra và báo giá cho bạn."),
        ),
      );
    const current = data.orders.find((o) => o.id === selected);
    if (current)
      renderDetail(detail, current, {
        staff: false,
        user,
        data,
        action,
        refresh,
      });
    else
      detail.append(
        panel(
          "Bạn chọn, tiệm đi chợ",
          el("p", {}, "1. Gửi danh sách và tiêu chí chọn hàng."),
          el("p", {}, "2. Duyệt mọi thay thế và tổng tiền trước khi mua."),
          el("p", {}, "3. Kiểm nhận, đối soát tiền và gửi phản hồi nếu cần."),
          el("p", { class: "hint" }, data.settings.policy),
        ),
      );
    root.replaceChildren(
      header,
      el("div", { class: "errand-layout" }, list, detail),
    );
  }
  async function refresh() {
    if (loading) {
      pending = true;
      return;
    }
    loading = true;
    try {
      do {
        pending = false;
        const next = await api();
        if (!data || JSON.stringify(next) !== JSON.stringify(data)) {
          data = next;
          if (!selected && data.orders.length) selected = data.orders[0].id;
          draw();
        }
      } while (pending);
    } finally {
      loading = false;
    }
  }
  init().catch((error) =>
    root.replaceChildren(
      panel(
        "Không tải được dịch vụ",
        el("p", { class: "error" }, error.message),
        button("Thử lại", init),
      ),
    ),
  );

  return { close: () => live?.close() };
}
if (document.body.classList.contains("errand-shop"))
  mountErrands(document.getElementById("errand-root"));
