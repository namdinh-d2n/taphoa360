import {
  replace,
  api,
  el,
  button,
  link,
  panel,
  toolbar,
  money,
  qty,
  state,
  toast,
  showModal,
  refresh,
} from "./ui.js?v=3.1";
let cart = [],
  checkoutKey = null,
  checkoutFingerprint = null;

export async function renderPOS(content) {
  const [products, customers, shifts] = await Promise.all([
    api("/products"),
    api("/customers"),
    api("/cash-shifts"),
  ]);
  const active = shifts.find(
    (s) => s.user_id === state.user.id && !s.closed_at,
  );
  const search = el("input", {
    placeholder: "Quét mã vạch hoặc tìm tên, SKU…",
    ariaLabel: "Tìm hàng hoặc quét mã vạch",
  });
  const grid = el("div", { class: "product-grid" }),
    cartBody = el("div"),
    cartTotal = el("strong"),
    cartCount = el("span", { class: "badge" });
  const customer = el(
    "select",
    { ariaLabel: "Khách hàng" },
    el("option", { value: "" }, "Khách lẻ"),
    customers.map((c) =>
      el("option", { value: c.id }, `${c.name} · ${c.points} điểm`),
    ),
  );
  const discount = el("input", {
      type: "number",
      min: 0,
      step: 1,
      value: 0,
      ariaLabel: "Giảm giá",
    }),
    points = el("input", {
      type: "number",
      min: 0,
      step: 1,
      value: 0,
      ariaLabel: "Đổi điểm",
    });
  const method = el(
    "select",
    { ariaLabel: "Thanh toán" },
    [
      ["CASH", "Tiền mặt"],
      ["TRANSFER", "Chuyển khoản"],
      ["DEBT", "Bán chịu"],
      ["MIXED", "Kết hợp nhiều phương thức"],
    ].map(([v, t]) => el("option", { value: v }, t)),
  );
  const cash = el("input", { type: "number", min: 0, step: 1, value: 0 }),
    transfer = el("input", { type: "number", min: 0, step: 1, value: 0 }),
    debt = el("input", { type: "number", min: 0, step: 1, value: 0 });
  const mixed = el(
    "div",
    { class: "cart-fields", hidden: true },
    el("label", {}, "Tiền mặt", cash),
    el("label", {}, "Chuyển khoản", transfer),
    el("label", {}, "Công nợ", debt),
  );
  const tendered = el("input", {
    type: "number",
    min: 0,
    step: 1,
    placeholder: "Mặc định bằng tiền mặt cần thu",
    ariaLabel: "Tiền khách đưa",
  });
  const fulfillment = el(
    "select",
    { ariaLabel: "Nhận hàng" },
    el("option", { value: "PICKUP" }, "Nhận tại cửa hàng"),
    el("option", { value: "DELIVERY" }, "Giao tận nơi"),
  );
  const address = el("input", {
      placeholder: "Địa chỉ giao hàng",
      ariaLabel: "Địa chỉ giao hàng",
    }),
    note = el("input", {
      placeholder: "Ghi chú đơn hàng",
      ariaLabel: "Ghi chú",
    }),
    change = el("small");
  const total = () =>
    Math.max(
      0,
      cart.reduce(
        (s, i) => s + Math.round(i.quantity * i.product.selling_price),
        0,
      ) -
        Number(discount.value || 0) -
        Number(points.value || 0) * 100,
    );
  function updateTotal() {
    cartTotal.textContent = money(total());
    const due =
      method.value === "CASH"
        ? total()
        : method.value === "MIXED"
          ? Number(cash.value || 0)
          : 0;
    change.textContent =
      "Tiền thối: " + money(Math.max(0, Number(tendered.value || due) - due));
  }
  function renderCart() {
    replace(cartBody);
    cartCount.textContent = cart.length + " mặt hàng";
    if (!cart.length)
      cartBody.append(
        el("div", { class: "empty" }, "Chọn sản phẩm để bắt đầu đơn hàng."),
      );
    for (const item of cart) {
      const input = el("input", {
        type: "number",
        min: 1,
        step: 1,
        max: item.product.sellable_stock,
        value: item.quantity,
        ariaLabel: "Số lượng " + item.product.product_name,
        oninput: () => {
          const next = Number(input.value);
          if (
            !Number.isSafeInteger(next) ||
            next < 1 ||
            next > item.product.sellable_stock
          ) {
            toast(
              "Số lượng phải là số nguyên từ 1 đến " +
                item.product.sellable_stock,
            );
            input.value = item.quantity;
            return;
          }
          item.quantity = next;
          updateTotal();
        },
        onblur: () => {
          input.value = String(item.quantity);
        },
      });
      cartBody.append(
        el(
          "div",
          { class: "cart-row" },
          el(
            "div",
            {},
            el("strong", {}, item.product.product_name),
            el(
              "small",
              {},
              money(item.product.selling_price) + " / " + item.product.unit,
            ),
          ),
          input,
          button(
            "×",
            () => {
              cart = cart.filter((x) => x !== item);
              renderCart();
            },
            "icon-button",
          ),
        ),
      );
    }
    updateTotal();
  }
  function add(p) {
    if (!p.active || p.sellable_stock <= 0) {
      toast("Mặt hàng hiện không có tồn bán được");
      return;
    }
    let existing = cart.find((i) => i.product.id === p.id);
    if (existing && existing.quantity >= p.sellable_stock) {
      toast("Đã chọn hết số lượng có thể bán");
      return;
    }
    if (existing) existing.quantity++;
    else cart.push({ product: p, quantity: 1 });
    renderCart();
  }
  function filter() {
    const q = search.value.trim().toLocaleLowerCase("vi");
    const filtered = products.filter(
      (p) =>
        p.active &&
        [p.product_name, p.sku, p.barcode].some((v) =>
          String(v || "")
            .toLocaleLowerCase("vi")
            .includes(q),
        ),
    );
    replace(
      grid,
      ...filtered.map((p) => button("", () => add(p), "product-card")),
    );
    [...grid.children].forEach((card, i) => {
      const p = filtered[i];
      card.append(
        el("span", { class: "product-glyph" }, p.zone_code.slice(0, 3)),
        el("strong", {}, p.product_name),
        el("span", { class: "product-price" }, money(p.selling_price)),
        el("small", {}, `Còn ${qty(p.sellable_stock)} ${p.unit} · ${p.sku}`),
      );
    });
    if (!filtered.length)
      grid.append(el("div", { class: "empty" }, "Không tìm thấy sản phẩm."));
  }
  search.addEventListener("input", filter);
  search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const q = search.value.trim();
      const p = products.find((p) => p.barcode === q || p.sku === q);
      if (p) {
        add(p);
        search.value = "";
        filter();
      } else toast("Không tìm thấy mã vạch hoặc SKU chính xác");
    }
  });
  [discount, points, tendered, cash, transfer, debt].forEach((x) =>
    x.addEventListener("input", updateTotal),
  );
  method.addEventListener("change", () => {
    mixed.hidden = method.value !== "MIXED";
    updateTotal();
  });
  const checkout = button(
    "Thanh toán & tạo đơn →",
    async () => {
      if (!cart.length) throw new Error("Giỏ hàng đang trống");
      if (
        cart.some(
          (item) => !Number.isSafeInteger(item.quantity) || item.quantity < 1,
        )
      )
        throw new Error("Số lượng phải là số nguyên từ 1 trở lên");
      const payments =
        method.value === "MIXED"
          ? [
              { method: "CASH", amount: Number(cash.value) },
              { method: "TRANSFER", amount: Number(transfer.value) },
              { method: "DEBT", amount: Number(debt.value) },
            ].filter((p) => p.amount > 0)
          : [{ method: method.value, amount: total() }];
      const cashDue = payments.find((p) => p.method === "CASH")?.amount || 0;
      const payload = {
        items: cart.map((i) => ({
          product_id: i.product.id,
          quantity: i.quantity,
        })),
        customer_id: customer.value ? Number(customer.value) : null,
        discount: Number(discount.value),
        points_redeemed: Number(points.value),
        payments,
        cash_tendered: tendered.value ? Number(tendered.value) : cashDue,
        fulfillment: fulfillment.value,
        apartment: address.value,
        customer_note: note.value,
      };
      const fp = JSON.stringify(payload);
      if (fp !== checkoutFingerprint) {
        checkoutKey = crypto.randomUUID();
        checkoutFingerprint = fp;
      }
      const result = await api("/orders", payload, "POST", {
        "Idempotency-Key": checkoutKey,
      });
      cart = [];
      checkoutKey = null;
      checkoutFingerprint = null;
      await refresh();
      showModal(
        "Đã tạo đơn " + result.order_code,
        el(
          "div",
          {},
          el(
            "div",
            { class: "detail-stats" },
            el(
              "div",
              {},
              el("small", {}, "Tổng tiền"),
              el("strong", {}, money(result.total_amount)),
            ),
            el(
              "div",
              {},
              el("small", {}, "Tiền thối"),
              el("strong", {}, money(result.change || 0)),
            ),
          ),
          link(
            "Mở & in hóa đơn",
            "/receipt/" + result.order_id,
            "button primary",
          ),
          link("Xem đơn hàng", "/orders"),
        ),
      );
    },
    "primary wide",
  );
  const cartPanel = panel(
    "",
    el(
      "div",
      { class: "panel-head" },
      el("h2", {}, "Đơn hàng hiện tại"),
      cartCount,
    ),
    cartBody,
    el(
      "div",
      { class: "cart-fields" },
      el("label", {}, "Khách hàng", customer),
      el(
        "div",
        { class: "form-grid" },
        el("label", {}, "Giảm giá (đ)", discount),
        el("label", {}, "Đổi điểm · 100đ/điểm", points),
      ),
      el("label", {}, "Phương thức thanh toán", method),
      mixed,
      el("label", {}, "Tiền khách đưa", tendered),
      el("label", {}, "Hình thức nhận", fulfillment),
      address,
      note,
    ),
    el(
      "div",
      { class: "cart-total" },
      el("span", {}, "Phải thanh toán"),
      cartTotal,
    ),
    change,
    checkout,
  );
  cartPanel.classList.add("cart");
  replace(
    content,
    !active
      ? el(
          "div",
          { class: "notice" },
          "Bạn chưa mở ca tiền mặt. ",
          link("Mở ca thu ngân", "/cash", ""),
        )
      : el("div", { class: "hint" }, "Ca tiền mặt #" + active.id + " đang mở"),
    el(
      "div",
      { class: "pos-layout" },
      panel("Chọn sản phẩm", toolbar(search), grid),
      cartPanel,
    ),
  );
  filter();
  renderCart();
  search.focus();
}
