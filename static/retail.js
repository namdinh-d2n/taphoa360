import { state, api, el, setRefresh, label, can, toast } from "./ui.js?v=3.1";
import { navIcon } from "./icons.js?v=3.1";
import { renderPOS } from "./pos.js?v=3.1";
import {
  renderProducts,
  renderInventory,
  renderParties,
  renderOrders,
  renderCash,
  renderMap,
  renderSuggestions,
  renderDashboard,
  renderReports,
} from "./operations.js?v=3.1";
import { renderHR, renderSettings } from "./people.js?v=3.1";
import {
  renderOwner,
  renderCashier,
  renderStockroom,
  renderDelivery,
} from "./workspaces.js?v=3.1";

const pages = {
  owner_portal: [
    "Quản lý cửa hàng",
    "Chủ tiệm quản lý tất cả hoạt động và các khu làm việc.",
    "/owner",
    "◈",
    [],
    renderOwner,
  ],
  cashier_portal: [
    "Khu thu ngân",
    "Bán hàng, thanh toán và quản lý ca của bạn.",
    "/cashier",
    "▦",
    ["cashier"],
    renderCashier,
  ],
  inventory_portal: [
    "Khu kiểm kho",
    "Nhập hàng, kiểm kê và chuẩn bị đơn giao.",
    "/inventory",
    "▣",
    ["inventory"],
    renderStockroom,
  ],
  shipper_portal: [
    "Khu giao hàng",
    "Nhận hàng, xem địa chỉ và hoàn tất đơn được phân công.",
    "/shipper",
    "⇢",
    ["shipper"],
    renderDelivery,
  ],
  pos: [
    "Bán hàng",
    "Quét mã, chọn hàng và hoàn tất thanh toán.",
    "/pos",
    "▦",
    ["cashier"],
    renderPOS,
  ],
  orders: [
    "Đơn hàng",
    "Theo dõi từ lúc tạo đơn đến khi giao và đổi trả.",
    "/orders",
    "▤",
    ["cashier", "inventory", "shipper"],
    renderOrders,
  ],
  products: [
    "Sản phẩm",
    "Danh mục, giá bán và vị trí hàng hóa.",
    "/products",
    "◇",
    ["cashier", "inventory"],
    renderProducts,
  ],
  inventory: [
    "Kho hàng",
    "Nhập theo lô, kiểm kê và theo dõi mọi thay đổi tồn.",
    "/warehouse",
    "▣",
    ["inventory"],
    renderInventory,
  ],
  map: [
    "Sơ đồ kệ",
    "Tìm sản phẩm theo khu, kệ và vị trí thực tế.",
    "/store_map",
    "⌖",
    ["inventory", "cashier"],
    renderMap,
  ],
  customers: [
    "Khách hàng",
    "Lịch sử mua hàng, điểm thưởng và công nợ.",
    "/customers",
    "♧",
    ["cashier"],
    (c) => renderParties(c, "CUSTOMER"),
  ],
  suppliers: [
    "Nhà cung cấp",
    "Thông tin đối tác và đối chiếu công nợ nhập hàng.",
    "/suppliers",
    "⇄",
    ["inventory"],
    (c) => renderParties(c, "SUPPLIER"),
  ],
  cash: [
    "Ca thu ngân",
    "Tiền đầu ca, thu chi và đối chiếu cuối ca.",
    "/cash",
    "▧",
    ["cashier", "inventory"],
    renderCash,
  ],
  hr: [
    "Nhân sự",
    "Lịch làm việc, chấm công và thu nhập của đội ngũ.",
    "/hr",
    "♙",
    null,
    renderHR,
  ],
  reports: [
    "Báo cáo",
    "Doanh số, giá vốn và hiệu quả vận hành.",
    "/reports",
    "▥",
    [],
    renderReports,
  ],
  suggestions: [
    "Đề xuất thông minh",
    "Những việc nên làm từ dữ liệu hàng hóa.",
    "/suggestions",
    "✦",
    ["inventory"],
    renderSuggestions,
  ],
  settings: [
    "Cài đặt",
    "Tài khoản, sao lưu và nhật ký cửa hàng.",
    "/settings",
    "⚙",
    [],
    renderSettings,
  ],
};
let loading = false,
  pending = false;
async function refresh() {
  if (loading) {
    pending = true;
    return;
  }
  loading = true;
  document.getElementById("content").setAttribute("aria-busy", "true");
  const error = document.getElementById("page-error");
  error.textContent = "";
  try {
    await pages[state.page][5](document.getElementById("content"));
  } catch (err) {
    const retry = el("button", {type: "button", class: "small", onclick: refresh}, "Thử lại");
    error.replaceChildren(el("span", {}, err.message + " "), retry);
    document.querySelector(".loading-state")?.remove();
  } finally {
    loading = false;
    document.getElementById("content").setAttribute("aria-busy", "false");
    if (pending) {
      pending = false;
      await refresh();
    }
  }
}
async function init() {
  state.user = await api("/api/session");
  const allowed = (key) => pages[key][4] === null || can(...pages[key][4]);
  if (!allowed(state.page)) {
    state.page = state.user.role + "_portal";
    history.replaceState({}, "", "/" + state.user.role);
  }
  const page = pages[state.page];
  document.getElementById("page-title").textContent = page[0];
  document.getElementById("page-description").textContent = page[1];
  document.title = page[0] + " · Tạp hóa 360";
  document.getElementById("role-label").textContent = label(state.user.role);
  document.getElementById("today").textContent = new Date().toLocaleDateString(
    "vi-VN",
    { weekday: "long", day: "numeric", month: "long" },
  );
  const nav = document.getElementById("navigation");
  for (const [id, [title, , , icon]] of Object.entries(pages)) {
    if (!allowed(id)) continue;
    if (id.endsWith("_portal") && id !== state.user.role + "_portal") continue;
    if (["owner_portal", "products", "hr"].includes(id))
      nav.append(
        el(
          "div",
          { class: "nav-label" },
          id === "owner_portal"
            ? "VẬN HÀNH"
            : id === "products"
              ? "HÀNG HÓA & ĐỐI TÁC"
              : "QUẢN TRỊ",
        ),
      );
    nav.append(
      el(
        "a",
        {
          href: pages[id][2],
          class: "nav-link" + (state.page === id ? " active" : ""),
          "aria-current": state.page === id ? "page" : null,
        },
        navIcon(id),
        title,
      ),
    );
  }
  const menu = document.getElementById("menu-toggle");
  const scrim = document.getElementById("nav-scrim");
  const mobile = matchMedia("(max-width: 800px)");
  function toggleMenu(open) {
    document.body.classList.toggle("nav-open", open);
    menu.setAttribute("aria-expanded", String(open));
    menu.setAttribute("aria-label", open ? "Đóng menu" : "Mở menu");
    scrim.hidden = !open;
    document.getElementById("sidebar").inert = mobile.matches && !open;
    if (open) nav.querySelector("a[aria-current='page']")?.focus();
    else menu.focus();
  }
  menu.addEventListener("click", () => toggleMenu(!document.body.classList.contains("nav-open")));
  scrim.addEventListener("click", () => toggleMenu(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("nav-open")) toggleMenu(false);
  });
  const syncMenu = () => {
    document.getElementById("sidebar").inert = mobile.matches && !document.body.classList.contains("nav-open");
    if (!mobile.matches) { document.body.classList.remove("nav-open"); scrim.hidden = true; menu.setAttribute("aria-expanded", "false"); }
  };
  mobile.addEventListener("change", syncMenu);
  syncMenu();
  document.getElementById("logout").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    state.loggingOut = true;
    state.stream?.close();
    try {
      await api("/api/logout", {});
      location.href = "/login/" + state.user.role;
    } catch (error) {
      state.loggingOut = false;
      document.getElementById("logout").disabled = false;
      toast(error.message);
    }
  });
  document
    .getElementById("modal-close")
    .addEventListener("click", () => document.getElementById("modal").close());
  setRefresh(refresh);
  await refresh();
  if (can("cashier", "inventory", "shipper")) {
    const stream = new EventSource("/api/v1/events"),
      badge = document.getElementById("connection");
    state.stream = stream;
    stream.onopen = () => {
      badge.textContent = "● Đang đồng bộ";
      badge.classList.remove("warn");
    };
    stream.onerror = () => {
      badge.textContent = "Đang kết nối lại…";
      badge.classList.add("warn");
    };
    stream.addEventListener("session-expired", () => {
      stream.close();
      if (!state.loggingOut) location.href = "/login/" + state.user.role;
    });
    stream.onmessage = (e) => {
      let message;
      try { message = JSON.parse(e.data); } catch { return; }
      if (message.status === "connected") return;
      toast(message.order_code + " · " + label(message.status));
      if (
        ["orders", "owner_portal", "shipper_portal"].includes(state.page) &&
        !document.getElementById("modal").open
      )
        refresh();
    };
  }
}
init().catch((err) => {
  document.getElementById("page-error").textContent = err.message;
});
