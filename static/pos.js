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
  const [products, customers, shifts, rescueOffers] = await Promise.all([
    api("/products"),
    api("/customers"),
    api("/cash-shifts"),
    api("/rescue/campaigns"),
  ]);
  let selectedRescue = null;
  const rescueStatus = el("div", { class: "rescue-pos-status", hidden: true, role: "status" });
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
  const comboDiscount = () => {
    if (!selectedRescue) return 0;
    const pair = [selectedRescue.product_id,selectedRescue.partner_id].map((id) => cart.find((item) => item.product.id === id));
    if (pair.some((item) => !item || item.quantity < selectedRescue.sets)) return 0;
    return Math.max(0,(pair.reduce((sum,item)=>sum+item.product.selling_price,0)-selectedRescue.price)*selectedRescue.sets);
  };
  const total = () =>
    Math.max(
      0,
      cart.reduce(
        (s, i) => s + Math.round(i.quantity * i.product.selling_price),
        0,
      ) -
        Number(discount.value || 0) -
        Number(points.value || 0) * 100 - comboDiscount(),
    );
  function updateTotal() {
    if (selectedRescue && [selectedRescue.product_id,selectedRescue.partner_id].some((id) => {
      const item = cart.find((line) => line.product.id === id);
      return !item || item.quantity < selectedRescue.sets;
    })) {
      selectedRescue = null;
      toast("Đã bỏ ưu đãi combo vì giỏ không còn đủ hai mặt hàng.");
    }
    discount.disabled = points.disabled = !!selectedRescue;
    rescueStatus.hidden = !selectedRescue;
    if (selectedRescue) replace(rescueStatus,
      el("strong", {}, selectedRescue.name),
      el("p", {}, selectedRescue.sets + " combo × " + money(selectedRescue.price) + " · tiết kiệm " + money(comboDiscount())),
      button("Bỏ ưu đãi (giữ hàng)", () => { selectedRescue=null; updateTotal(); }, "small"));
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
        ...(selectedRescue ? {rescue_campaign_id:selectedRescue.id,rescue_sets:selectedRescue.sets} : {}),
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
    rescueStatus,
    checkout,
  );
  cartPanel.classList.add("cart");
  const rescueSelect = el("select", {ariaLabel:"Combo giải cứu"},
    el("option",{value:""},"Chọn combo đang có"),
    rescueOffers.map((offer)=>el("option",{value:offer.id},offer.name+" · "+money(offer.price))));
  const rescueSets = el("input",{type:"number",min:1,step:1,value:1,ariaLabel:"Số combo giải cứu"});
  const rescueHint = el("p",{class:"hint"});
  rescueSelect.addEventListener("change",()=>{
    const offer=rescueOffers.find((value)=>value.id===Number(rescueSelect.value));
    rescueSets.max=offer?.available_sets || 1;
    rescueHint.textContent=offer ? "Mỗi combo: 1 "+offer.product_unit+" "+offer.product_name+" + 1 "+offer.partner_unit+" "+offer.partner_name+
      ". Còn "+offer.available_sets+" lượt · đến hết "+offer.expires_on+". Không cộng giảm giá tay hoặc đổi điểm." : "";
  });
  const rescuePicker = rescueOffers.length ? panel("Combo giải cứu cận hạn",
    el("div",{class:"form-grid"},el("label",{class:"full"},"Combo",rescueSelect),el("label",{},"Số combo",rescueSets)),rescueHint,
    button("Thêm combo vào giỏ",()=>{
      if (selectedRescue) throw new Error("Hãy bỏ ưu đãi combo đang chọn trước khi đổi combo.");
      if (Number(discount.value)||Number(points.value)) throw new Error("Đặt giảm giá thủ công và đổi điểm về 0 trước khi chọn combo.");
      const offer=rescueOffers.find((value)=>value.id===Number(rescueSelect.value));
      const sets=Number(rescueSets.value);
      if (!offer || !Number.isSafeInteger(sets) || sets<1 || sets>offer.available_sets) throw new Error("Chọn combo và số lượt trong giới hạn còn lại.");
      const pair=[offer.product_id,offer.partner_id].map((id)=>products.find((p)=>p.id===id));
      if (pair.some((p)=>!p || !p.active || p.sellable_stock < (cart.find((line)=>line.product.id===p.id)?.quantity || 0)+sets))
        throw new Error("Giỏ hiện tại cộng combo vượt tồn bán được. Hãy kiểm tra lại số lượng.");
      for (const p of pair) {
        const old=cart.find((line)=>line.product.id===p.id);
        if (old) old.quantity+=sets; else cart.push({product:p,quantity:sets});
      }
      selectedRescue={...offer,sets}; renderCart();
    },"primary")) : null;
  if (rescuePicker) rescuePicker.classList.add("rescue-pos");
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
    rescuePicker,
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
