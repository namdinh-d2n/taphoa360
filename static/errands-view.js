import {
  el,
  button,
  money,
  qty,
  panel,
  toolbar,
  field,
  readFields,
  showModal,
  closeModal,
} from "./ui.js?v=3.1";
export const statuses = {
  REQUESTED: "Mới tiếp nhận",
  ESTIMATE_REVIEW: "Chờ duyệt dự kiến",
  ESTIMATE_APPROVED: "Đã duyệt dự kiến",
  SHOPPING: "Đang chọn hàng",
  CHANGE_REVIEW: "Chờ duyệt thay thế",
  FINAL_REVIEW: "Chờ duyệt bản chốt",
  APPROVED: "Đã duyệt, chờ mua",
  PURCHASED: "Đã mua / đóng gói",
  SHIPPING: "Đang giao",
  DELIVERED: "Kiểm nhận & quyết toán",
  SETTLED: "Đã quyết toán",
  CANCELLED: "Đã hủy",
};
export const spec = (name, label, type = "text", extra = {}) => ({
  name,
  label,
  type,
  ...extra,
});
export const select = (name, label, options) => ({
  name,
  label,
  options,
  required: name !== "product_id",
});
export function form(title, specs, initial, submit, extra = null) {
  const node = el(
    "form",
    {},
    el(
      "div",
      { class: "form-grid" },
      specs.map((s) => {
        const node = field(s, initial[s.name]);
        node
          .querySelector("input,select,textarea")
          .setAttribute("aria-label", s.label);
        return node;
      }),
    ),
  );
  if (extra) node.append(extra);
  const error = el("p", { class: "error", role: "alert" });
  const save = el("button", { type: "submit", class: "primary" }, "Xác nhận");
  node.append(error, toolbar(save, button("Quay lại", closeModal)));
  node.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    error.textContent = "";
    try {
      await submit(readFields(node, specs));
      closeModal();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  });
  delete document.getElementById("modal").dataset.errandQr;
  showModal(title, node);
  return node;
}
function textForm(title, label, callback, name = "note") {
  form(title, [spec(name, label, "textarea")], {}, callback);
}
export function card(order, selected, open) {
  return button(
    "",
    () => open(order.id),
    "errand-order-card" + (selected === order.id ? " active" : ""),
  );
}
export function fillCard(node, o) {
  node.append(
    el("strong", {}, o.code),
    el("span", { class: "errand-status" }, statuses[o.status]),
    el("small", {}, o.items.map((i) => i.requested_name).join(" · ")),
    el("b", {}, money(o.total || o.estimate || o.budget)),
    el("small", {}, o.delivery_window),
  );
}
function evidence(url, staff) {
  return url
    ? el(
        "a",
        {
          href: url + (staff ? "?staff=1" : ""),
          target: "_blank",
          rel: "noopener",
        },
        el("img", {
          src: url + (staff ? "?staff=1" : ""),
          alt: "Ảnh minh chứng trong đơn",
          class: "errand-evidence",
          loading: "lazy",
        }),
      )
    : document.createDocumentFragment();
}
function photoInput(order, ctx, initial = "") {
  const input = el("input", { type: "file", accept: "image/*" });
  const wrap = el("label", {}, "Ảnh hàng / minh chứng (tối đa 4 MB)", input);
  return {
    node: wrap,
    upload: async () => {
      if (!input.files[0]) return initial;
      const body = new FormData();
      body.append("image", input.files[0]);
      const response = await fetch(
        `/api/errands/${order.id}/photos` + (ctx.staff ? "?staff=1" : ""),
        { method: "POST", headers: { "X-CSRF-Token": ctx.user.csrf }, body },
      );
      const result = await response.json();
      if (!response.ok) throw Error(result.detail || "Không tải được ảnh");
      return result.url;
    },
  };
}
export function renderDetail(host, o, ctx) {
  host.replaceChildren();
  const staff = ctx.staff,
    role = ctx.user.role;
  const cashier = staff && ["owner", "cashier"].includes(role),
    shopper = staff && ["owner", "inventory"].includes(role);
  const action = (name, data = {}) => ctx.action(o, name, data);
  const ask = (name, title, label, key = "note") =>
    textForm(title, label, (d) => action(name, d), key);
  const f = o.finance;
  const goods = o.items.reduce(
    (sum, i) => sum + (i.skipped ? 0 : i.subtotal),
    0,
  );
  host.append(
    panel(
      o.code,
      el("p", { class: "errand-status" }, statuses[o.status]),
      el("p", {}, o.receiver + " · " + o.phone),
      el("p", {}, o.address),
      o.branch_name
        ? el(
            "p",
            { class: "errand-branch" },
            o.province_name + " · " + o.branch_name,
          )
        : null,
      el("p", {}, "Giờ mong muốn: " + o.delivery_window),
      el("p", {}, "Ngân sách trọn gói: " + money(o.budget)),
      el("p", {}, "Yêu cầu: " + o.preferences),
    ),
  );
  const actions = toolbar();
  if (!staff) {
    if (o.status === "ESTIMATE_REVIEW")
      actions.append(
        button(
          "Đồng ý giá dự kiến",
          () => action("approve-estimate"),
          "primary",
        ),
      );
    if (o.status === "FINAL_REVIEW") {
      actions.append(
        button(
          "Đồng ý hàng & tổng tiền",
          () => action("approve-final"),
          "primary",
        ),
      );
      actions.append(
        button("Yêu cầu chỉnh bản chốt", () =>
          ask("revise", "Chỉnh bản chốt", "Món / giá / phí cần chỉnh"),
        ),
      );
    }
    if (o.status === "DELIVERED" && !o.received)
      actions.append(
        button("Tôi đã kiểm nhận hàng", () => action("receive"), "primary"),
      );
    if (
      [
        "REQUESTED",
        "ESTIMATE_REVIEW",
        "ESTIMATE_APPROVED",
        "SHOPPING",
        "CHANGE_REVIEW",
        "FINAL_REVIEW",
        "APPROVED",
      ].includes(o.status)
    )
      actions.append(
        button("Hủy yêu cầu", () =>
          ask("cancel", "Hủy trước khi mua", "Lý do hủy"),
        ),
      );
  } else {
    if (cashier && ["REQUESTED", "ESTIMATE_REVIEW"].includes(o.status))
      actions.append(
        button(
          "Gửi giá dự kiến",
          () =>
            form(
              "Báo giá đã gồm phí",
              [
                spec("estimate", "Tổng dự kiến (đ)", "number"),
                spec("note", "Nội dung báo giá", "textarea"),
              ],
              { estimate: o.estimate || o.budget },
              (d) => action("estimate", d),
            ),
          "primary",
        ),
      );
    if (
      cashier &&
      !["SHIPPING", "DELIVERED", "CANCELLED", "SETTLED"].includes(o.status)
    )
      actions.append(
        button("Phân công", () =>
          form(
            "Phân công đi chợ và giao",
            [
              select(
                "shopper_id",
                "Người đi chợ",
                ctx.data.workers
                  .filter((w) => ["owner", "inventory"].includes(w.role))
                  .map((w) => [w.id, w.name]),
              ),
              select(
                "shipper_id",
                "Người giao",
                ctx.data.workers
                  .filter((w) => ["owner", "shipper"].includes(w.role))
                  .map((w) => [w.id, w.name]),
              ),
            ],
            o,
            (d) => action("assign", d),
          ),
        ),
      );
    if (
      cashier &&
      [
        "ESTIMATE_APPROVED",
        "SHOPPING",
        "CHANGE_REVIEW",
        "FINAL_REVIEW",
      ].includes(o.status)
    )
      actions.append(
        button(
          "Gửi bản chốt cho khách",
          () =>
            ask(
              "final",
              "Gửi khách duyệt lần cuối",
              "Ghi rõ chênh lệch, phí và nội dung cần xác nhận",
            ),
          "primary",
        ),
      );
    if (shopper && o.status === "APPROVED")
      actions.append(
        button(
          "Xác nhận mua / xuất kho",
          () =>
            ask(
              "purchase",
              "Mua đúng bản khách duyệt",
              "Mã hóa đơn, nơi mua, kiểm chất lượng và đóng gói",
            ),
          "primary",
        ),
      );
    if (cashier && o.status === "PURCHASED")
      actions.append(button("Bắt đầu giao", () => action("ship"), "primary"));
    if (staff && ["owner", "shipper"].includes(role) && o.status === "SHIPPING")
      actions.append(
        button(
          "Xác nhận đã giao",
          () =>
            ask(
              "deliver",
              "Bàn giao cho khách",
              "Biên nhận và tình trạng giao",
            ),
          "primary",
        ),
      );
    if (cashier && ["DELIVERED", "CANCELLED"].includes(o.status))
      actions.append(
        button("Đối soát và quyết toán", () => action("settle"), "primary"),
      );
    if (
      cashier &&
      [
        "REQUESTED",
        "ESTIMATE_REVIEW",
        "ESTIMATE_APPROVED",
        "SHOPPING",
        "CHANGE_REVIEW",
        "FINAL_REVIEW",
        "APPROVED",
      ].includes(o.status)
    )
      actions.append(
        button("Hủy trước khi mua", () =>
          ask("cancel", "Hủy và hoàn tiền", "Lý do hủy", "reason"),
        ),
      );
  }
  host.append(panel("Thao tác", actions));
  if (["ESTIMATE_REVIEW", "CHANGE_REVIEW", "FINAL_REVIEW"].includes(o.status))
    host.append(
      el(
        "p",
        { class: "errand-alert" },
        "Chờ khách xác nhận trước " +
          o.review_deadline.replace("T", " ") +
          ". Chưa phản hồi sẽ không tự duyệt hoặc mua.",
      ),
    );
  if (cashier && o.status === "APPROVED")
    actions.append(
      button("Chỉnh lại trước khi mua", () =>
        ask(
          "revise-approved",
          "Cần khách duyệt lại",
          "Lý do hàng / giá thay đổi trước khi mua",
        ),
      ),
    );
  const items = panel("Danh sách & chất lượng hàng");
  for (const i of o.items) {
    const item = el(
      "article",
      { class: "errand-item" },
      el("h4", {}, i.requested_name),
      el(
        "p",
        {},
        `Yêu cầu: ${qty(i.requested_qty)} ${i.requested_unit} · ${i.criteria}`,
      ),
    );
    if (i.skipped)
      item.append(el("p", { class: "errand-status" }, "Khách đã chọn bỏ món"));
    else if (i.selected_name)
      item.append(
        el(
          "p",
          {},
          `Thực chọn: ${i.selected_name} · ${qty(i.quantity)} ${i.unit} × ${money(i.unit_price)} = ${money(i.subtotal)}`,
        ),
        el("p", {}, "Kiểm chất lượng: " + i.quality),
        el(
          "p",
          {},
          (i.source === "STORE" ? "Hàng của tiệm" : "Mua ngoài") +
            " · " +
            i.vendor,
        ),
        evidence(i.photo, staff),
      );
    else item.append(el("p", { class: "muted" }, "Chưa chọn hàng"));
    if (i.proposal) {
      const p = i.proposal;
      const proposal = el(
        "div",
        { class: "errand-proposal" },
        el("strong", {}, "Cần khách quyết định"),
        p.unavailable
          ? el("p", {}, "Hết hàng / không đạt chất lượng")
          : el(
              "div",
              {},
              el(
                "p",
                {},
                `${p.selected_name} · ${qty(p.quantity)} ${p.unit} · ${money(p.subtotal)}`,
              ),
              el("p", {}, p.quality),
              evidence(p.photo, staff),
            ),
      );
      if (!staff)
        proposal.append(
          toolbar(
            ...(p.unavailable
              ? []
              : [
                  button(
                    "Đồng ý thay thế",
                    () =>
                      action("decide-item", {
                        item_id: i.id,
                        decision: "APPROVE",
                      }),
                    "primary",
                  ),
                ]),
            button("Bỏ món", () =>
              action("decide-item", { item_id: i.id, decision: "SKIP" }),
            ),
            button("Chọn lại / hỏi thêm", () =>
              action("decide-item", { item_id: i.id, decision: "REJECT" }),
            ),
          ),
        );
      item.append(proposal);
    }
    if (
      shopper &&
      ["ESTIMATE_APPROVED", "SHOPPING", "CHANGE_REVIEW"].includes(o.status)
    ) {
      const edit = (propose) => {
        const photo = photoInput(o, ctx, i.photo);
        const fields = [
          spec("selected_name", "Tên hàng thực chọn"),
          spec("quantity", "Lượng thực chọn", "number", {
            step: "1",
            min: 1,
          }),
          spec("unit", "Đơn vị (kg, bó, hộp…)"),
          spec("unit_price", "Đơn giá (đ)", "number"),
          select("source", "Nguồn hàng", [
            ["EXTERNAL", "Mua ngoài"],
            ["STORE", "Hàng của tiệm"],
          ]),
          select("product_id", "Sản phẩm kho nếu lấy từ tiệm", [
            ["", "Không lấy từ kho"],
            ...(ctx.data.products || []).map((p) => [
              p.id,
              p.product_name + " · " + p.unit,
            ]),
          ]),
          spec("vendor", "Nguồn mua / nhà bán"),
          spec(
            "quality",
            "Độ tươi, tình trạng, hạn dùng, sơ chế / bảo quản",
            "textarea",
          ),
          ...(propose
            ? [
                spec(
                  "reason",
                  "Lý do thiếu hàng / đổi hàng / đổi lượng",
                  "textarea",
                ),
              ]
            : []),
        ];
        const formNode = form(
          propose ? "Gửi phương án thay thế" : "Ghi nhận chọn hàng",
          fields,
          {
            ...i,
            selected_name: i.selected_name || i.requested_name,
            quantity: i.quantity || i.requested_qty,
            unit: i.unit || i.requested_unit,
            vendor: i.vendor || "Tiệm / quầy chợ",
          },
          async (d) =>
            action(propose ? "propose" : "select", {
              ...d,
              item_id: i.id,
              photo: await photo.upload(),
            }),
          photo.node,
        );
        formNode.elements.product_id.addEventListener("change", (e) => {
          const p = (ctx.data.products || []).find(
            (p) => String(p.id) === e.target.value,
          );
          if (p) {
            formNode.elements.source.value = "STORE";
            formNode.elements.selected_name.value = p.product_name;
            formNode.elements.unit.value = p.unit;
            formNode.elements.unit_price.value = p.price;
          }
        });
      };
      item.append(
        toolbar(
          button("Chọn đúng yêu cầu", () => edit(false)),
          button("Đề xuất thay thế", () => edit(true)),
          button("Báo hết / không đạt", () =>
            textForm(
              "Thông báo thiếu hàng",
              "Mô tả tình trạng để khách quyết định",
              (d) => action("unavailable", { ...d, item_id: i.id }),
              "reason",
            ),
          ),
        ),
      );
    }
    if (!staff && ["DELIVERED", "SETTLED"].includes(o.status) && !i.skipped) {
      item.append(
        button("Phản hồi / khiếu nại món này", () => {
          const photo = photoInput(o, ctx);
          form(
            "Phản hồi về " + (i.selected_name || i.requested_name),
            [
              spec(
                "reason",
                "Tình trạng hàng, số lượng bị ảnh hưởng và mong muốn xử lí",
                "textarea",
              ),
            ],
            {},
            async (d) =>
              action("complaints", {
                ...d,
                item_id: i.id,
                photo: await photo.upload(),
              }),
            photo.node,
          );
        }),
      );
    }
    items.append(item);
  }
  host.append(items);
  const totals = el("div", { class: "errand-totals" });
  for (const [label, value] of [
    ["Tiền hàng", Math.max(0, o.total - o.service_fee - o.shipping_fee)],
    ["Phí mua hộ", o.service_fee],
    ["Phí giao", o.shipping_fee],
    ["Tổng bản chốt", o.total],
    ["Điều chỉnh khiếu nại", o.credit],
    ["Đã nhận", f.received],
    ["Đã hoàn", f.refunded],
    ["Còn thu", f.collect_due],
    ["Chờ hoàn", f.refund_due],
  ])
    totals.append(
      el(
        "div",
        { class: "errand-total" },
        el("span", {}, label),
        el("strong", {}, money(value)),
      ),
    );
  const financial = panel(
    "Đối soát và quyết toán chi phí",
    el("p", {}, "Dự kiến đã gồm phí: " + money(o.estimate)),
    totals,
  );
  if (o.total > o.budget)
    financial.append(
      el(
        "p",
        { class: "errand-alert" },
        "Bản chốt vượt ngân sách " +
          money(o.total - o.budget) +
          ". Cần khách xác nhận rõ trước khi mua.",
      ),
    );
  if (f.refund_due)
    financial.append(
      el(
        "p",
        { class: "errand-alert" },
        "Còn phải hoàn " +
          money(f.refund_due) +
          ". Chỉ đánh dấu đã hoàn khi có giao dịch/biên nhận thực tế.",
      ),
    );
  if (cashier) {
    financial.append(
      toolbar(
        ...[
          ["RECEIVE", "Ghi nhận thu tiền", f.collect_due],
          ["REFUND", "Ghi nhận hoàn tiền", f.refund_due],
          ["EXPENSE", "Chi tiền hàng mua ngoài", f.expense_due],
        ].map(([kind, label, amount]) =>
          button(label, () => {
            const idempotency = crypto.randomUUID();
            form(
              label,
              [
                spec("amount", "Số tiền thực tế (đ)", "number"),
                select("method", "Phương thức", [
                  ["TRANSFER", "Chuyển khoản"],
                  ["CASH", "Tiền mặt"],
                ]),
                spec("reference", "Mã giao dịch / biên nhận thực tế"),
                spec("recipient", "Người hoặc tài khoản nộp / nhận tiền"),
                spec("reason", "Nội dung đối soát / hóa đơn mua", "textarea"),
              ],
              { amount },
              (d) => ctx.action(o, "money", { ...d, kind }, idempotency),
            );
          }),
        ),
      ),
    );
    financial.append(
      el(
        "p",
        { class: "hint" },
        "Tiền mặt cần mở ca. Xác nhận chuyển khoản sau khi đối chiếu ngân hàng. Chi mua ngoài ghi riêng để không nhầm với tiền khách trả.",
      ),
    );
  }
  financial.prepend(
    el(
      "p",
      {},
      `Tiền hàng đã chọn ${money(goods)} + phí mua hộ ${money(o.service_fee)} + phí giao ${money(o.shipping_fee)}.`,
    ),
  );
  if (!staff) {
    const pay = o.payment;
    const paymentBox = el(
      "section",
      { class: "errand-payment" },
      el("h3", {}, "Thanh toán đơn đi chợ hộ"),
    );
    const method = el(
      "select",
      { ariaLabel: "Phương thức thanh toán" },
      el("option", { value: "TRANSFER" }, "Chuyển khoản qua QR"),
      el("option", { value: "CASH" }, "Tiền mặt khi nhận hàng"),
    );
    method.value = o.payment_method;
    method.disabled = ["SETTLED", "CANCELLED"].includes(o.status);
    method.addEventListener("change", async () => {
      method.disabled = true;
      try {
        await action("payment-method", { method: method.value });
      } catch (error) {
        method.value = o.payment_method;
        method.disabled = false;
        paymentError.textContent = error.message;
      }
    });
    const paymentError = el("p", { class: "error", role: "alert" });
    paymentBox.append(
      el("label", {}, "Phương thức thanh toán", method),
      paymentError,
    );
    function qrContent() {
      if (!pay.amount)
        return el(
          "p",
          {},
          "Đơn không còn khoản đã duyệt cần chuyển. Thông tin thanh toán đã cập nhật.",
        );
      const bank = pay.bank;
      const path = `/api/shop/errands/${o.id}/qr?version=${o.version}`;
      return el(
        "div",
        { class: "errand-qr-large" },
        el("strong", {}, money(pay.amount)),
        el("img", { src: path, alt: "Mã QR chuyển khoản cho đơn " + o.code }),
        el("p", {}, bank.bank_name + " · " + bank.bank_account),
        el("p", {}, "Nội dung: " + o.code),
        el(
          "p",
          { class: "hint" },
          "Kiểm tra người nhận và số tiền trong ứng dụng ngân hàng trước khi chuyển.",
        ),
        el(
          "a",
          { href: path, download: o.code + "-qr.png", class: "button" },
          "Tải ảnh QR",
        ),
      );
    }
    function openQr() {
      const modal = document.getElementById("modal");
      showModal("QR thanh toán · " + o.code, qrContent());
      modal.dataset.errandQr = String(o.id);
      modal.addEventListener(
        "close",
        () => {
          delete modal.dataset.errandQr;
        },
        { once: true },
      );
    }
    const modal = document.getElementById("modal");
    if (modal.open && modal.dataset.errandQr === String(o.id)) {
      document
        .getElementById("modal-content")
        .replaceChildren(
          pay.qr_ready && o.payment_method === "TRANSFER"
            ? qrContent()
            : el(
                "p",
                {},
                "Khoản thanh toán đã thay đổi. Xem thông tin mới trên đơn.",
              ),
        );
    }
    if (o.payment_method === "TRANSFER") {
      if (pay.amount > 0) {
        paymentBox.append(
          el("p", {}, "Cần chuyển theo khoản đã duyệt: " + money(pay.amount)),
        );
        if (pay.qr_ready)
          paymentBox.append(button("Mở QR thanh toán", openQr, "primary"));
        else
          paymentBox.append(
            el(
              "p",
              { class: "hint" },
              "Tiệm chưa cấu hình ngân hàng nhận tiền. Liên hệ tiệm hoặc chọn tiền mặt.",
            ),
          );
        paymentBox.append(
          button("Tôi đã chuyển khoản", () =>
            ask(
              "report-payment",
              "Báo chuyển khoản",
              "Mã giao dịch để cửa hàng đối chiếu",
            ),
          ),
        );
        paymentBox.append(
          el(
            "p",
            { class: "hint" },
            "Báo đã chuyển để cửa hàng đối chiếu. Số tiền đã nhận cập nhật ngay sau khi thu ngân xác nhận.",
          ),
        );
      } else
        paymentBox.append(
          el(
            "p",
            {},
            ["REQUESTED", "ESTIMATE_REVIEW"].includes(o.status)
              ? "QR sẽ hiện khi bạn đồng ý giá dự kiến hoặc bản chốt có khoản cần thanh toán."
              : "Không còn tiền đã duyệt cần chuyển thêm.",
          ),
        );
    } else
      paymentBox.append(
        el(
          "p",
          {},
          "Thanh toán tiền mặt khi nhận, chỉ thu khoản bạn đã đồng ý trong bản chốt.",
        ),
      );
    financial.append(paymentBox);
  }
  const ledger = el("ul", { class: "errand-ledger" });
  for (const m of o.ledger)
    ledger.append(
      el(
        "li",
        {},
        el(
          "strong",
          {},
          { RECEIVE: "Thu", REFUND: "Hoàn", EXPENSE: "Chi mua ngoài" }[m.kind] +
            " " +
            money(m.amount),
        ),
        el("p", {}, m.method + " · " + m.reference + " · " + m.recipient),
        el("small", {}, m.created_at + " · " + m.reason),
      ),
    );
  financial.append(ledger);
  host.append(financial);
  const complaints = panel(
    "Phản hồi sau nhận hàng",
    el(
      "p",
      {},
      `Tiếp nhận trong ${o.complaint_hours} giờ sau giao. ${o.policy}`,
    ),
  );
  for (const c of o.complaints) {
    const box = el(
      "article",
      { class: "errand-item" },
      el(
        "strong",
        {},
        {
          OPEN: "Đã tiếp nhận",
          REVIEW: "Đang xử lí",
          RESOLVED: "Đã xử lí",
          REJECTED: "Đã phản hồi lý do",
        }[c.status],
      ),
      el("p", {}, c.reason),
      evidence(c.photo, staff),
      el("p", {}, c.reply || "Cửa hàng đang kiểm tra."),
    );
    if (cashier && ["OPEN", "REVIEW"].includes(c.status))
      box.append(
        button("Xác minh & xử lí", () =>
          form(
            "Xử lí khiếu nại",
            [
              select("resolution", "Phương án", [
                ["REFUND", "Giảm tiền / hoàn tiền"],
                ["REPLACE", "Đổi hàng"],
                ["REJECT", "Từ chối có lý do"],
              ]),
              spec("credit", "Tiền hàng giảm / hoàn được duyệt", "number"),
              spec(
                "reply",
                "Kết quả xác minh, cách nhận trả/đổi và lý do",
                "textarea",
              ),
            ],
            { credit: 0 },
            (d) => action("resolve", { ...d, complaint_id: c.id }),
          ),
        ),
      );
    complaints.append(box);
  }
  host.append(complaints);
  host.append(
    panel(
      "Thông báo & lịch sử xác nhận",
      el(
        "div",
        { class: "errand-timeline" },
        [...o.events]
          .reverse()
          .map((e) =>
            el(
              "div",
              {},
              el("small", {}, e.created_at + " · " + e.actor),
              el("p", {}, e.message),
            ),
          ),
      ),
    ),
  );
}
