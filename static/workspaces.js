import {
  api,
  el,
  panel,
  toolbar,
  link,
  button,
  replace,
  metric,
  money,
  badge,
  state,
  refresh,
  confirmAction,
  label,
} from "./ui.js?v=3.1";
import { renderPOS } from "./pos.js?v=3.1";
import { renderInventory, renderDashboard, orderDetail } from "./operations.js?v=3.1";

function workspace(content, links) {
  const body = el("div");
  replace(
    content,
    el("div", {class: "workspace-links"}, ...links.map(([name, path]) => link(name, path))),
    body,
  );
  return body;
}

export async function renderOwner(content) {
  const body = workspace(content, [
    ["Khu thu ngân →", "/cashier"],
    ["Khu kiểm kho →", "/inventory"],
    ["Khu giao hàng →", "/shipper"],
    ["Quản lý tài khoản", "/settings"],
  ]);
  await renderDashboard(body);
}

export async function renderCashier(content) {
  const body = workspace(content, [
    ["Mở / chốt ca", "/cash"],
    ["Đơn hàng & đổi trả", "/orders"],
    ["Khách hàng", "/customers"],
    ["Lịch ca của tôi", "/hr"],
  ]);
  await renderPOS(body);
}

export async function renderStockroom(content) {
  const body = workspace(content, [
    ["Sản phẩm", "/products"],
    ["Đơn cần soạn", "/orders"],
    ["Sơ đồ kệ", "/store_map"],
    ["Lịch ca của tôi", "/hr"],
  ]);
  await renderInventory(body);
}

export async function renderDelivery(content) {
  const all = await api("/orders");
  const assigned =
    state.user.role === "owner"
      ? all.filter(
          (order) => order.fulfillment === "DELIVERY" || order.shipper_user_id,
        )
      : all;
  const active = assigned.filter((order) =>
    ["PENDING", "PROCESSING", "SHIPPING"].includes(order.status),
  );
  const completed = assigned.filter((order) => order.status === "COMPLETED");
  const cards = active.map((order) =>
    el(
      "article",
      { class: "delivery-card" },
      el(
        "div",
        { class: "panel-head" },
        el("h2", {}, order.order_code),
        badge(order.status),
      ),
      el(
        "p",
        { class: "delivery-address" },
        order.apartment || "Chưa có địa chỉ giao hàng",
      ),
      order.customer_note
        ? el("p", { class: "notice" }, order.customer_note)
        : null,
      el("p", { class: "muted" }, "Giá trị đơn: " + money(order.total_amount)),
      el(
        "small",
        {},
        "Thanh toán: " +
          order.payment_method.split("+").map(label).join(" + ") +
          " · Ghi nhận lúc " +
          order.created_at,
      ),
      state.user.role === "owner"
        ? el(
            "small",
            {},
            "Người giao: " + (order.shipper_name || "Chưa phân công"),
          )
        : null,
      toolbar(
        button("Xem hàng & chi tiết", () => orderDetail(order.id)),
        order.status === "SHIPPING"
          ? button(
              "Đã giao thành công",
              () =>
                confirmAction(
                  "Xác nhận giao hàng",
                  "Xác nhận đã giao đơn " +
                    order.order_code +
                    " cho khách tại " +
                    order.apartment +
                    ".",
                  () =>
                    api("/orders/" + order.id + "/status", {
                      status: "COMPLETED",
                    }),
                ),
              "primary",
            )
          : el("span", { class: "hint" }, "Chờ cửa hàng soạn và bàn giao."),
      ),
    ),
  );
  replace(
    content,
    el(
      "div",
      { class: "cards" },
      metric(
        "Đơn đang giao",
        active.filter((o) => o.status === "SHIPPING").length,
        "Đã được bàn giao",
        true,
      ),
      metric(
        "Chờ nhận hàng",
        active.filter((o) => o.status !== "SHIPPING").length,
        "Cửa hàng đang chuẩn bị",
      ),
      metric("Đã giao xong", completed.length, "Trong danh sách đơn gần đây"),
    ),
    toolbar(button("Tải lại đơn", refresh), link("Lịch ca & chấm công", "/hr")),
    panel(
      state.user.role === "owner"
        ? "Quản lý toàn bộ đơn giao"
        : "Đơn được phân công cho bạn",
      cards.length
        ? el("div", { class: "delivery-grid" }, cards)
        : el(
            "div",
            { class: "empty" },
            "Hiện chưa có đơn giao cần xử lý. Đơn mới sẽ xuất hiện khi cửa hàng phân công cho bạn.",
          ),
    ),
    completed.length
      ? panel(
          "Đã giao gần đây",
          completed.slice(0, 10).map((o) =>
            el(
              "div",
              { class: "status-line" },
              o.order_code + " · " + o.apartment + " ",
              button("Chi tiết", () => orderDetail(o.id), "small"),
            ),
          ),
        )
      : null,
  );
}
