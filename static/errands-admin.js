import { el, api, state, button, toolbar, panel, money } from "./ui.js?v=3.1";
import {
  form,
  spec,
  card,
  fillCard,
  renderDetail,
} from "./errands-view.js?v=2";
import { connectErrands } from "./errands-live.js?v=2";
let selected = null,
  live = null,
  revision = "",
  pending = false,
  rendering = false;
const indicator = el(
  "span",
  { class: "errand-live", role: "status" },
  "Đang kết nối…",
);
async function liveRefresh() {
  if (rendering) {
    pending = true;
    return;
  }
  rendering = true;
  try {
    do {
      pending = false;
      await renderErrands(document.getElementById("content"));
    } while (pending);
  } finally {
    rendering = false;
  }
}
export async function renderErrands(content, supplied) {
  const data = supplied || (await api("/errands"));
  const refresh = liveRefresh;
  if (!live)
    live = connectErrands("/api/v1/errands/events", liveRefresh, (text) => {
      indicator.textContent = text;
    });
  const next = JSON.stringify(data) + ":" + selected;
  if (next === revision) return;
  revision = next;
  const tools = toolbar(indicator);
  if (state.user.role === "owner")
    tools.append(
      button("Phí & chính sách", () =>
        form(
          "Cài đặt cho yêu cầu mới",
          [
            spec("service_fee", "Phí mua hộ (đ)", "number"),
            spec(
              "complaint_hours",
              "Thời hạn phản hồi sau giao (giờ)",
              "number",
            ),
            spec("policy", "Chính sách chất lượng / nhận trả", "textarea"),
          ],
          data.settings,
          async (d) => {
            await api("/errands/settings", d);
            await refresh();
          },
        ),
      ),
    );
  const pending = data.orders.filter((o) =>
    ["REQUESTED", "CHANGE_REVIEW", "FINAL_REVIEW"].includes(o.status),
  ).length;
  tools.append(
    el(
      "span",
      { class: "muted" },
      pending +
        " đơn cần theo dõi · " +
        data.orders.length +
        " đơn trong phạm vi của bạn",
    ),
  );
  const list = el("aside", { class: "errand-list" });
  const detail = el("div", { class: "errand-detail" });
  if (!selected && data.orders.length) selected = data.orders[0].id;
  for (const o of data.orders) {
    const node = card(o, selected, (id) => {
      selected = id;
      revision = "";
      return renderErrands(content, data);
    });
    fillCard(node, o);
    list.append(node);
  }
  if (!data.orders.length)
    list.append(
      el(
        "div",
        { class: "errand-empty" },
        "Chưa có đơn đi chợ hộ được tiếp nhận / phân công.",
      ),
    );
  const current = data.orders.find((o) => o.id === selected);
  if (current)
    renderDetail(detail, current, {
      staff: true,
      user: state.user,
      data,
      refresh,
      action: async (order, name, values = {}, key) => {
        const result = await api(
          `/errands/${order.id}/${name}`,
          { ...values, version: order.version },
          "POST",
          key ? { "Idempotency-Key": key } : {},
        );
        const index = data.orders.findIndex((o) => o.id === result.id);
        if (index >= 0) data.orders[index] = result;
        revision = "";
        await renderErrands(content, data);
      },
    });
  else
    detail.append(
      panel(
        "Quy trình vận hành",
        el(
          "p",
          {},
          "Báo dự kiến → khách duyệt → phân công và chọn hàng → duyệt thay thế → duyệt bản chốt → mua, giao → kiểm nhận → quyết toán.",
        ),
        el(
          "p",
          {},
          "Thu ngân đối chiếu tiền thực nhận/hoàn. Kiểm kho chọn hàng được giao. Nhân viên giao chỉ xem và giao đơn được phân công.",
        ),
      ),
    );
  content.replaceChildren(
    tools,
    el("div", { class: "errand-layout" }, list, detail),
  );
}
