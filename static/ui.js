export const state = { user: null, page: document.body.dataset.page };
let refresher = async () => {},
  timer;
export const setRefresh = (fn) => {
  refresher = fn;
};
export const refresh = () => refresher();
export const money = (value) =>
  new Intl.NumberFormat("vi-VN").format(Math.round(value || 0)) + " đ";
export const qty = (value) =>
  new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 3 }).format(
    value || 0,
  );
export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export const owner = () => state.user?.role === "owner";
export const can = (...roles) => owner() || roles.includes(state.user?.role);
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k in node && !["list", "form", "style"].includes(k)) node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null) continue;
    node.append(
      child instanceof Node ? child : document.createTextNode(String(child)),
    );
  }
  return node;
}
export async function api(path, data, method, headers = {}) {
  let res;
  try {
    res = await fetch(path.startsWith("/api/") ? path : "/api/v1" + path, {
    method: method || (data === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": state.user?.csrf || "",
      ...headers,
    },
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(30000),
    });
  } catch (error) {
    throw new Error(error.name === "TimeoutError"
      ? "Máy chủ phản hồi chậm. Hãy kiểm tra kết quả trước khi thử lại thao tác."
      : "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
  }
  let result;
  try {
    result = await res.json();
  } catch {
    throw new Error(res.status >= 500 ? "Máy chủ tạm thời không sẵn sàng. Vui lòng thử lại." : "Không đọc được phản hồi của máy chủ");
  }
  if (res.status === 401) {
    location.href = state.user ? "/login/" + state.user.role : "/login";
    throw new Error("Phiên đăng nhập đã kết thúc");
  }
  if (!res.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail || result),
    );
  return result;
}
export function toast(message) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.classList.add("show");
  clearTimeout(timer);
  timer = setTimeout(() => box.classList.remove("show"), 4500);
}
export function button(label, fn, cls = "") {
  const b = el("button", { type: "button", class: cls }, label);
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await fn();
    } catch (err) {
      toast(err.message);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}
export const link = (label, href, cls = "button") =>
  el("a", { href, class: cls }, label);
export const toolbar = (...children) =>
  el("div", { class: "toolbar" }, children);
export function panel(title, ...children) {
  return el(
    "section",
    { class: "panel" },
    title ? el("div", { class: "panel-head" }, el("h2", {}, title)) : null,
    children,
  );
}
export function metric(label, value, note = "", featured = false) {
  return el(
    "div",
    { class: "metric" + (featured ? " featured" : "") },
    el("div", { class: "metric-label" }, label),
    el("strong", {}, value),
    el("small", {}, note),
  );
}
const labels = {
  PENDING: "Chờ xác nhận",
  PROCESSING: "Đang soạn",
  SHIPPING: "Đang giao",
  COMPLETED: "Hoàn tất",
  CANCELLED: "Đã hủy",
  PARTIAL_RETURN: "Trả một phần",
  RETURNED: "Đã trả hết",
  APPROVED: "Đã duyệt",
  REJECTED: "Từ chối",
  DRAFT: "Bản nháp",
  ACTIVE: "Đang làm",
  INACTIVE: "Đã nghỉ",
  DUNG_GIO: "Đúng giờ",
  DI_TRE: "Đi trễ",
  VANG: "Vắng",
  ABSENT: "Chưa chấm",
  CASH: "Tiền mặt",
  TRANSFER: "Chuyển khoản",
  DEBT: "Công nợ",
  SALE: "Bán hàng",
  PURCHASE: "Nhập hàng",
  COUNT: "Kiểm kê",
  OPENING: "Tồn đầu",
  RETURN: "Trả hàng",
  CANCEL: "Hủy đơn",
  REFUND: "Hoàn tiền",
  MONTHLY: "Theo tháng",
  HOURLY: "Theo giờ",
  LEAVE: "Xin nghỉ",
  SWAP: "Đổi ca",
  owner: "Chủ tiệm",
  cashier: "Thu ngân",
  inventory: "Kiểm kho",
  shipper: "Giao hàng",
};
export const label = (value) => labels[value] || value || "—";
export function badge(value) {
  return el(
    "span",
    {
      class:
        "badge" +
        (["PENDING", "PROCESSING", "DRAFT", "DI_TRE"].includes(value)
          ? " warn"
          : ["CANCELLED", "REJECTED", "VANG", "RETURNED"].includes(value)
            ? " red"
            : ""),
    },
    label(value),
  );
}
export function table(data, columns) {
  if (!data.length)
    return el("div", { class: "empty" }, "Chưa có dữ liệu phù hợp.");
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      {},
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          columns.map((c) => el("th", {}, c.label)),
        ),
      ),
      el(
        "tbody",
        {},
        data.map((row) =>
          el(
            "tr",
            {},
            columns.map((c) =>
              el("td", {}, c.render ? c.render(row) : (row[c.key] ?? "—")),
            ),
          ),
        ),
      ),
    ),
  );
}
export const actions = (...buttons) => el("div", { class: "actions" }, buttons);
export function showModal(title, body) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-content").replaceChildren(body);
  const modal = document.getElementById("modal");
  if (!modal.open) modal.showModal();
}
export const closeModal = () => document.getElementById("modal").close();
export function field(spec, value) {
  let input;
  if (spec.options) {
    input = el(
      "select",
      { name: spec.name, required: spec.required !== false },
      spec.required === false
        ? el("option", { value: "" }, "— Không chọn —")
        : null,
      spec.options.map((o) => el("option", { value: o[0] }, o[1])),
    );
  } else if (spec.type === "textarea") {
    input = el("textarea", {
      name: spec.name,
      required: spec.required !== false,
      maxLength: spec.maxLength || 500,
    });
  } else {
    input = el("input", {
      name: spec.name,
      type: spec.type || "text",
      required: spec.required !== false,
      min: spec.min ?? (spec.type === "number" ? 0 : null),
      max: spec.max,
      step: spec.step || (spec.type === "number" ? "1" : null),
      maxLength: spec.maxLength || 200,
      placeholder: spec.placeholder || "",
    });
  }
  if (spec.type === "checkbox") {
    input.required = false;
    input.checked = Boolean(value ?? spec.value);
  } else if (value != null || spec.value != null)
    input.value = value ?? spec.value;
  return el(
    "label",
    { class: spec.full ? "full" : "" },
    spec.label,
    input,
    spec.hint ? el("small", {}, spec.hint) : null,
  );
}
export function readFields(form, fields) {
  const result = {};
  for (const f of fields) {
    const input = form.elements.namedItem(f.name);
    result[f.name] =
      f.type === "checkbox"
        ? input.checked
        : f.type === "number"
          ? input.value === ""
            ? null
            : Number(input.value)
          : input.value;
    if (f.options && f.numeric)
      result[f.name] = input.value === "" ? null : Number(input.value);
  }
  return result;
}
export function formModal(title, fields, submit, initial = {}) {
  const error = el("p", { class: "error", role: "alert" });
  const form = el(
    "form",
    {},
    el(
      "div",
      { class: "form-grid" },
      fields.map((f) => field(f, initial[f.name])),
    ),
    error,
  );
  const save = el(
    "button",
    { type: "submit", class: "primary" },
    "Lưu thay đổi",
  );
  form.append(
    el("div", { class: "form-actions" }, button("Hủy", closeModal), save),
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    error.textContent = "";
    try {
      await submit(readFields(form, fields));
      closeModal();
      toast("Đã lưu thành công");
      await refresh();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  });
  showModal(title, form);
  return form;
}
export function confirmAction(title, message, fn) {
  showModal(
    title,
    el(
      "div",
      {},
      el("p", { class: "muted" }, message),
      el(
        "div",
        { class: "form-actions" },
        button("Quay lại", closeModal),
        button(
          "Xác nhận",
          async () => {
            await fn();
            closeModal();
            toast("Đã hoàn tất");
            await refresh();
          },
          "primary",
        ),
      ),
    ),
  );
}
export function csv(name, data, columns) {
  const escape = (v) =>
    '"' +
    String(v ?? "")
      .replaceAll('"', '""')
      .replace(/^([=+@-])/, "'$1") +
    '"';
  const text =
    "\ufeff" +
    [
      columns.map((c) => escape(c.label)).join(","),
      ...data.map((r) => columns.map((c) => escape(r[c.key])).join(",")),
    ].join("\r\n");
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/csv;charset=utf-8" }),
  );
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function tabs(names, current, change) {
  return el(
    "div",
    { class: "tabs" },
    names.map(([id, text]) =>
      button(text, () => change(id), id === current ? "active" : ""),
    ),
  );
}

export const replace = (node, ...children) =>
  node.replaceChildren(
    ...children
      .flat(Infinity)
      .filter((child) => child !== null && child !== undefined),
  );
