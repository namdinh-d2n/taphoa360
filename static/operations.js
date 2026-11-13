import {
  replace,
  api,
  el,
  button,
  link,
  panel,
  toolbar,
  table,
  money,
  qty,
  badge,
  label,
  actions,
  formModal,
  showModal,
  closeModal,
  field,
  readFields,
  toast,
  refresh,
  owner,
  can,
  state,
  metric,
  csv,
  today,
} from "./ui.js?v=3.1";
const num = (name, label, value = 0, extra = {}) => ({
  name,
  label,
  type: "number",
  value,
  ...extra,
});
const text = (name, label, extra = {}) => ({ name, label, ...extra });
const select = (name, label, options, extra = {}) => ({
  name,
  label,
  options,
  ...extra,
});
const paymentOptions = [
  ["CASH", "Tiền mặt"],
  ["TRANSFER", "Chuyển khoản"],
];
const productColumns = [
  {
    label: "Mặt hàng",
    render: (p) =>
      el(
        "div",
        {},
        el("strong", {}, p.product_name),
        el("small", {}, p.sku + (p.barcode ? " · " + p.barcode : "")),
      ),
  },
  { label: "Giá bán", render: (p) => money(p.selling_price) },
  {
    label: "Tồn / bán được",
    render: (p) => `${qty(p.stock)} / ${qty(p.sellable_stock)} ${p.unit}`,
  },
  {
    label: "Vị trí",
    render: (p) =>
      el("div", {}, p.zone_code, el("small", {}, p.shelf_location)),
  },
];

export async function renderProducts(content) {
  const data = await api("/products");
  const body = el("div"),
    search = el("input", {
      placeholder: "Tìm tên hàng, SKU hoặc mã vạch",
      ariaLabel: "Tìm sản phẩm",
    });
  function edit(p = {}) {
    const fields = [
      text("product_name", "Tên hàng"),
      text("sku", "SKU"),
      text("barcode", "Mã vạch", { required: false }),
      num("price", "Giá bán"),
      num("cost_price", "Giá vốn nhập gần nhất"),
      text("unit", "Đơn vị", { value: "cái" }),
      text("zone_code", "Khu / kệ", { value: "A1" }),
      text("shelf_location", "Tầng / ô", { required: false }),
      num("min_stock", "Ngưỡng nhập thêm", 5, { step: "1" }),
      { name: "active", label: "Đang bán", type: "checkbox", value: true },
    ];
    if (p.id && !owner())
      fields.splice(
        fields.findIndex((f) => f.name === "price"),
        1,
      );
    formModal(
      p.id ? "Sửa mặt hàng" : "Thêm mặt hàng",
      fields,
      (d) =>
        api("/products" + (p.id ? "/" + p.id : ""), d, p.id ? "PATCH" : "POST"),
      p,
    );
  }
  function draw() {
    const term = search.value.toLocaleLowerCase("vi");
    const filtered = data.filter((p) =>
      [p.product_name, p.sku, p.barcode]
        .join(" ")
        .toLocaleLowerCase("vi")
        .includes(term),
    );
    replace(
      body,
      table(filtered, [
        ...productColumns,
        {
          label: "Trạng thái",
          render: (p) => badge(p.active ? "ACTIVE" : "INACTIVE"),
        },
        ...(can("inventory")
          ? [
              {
                label: "Thao tác",
                render: (p) =>
                  actions(
                    button("Sửa", () => edit(p), "small"),
                    p.promo_price != null && owner()
                      ? button(
                          "Dừng giảm giá",
                          async () => {
                            await api(
                              "/products/" + p.id + "/end-promotion",
                              {},
                            );
                            await refresh();
                          },
                          "small",
                        )
                      : null,
                  ),
              },
            ]
          : []),
      ]),
    );
  }
  search.addEventListener("input", draw);
  replace(
    content,
    panel(
      "Danh mục hàng hóa",
      toolbar(
        search,
        can("inventory")
          ? button("+ Thêm mặt hàng", () => edit(), "primary")
          : null,
        button("Xuất CSV", () =>
          csv("san-pham.csv", data, [
            { key: "product_name", label: "Tên hàng" },
            { key: "sku", label: "SKU" },
            { key: "price", label: "Giá" },
            { key: "stock", label: "Tồn" },
            { key: "zone_code", label: "Kệ" },
          ]),
        ),
      ),
      body,
    ),
  );
  draw();
}

function purchaseForm(products, suppliers) {
  if (!suppliers.length)
    throw new Error("Hãy thêm nhà cung cấp trước khi nhập hàng");
  let lines = [];
  const lineBox = el("div"),
    error = el("p", { class: "error" }),
    totalLabel = el("strong");
  const fields = [
    select(
      "supplier_id",
      "Nhà cung cấp",
      suppliers.map((s) => [s.id, s.name]),
      { numeric: true },
    ),
    select("method", "Phương thức trả", paymentOptions, { value: "TRANSFER" }),
    num("paid", "Đã trả (bỏ trống để trả đủ)", null, { required: false }),
    text("note", "Ghi chú", { required: false }),
  ];
  const form = el(
    "form",
    {},
    el(
      "div",
      { class: "form-grid" },
      fields.map((f) => field(f)),
    ),
  );
  function total() {
    return lines.reduce(
      (s, line) =>
        s + Math.round(Number(line.quantity.value) * Number(line.cost.value)),
      0,
    );
  }
  function add() {
    const p = el(
      "select",
      {},
      products
        .filter((p) => p.active)
        .map((p) => el("option", { value: p.id }, p.product_name)),
    );
    const quantity = el("input", {
        type: "number",
        min: 1,
        step: 1,
        value: 1,
        required: true,
      }),
      cost = el("input", {
        type: "number",
        min: 0,
        step: 1,
        value: products.find((x) => x.id === Number(p.value))?.cost_price || 0,
        required: true,
      }),
      lot = el("input", { placeholder: "Mã lô (tự tạo nếu trống)" }),
      expiry = el("input", { type: "date", min: today() });
    const line = { p, quantity, cost, lot, expiry };
    lines.push(line);
    const row = el(
      "div",
      { class: "form-section" },
      el(
        "div",
        { class: "form-grid" },
        el("label", {}, "Sản phẩm", p),
        el("label", {}, "Số lượng", quantity),
        el("label", {}, "Giá vốn / đơn vị", cost),
        el("label", {}, "Mã lô", lot),
        el("label", {}, "Hạn sử dụng", expiry),
      ),
      button(
        "Bỏ dòng",
        () => {
          lines = lines.filter((x) => x !== line);
          row.remove();
          totalLabel.textContent = money(total());
        },
        "small",
      ),
    );
    p.addEventListener("change", () => {
      cost.value =
        products.find((x) => x.id === Number(p.value))?.cost_price || 0;
      totalLabel.textContent = money(total());
    });
    [quantity, cost].forEach((x) =>
      x.addEventListener(
        "input",
        () => (totalLabel.textContent = money(total())),
      ),
    );
    lineBox.append(row);
    totalLabel.textContent = money(total());
  }
  const save = el(
    "button",
    { type: "submit", class: "primary" },
    "Ghi nhận phiếu nhập",
  );
  form.append(
    lineBox,
    toolbar(
      button("+ Thêm dòng", add),
      el("span", { class: "spacer" }),
      totalLabel,
    ),
    error,
    el("div", { class: "form-actions" }, button("Hủy", closeModal), save),
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    error.textContent = "";
    try {
      const data = readFields(form, fields);
      data.paid = data.paid ?? total();
      data.items = lines.map((l) => ({
        product_id: Number(l.p.value),
        quantity: Number(l.quantity.value),
        cost_price: Number(l.cost.value),
        lot_code: l.lot.value,
        expires_on: l.expiry.value || null,
      }));
      await api("/purchases", data);
      closeModal();
      toast("Đã nhập kho");
      await refresh();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  });
  showModal("Nhập hàng từ nhà cung cấp", form);
  add();
}

export async function renderInventory(content) {
  const [data, products, suppliers] = await Promise.all([
    api("/inventory"),
    api("/products"),
    api("/suppliers"),
  ]);
  const count = () =>
    formModal(
      "Kiểm kê tồn kho",
      [
        select(
          "product_id",
          "Mặt hàng",
          products.map((p) => [
            p.id,
            p.product_name + " · tồn " + qty(p.stock),
          ]),
          { numeric: true },
        ),
        num("counted", "Số lượng thực đếm", 0, { step: "1" }),
        text("note", "Lý do chênh lệch"),
      ],
      (d) => api("/stock-counts", d),
    );
  replace(
    content,
    toolbar(
      button("+ Nhập hàng", () => purchaseForm(products, suppliers), "primary"),
      button("Kiểm kê tồn", count),
      link("Nhà cung cấp", "/suppliers"),
      link("Đề xuất nhập / cận hạn", "/suggestions"),
    ),
    panel(
      "Các lô hàng",
      table(data.batches, [
        { label: "Mặt hàng", key: "product_name" },
        { label: "Mã lô", key: "lot_code" },
        {
          label: "Hạn sử dụng",
          render: (b) =>
            el(
              "span",
              { class: b.expires_on && b.expires_on < today() ? "bad" : "" },
              b.expires_on || "Không khai báo",
            ),
        },
        { label: "Còn lại", render: (b) => qty(b.remaining) },
        { label: "Giá vốn", render: (b) => money(b.cost_price) },
        {
          label: "Thao tác",
          render: (b) =>
            actions(
              owner()
                ? button(
                    "Sửa lô",
                    () =>
                      formModal(
                        "Điều chỉnh lô hàng",
                        [
                          text("lot_code", "Mã lô"),
                          num("cost_price", "Giá vốn"),
                          text("expires_on", "Hạn sử dụng", {
                            type: "date",
                            required: false,
                          }),
                          text("note", "Lý do chỉnh lô"),
                        ],
                        (d) => api("/batches/" + b.id, d, "PATCH"),
                        b,
                      ),
                    "small",
                  )
                : null,
              b.remaining >= 1
                ? button(
                    "Xuất hỏng / hết hạn",
                    () =>
                      formModal(
                        "Loại bỏ hàng trong lô",
                        [
                          num("quantity", "Số lượng", Math.floor(b.remaining), {
                            step: "1",
                            max: Math.floor(b.remaining),
                            min: 1,
                          }),
                          text("note", "Lý do"),
                        ],
                        (d) => api("/batches/" + b.id + "/dispose", d),
                      ),
                    "small danger",
                  )
                : null,
            ),
        },
      ]),
    ),
    panel(
      "Phiếu nhập gần đây",
      table(data.receipts, [
        { label: "Phiếu", render: (r) => "PN-" + r.id },
        { label: "Nhà cung cấp", key: "supplier_name" },
        { label: "Tổng tiền", render: (r) => money(r.total) },
        { label: "Đã trả", render: (r) => money(r.paid) },
        { label: "Còn nợ", render: (r) => money(r.total - r.paid) },
        { label: "Thời gian", key: "created_at" },
      ]),
    ),
    panel(
      "Sổ biến động kho",
      table(data.movements, [
        { label: "Thời gian", key: "created_at" },
        { label: "Mặt hàng", key: "product_name" },
        { label: "Nghiệp vụ", render: (r) => label(r.kind) },
        {
          label: "Thay đổi",
          render: (r) =>
            el(
              "strong",
              { class: r.quantity > 0 ? "good" : "bad" },
              (r.quantity > 0 ? "+" : "") + qty(r.quantity),
            ),
        },
        { label: "Tham chiếu", key: "reference" },
        { label: "Người thực hiện", key: "actor" },
        { label: "Ghi chú", key: "note" },
      ]),
    ),
  );
}

export async function renderParties(content, kind) {
  const customer = kind === "CUSTOMER",
    endpoint = customer ? "/customers" : "/suppliers",
    data = await api(endpoint);
  const edit = (p = {}) =>
    formModal(
      p.id
        ? "Sửa thông tin"
        : customer
          ? "Thêm khách hàng"
          : "Thêm nhà cung cấp",
      [
        text("name", "Tên"),
        text("phone", "Điện thoại", { required: false }),
        text(
          customer ? "customer_group" : "address",
          customer ? "Nhóm khách" : "Địa chỉ",
          { required: false, value: customer ? "RETAIL" : "" },
        ),
      ],
      (d) =>
        api(endpoint + (p.id ? "/" + p.id : ""), d, p.id ? "PATCH" : "POST"),
      p,
    );
  async function history(p) {
    const entries = await api("/accounts/" + kind + "/" + p.id);
    const blocks = [
      panel(
        "Sổ công nợ",
        table(entries, [
          { label: "Ngày", key: "created_at" },
          { label: "Thay đổi", render: (e) => money(e.amount) },
          { label: "Tham chiếu", key: "reference" },
          { label: "Ghi chú", key: "note" },
        ]),
      ),
    ];
    if (customer) {
      const orders = await api("/orders?customer_id=" + p.id);
      blocks.unshift(
        panel(
          "Lịch sử mua hàng",
          table(orders, [
            { label: "Mã đơn", key: "order_code" },
            { label: "Tổng tiền", render: (o) => money(o.total_amount) },
            { label: "Trạng thái", render: (o) => badge(o.status) },
            { label: "Ngày", key: "created_at" },
          ]),
        ),
      );
    }
    showModal(p.name, el("div", {}, blocks));
  }
  replace(
    content,
    panel(
      customer ? "Khách hàng & tích điểm" : "Nhà cung cấp & công nợ",
      toolbar(
        button(
          customer ? "+ Khách hàng" : "+ Nhà cung cấp",
          () => edit(),
          "primary",
        ),
      ),
      customer
        ? el(
            "p",
            { class: "hint" },
            "Mỗi 10.000đ tiền hàng sau giảm giá tích 1 điểm. Mỗi điểm đổi được 100đ. Điểm được điều chỉnh khi trả hàng.",
          )
        : null,
      table(data, [
        { label: "Tên", key: "name" },
        { label: "Điện thoại", key: "phone" },
        ...(customer
          ? [
              { label: "Nhóm", key: "customer_group" },
              { label: "Điểm", key: "points" },
            ]
          : [{ label: "Địa chỉ", key: "address" }]),
        { label: "Công nợ", render: (p) => money(p.debt) },
        {
          label: "Thao tác",
          render: (p) =>
            actions(
              button("Sửa", () => edit(p), "small"),
              button("Lịch sử", () => history(p), "small"),
              p.debt > 0
                ? button(
                    customer ? "Thu nợ" : "Trả nợ",
                    () =>
                      formModal(
                        customer ? "Thu công nợ" : "Thanh toán nhà cung cấp",
                        [
                          num("amount", "Số tiền", p.debt, {
                            max: p.debt,
                            min: 1,
                          }),
                          select("method", "Phương thức", paymentOptions),
                          text("note", "Ghi chú", { required: false }),
                        ],
                        (d) =>
                          api("/accounts/" + kind + "/" + p.id + "/settle", d),
                      ),
                    "small",
                  )
                : null,
            ),
        },
      ]),
    ),
  );
}

export async function orderDetail(id) {
  const order = await api("/orders/" + id);
  const actionBar = toolbar();
  if (can("cashier")) actionBar.append(link("In hóa đơn", "/receipt/" + id));
  if (
    ["PENDING", "PROCESSING"].includes(order.status) &&
    can("inventory", "cashier")
  ) {
    if (order.status === "PENDING")
      actionBar.append(
        button(
          "Bắt đầu soạn",
          async () => {
            await api("/orders/" + id + "/status", { status: "PROCESSING" });
            await orderDetail(id);
            await refresh();
          },
          "primary",
        ),
      );
    if (can("inventory"))
      actionBar.append(
        button("Phân công giao hàng", async () => {
          const shippers = await api("/shippers");
          if (!shippers.length)
            throw new Error(
              "Chưa có tài khoản giao hàng. Chủ tiệm tạo tài khoản trong Cài đặt.",
            );
          formModal(
            "Phân công giao hàng",
            [
              select(
                "user_id",
                "Người giao",
                shippers.map((s) => [s.id, s.name]),
                { numeric: true },
              ),
            ],
            (d) => api("/orders/" + id + "/assign", d),
          );
        }),
      );
    if (order.status === "PROCESSING")
      actionBar.append(
        button(
          "Bàn giao đi giao",
          async () => {
            await api("/orders/" + id + "/status", { status: "SHIPPING" });
            await orderDetail(id);
            await refresh();
          },
          "primary",
        ),
      );
    if (can("cashier") && order.managed)
      actionBar.append(
        button(
          "Hủy đơn",
          () =>
            formModal(
              "Hủy đơn và hoàn tiền",
              [
                text("reason", "Lý do"),
                select("method", "Hoàn tiền qua", paymentOptions),
              ],
              (d) =>
                api("/orders/" + id + "/status", { ...d, status: "CANCELLED" }),
            ),
          "danger",
        ),
      );
  }
  if (order.status === "SHIPPING")
    actionBar.append(
      button(
        "Xác nhận giao thành công",
        async () => {
          await api("/orders/" + id + "/status", { status: "COMPLETED" });
          await orderDetail(id);
          await refresh();
        },
        "primary",
      ),
    );
  const rows = table(order.items, [
    {
      label: "Mặt hàng",
      render: (i) =>
        el("div", {}, i.product_name, el("small", {}, i.shelf_location)),
    },
    {
      label: "Số lượng / đã trả",
      render: (i) => qty(i.quantity) + " / " + qty(i.returned_qty),
    },
    { label: "Giá", render: (i) => money(i.price) },
    { label: "Thành tiền sau giảm", render: (i) => money(i.net_subtotal) },
    {
      label: "Thao tác",
      render: (i) =>
        actions(
          ["PENDING", "PROCESSING"].includes(order.status) &&
            can("inventory", "cashier")
            ? button(
                i.is_picked ? "✓ Đã lấy" : "Đánh dấu đã lấy",
                async () => {
                  await api("/order-items/" + i.id + "/pick", {
                    picked: !i.is_picked,
                  });
                  await orderDetail(id);
                },
                i.is_picked ? "small" : "small primary",
              )
            : null,
          can("cashier") &&
            order.managed &&
            ["COMPLETED", "PARTIAL_RETURN"].includes(order.status) &&
            i.returned_qty < i.quantity
            ? button(
                "Trả hàng",
                () =>
                  formModal(
                    (i.quantity - i.returned_qty < 1
                      ? "Hoàn trả phần lẻ cũ · "
                      : "Trả ") + i.product_name,
                    [
                      ...(i.quantity - i.returned_qty >= 1
                        ? [
                            num(
                              "quantity",
                              "Số lượng trả",
                              Math.floor(i.quantity - i.returned_qty),
                              {
                                step: "1",
                                min: 1,
                                max: Math.floor(i.quantity - i.returned_qty),
                              },
                            ),
                          ]
                        : []),
                      {
                        name: "restock",
                        label: "Hàng còn sử dụng được, nhập lại kho",
                        type: "checkbox",
                        value: true,
                      },
                      text("reason", "Lý do"),
                      select("method", "Hoàn tiền qua", paymentOptions),
                    ],
                    (d) =>
                      api("/orders/" + id + "/returns", {
                        reason: d.reason,
                        method: d.method,
                        items: [
                          {
                            item_id: i.id,
                            quantity:
                              d.quantity ??
                              Math.round((i.quantity - i.returned_qty) * 1000) /
                                1000,
                            restock: d.restock,
                          },
                        ],
                      }),
                  ),
                "small",
              )
            : null,
        ),
    },
  ]);
  showModal(
    order.order_code,
    el(
      "div",
      {},
      el(
        "div",
        { class: "detail-stats" },
        el(
          "div",
          {},
          el("small", {}, "Tổng đơn"),
          el("strong", {}, money(order.total_amount)),
        ),
        badge(order.status),
      ),
      el("p", { class: "muted" }, order.apartment || "Nhận tại cửa hàng"),
      actionBar,
      rows,
      panel(
        "Lịch sử xử lý",
        order.events.map((e) =>
          el(
            "div",
            { class: "status-line" },
            e.created_at +
              " · " +
              label(e.status) +
              (e.note ? " · " + e.note : ""),
          ),
        ),
      ),
      order.returns.length
        ? panel(
            "Hoàn tiền",
            table(order.returns, [
              { label: "Ngày", key: "created_at" },
              { label: "Số tiền", render: (r) => money(r.amount) },
              { label: "Lý do", key: "reason" },
            ]),
          )
        : null,
    ),
  );
}

export async function renderOrders(content) {
  const data = await api("/orders");
  const search = el("input", {
      placeholder: "Tìm mã đơn hoặc người tạo",
      ariaLabel: "Tìm đơn hàng",
    }),
    status = el(
      "select",
      { ariaLabel: "Lọc trạng thái" },
      el("option", { value: "" }, "Tất cả trạng thái"),
      [
        "PENDING",
        "PROCESSING",
        "SHIPPING",
        "COMPLETED",
        "CANCELLED",
        "PARTIAL_RETURN",
        "RETURNED",
      ].map((s) => el("option", { value: s }, label(s))),
    ),
    body = el("div");
  function draw() {
    const filtered = data.filter(
      (o) =>
        (!status.value || o.status === status.value) &&
        [o.order_code, o.created_by]
          .join(" ")
          .toLowerCase()
          .includes(search.value.toLowerCase()),
    );
    replace(
      body,
      table(filtered, [
        {
          label: "Mã đơn",
          render: (o) =>
            el(
              "div",
              {},
              el("strong", {}, o.order_code),
              el("small", {}, o.created_at),
            ),
        },
        {
          label: "Khách / thu ngân",
          render: (o) =>
            el(
              "div",
              {},
              o.customer_name || "Khách lẻ",
              el("small", {}, o.created_by),
            ),
        },
        { label: "Tổng tiền", render: (o) => money(o.total_amount) },
        { label: "Đã hoàn", render: (o) => money(o.refunded) },
        { label: "Trạng thái", render: (o) => badge(o.status) },
        { label: "Người giao", key: "shipper_name" },
        {
          label: "Chi tiết",
          render: (o) => button("Mở đơn →", () => orderDetail(o.id), "small"),
        },
      ]),
    );
  }
  search.addEventListener("input", draw);
  status.addEventListener("change", draw);
  replace(
    content,
    panel(
      "Đơn hàng gần đây",
      toolbar(
        search,
        status,
        button("Tải lại", refresh),
        can("cashier") ? link("+ Tạo đơn", "/pos", "button primary") : null,
      ),
      body,
    ),
  );
  draw();
}

export async function renderCash(content) {
  const data = await api("/cash-shifts");
  replace(
    content,
    panel(
      "Ca thu ngân & đối chiếu tiền",
      toolbar(
        button(
          "+ Mở ca",
          () =>
            formModal(
              "Mở ca thu ngân",
              [num("opening_cash", "Tiền mặt đầu ca")],
              (d) => api("/cash-shifts", d),
            ),
          "primary",
        ),
      ),
      el(
        "p",
        { class: "hint" },
        "Tiền dự kiến = đầu ca + thu tiền mặt − hoàn tiền − chi nhập hàng/trả nợ. Các khoản chuyển khoản không cộng vào két.",
      ),
      table(data, [
        { label: "Ca", render: (s) => "#" + s.id },
        { label: "Thu ngân", key: "cashier" },
        { label: "Mở lúc", key: "opened_at" },
        { label: "Tiền đầu", render: (s) => money(s.opening_cash) },
        { label: "Bán hàng thuần", render: (s) => money(s.net_sales) },
        { label: "Thu/chi chuyển khoản", render: (s) => money(s.transfer_net) },
        {
          label: "Dự kiến",
          render: (s) => money(s.closed_at ? s.expected_cash : s.live_expected),
        },
        {
          label: "Thực đếm",
          render: (s) => (s.closed_at ? money(s.counted_cash) : "—"),
        },
        {
          label: "Chênh lệch",
          render: (s) =>
            s.closed_at
              ? el(
                  "strong",
                  { class: s.difference ? "bad" : "good" },
                  money(s.difference),
                )
              : "—",
        },
        {
          label: "Thao tác",
          render: (s) =>
            s.closed_at
              ? badge("COMPLETED")
              : button(
                  "Chốt ca",
                  () =>
                    formModal(
                      "Chốt ca #" + s.id,
                      [
                        num("counted_cash", "Tiền thực đếm"),
                        text("note", "Giải trình nếu chênh lệch", {
                          required: false,
                        }),
                      ],
                      (d) => api("/cash-shifts/" + s.id + "/close", d),
                    ),
                  "small primary",
                ),
        },
      ]),
    ),
  );
}

export async function renderMap(content) {
  const products = await api("/products"),
    search = el("input", {
      placeholder: "Tìm hàng để tô sáng đúng kệ",
      ariaLabel: "Tìm vị trí hàng",
    }),
    grid = el("div", { class: "map-grid" });
  function draw() {
    const term = search.value.trim().toLocaleLowerCase("vi"),
      zones = [...new Set(products.map((p) => p.zone_code))].sort();
    replace(
      grid,
      ...zones.map((zone) => {
        const ps = products.filter((p) => p.zone_code === zone),
          match = (p) =>
            term &&
            [p.product_name, p.sku, p.barcode]
              .join(" ")
              .toLocaleLowerCase("vi")
              .includes(term);
        return el(
          "section",
          { class: "shelf" + (ps.some(match) ? " selected" : "") },
          el("h3", {}, "KỆ " + zone),
          ps.map((p) =>
            el(
              "div",
              { class: "shelf-item" },
              match(p) ? el("mark", {}, p.product_name) : p.product_name,
              el(
                "small",
                {},
                p.shelf_location + " · " + qty(p.stock) + " " + p.unit,
              ),
            ),
          ),
        );
      }),
    );
  }
  search.addEventListener("input", draw);
  replace(
    content,
    panel(
      "Sơ đồ các kệ hàng",
      toolbar(search),
      el(
        "p",
        { class: "hint" },
        "Kệ được nhóm từ vị trí sản phẩm đã khai báo. Danh sách soạn hàng trong đơn được sắp theo khu và vị trí.",
      ),
      grid,
    ),
  );
  draw();
}

export async function renderSuggestions(content) {
  const data = await api("/suggestions");
  replace(
    content,
    panel(
      "Đề xuất từ dữ liệu cửa hàng",
      el(
        "p",
        { class: "hint" },
        "Phân tích theo tồn có thể bán, lịch sử xuất hàng và hạn từng lô. Giá khuyến mãi áp dụng cho toàn bộ sản phẩm đến ngày kết thúc.",
      ),
      data.length
        ? el(
            "div",
            {},
            data.map((s) =>
              el(
                "div",
                { class: "suggestion" },
                el(
                  "div",
                  {},
                  el("strong", {}, s.name),
                  el("p", {}, s.reason),
                  el("small", {}, s.action),
                ),
                owner() && ["SLOW", "EXPIRING"].includes(s.type)
                  ? button(
                      "Áp dụng khuyến mãi",
                      async () => {
                        const result = await api("/suggestions/apply", {
                          key: s.key,
                        });
                        toast(
                          "Giá mới " +
                            money(result.price) +
                            " đến " +
                            result.until,
                        );
                        await refresh();
                      },
                      "primary",
                    )
                  : link("Mở kho", "/warehouse"),
              ),
            ),
          )
        : el("div", { class: "empty" }, "Chưa có cảnh báo cần xử lý."),
    ),
  );
}

export async function renderDashboard(content) {
  if (!owner()) {
    replace(
      content,
      el(
        "div",
        { class: "hero" },
        el(
          "div",
          {},
          el("h2", {}, "Chào " + state.user.name + "!"),
          el(
            "p",
            {},
            "Mọi thao tác trong ca làm được lưu và đồng bộ với cửa hàng.",
          ),
        ),
        el("span", { class: "hero-icon" }, "◈"),
      ),
      toolbar(
        can("cashier")
          ? link("Bắt đầu bán hàng", "/pos", "button primary")
          : null,
        can("inventory")
          ? link("Quản lý kho", "/warehouse", "button primary")
          : null,
        link("Đơn hàng", "/orders"),
        link("Chấm công & lịch ca", "/hr"),
      ),
    );
    return;
  }
  const [report, suggestions, orders] = await Promise.all([
    api("/reports?start=" + today() + "&end=" + today()),
    api("/suggestions"),
    api("/orders"),
  ]);
  replace(
    content,
    el(
      "div",
      { class: "hero" },
      el(
        "div",
        {},
        el("p", { class: "eyebrow" }, "MỖI NGÀY MỘT CHÚT TỐT HƠN"),
        el("h2", {}, "Một ngày bán hàng thuận lợi."),
        el(
          "p",
          {},
          "Theo dõi dòng tiền, hàng hóa và những việc cần xử lý ngay hôm nay.",
        ),
      ),
      el("span", { class: "hero-icon" }, "◈"),
    ),
    el(
      "div",
      { class: "cards" },
      metric(
        "Doanh số thuần hôm nay",
        money(report.net_revenue),
        "Đã trừ các khoản hoàn",
        true,
      ),
      metric("Đơn hàng", qty(report.order_count), "Được tạo trong ngày"),
      metric(
        "Cần xử lý",
        qty(
          orders.filter((o) => ["PENDING", "PROCESSING"].includes(o.status))
            .length,
        ),
        "Đơn chờ xác nhận / soạn",
      ),
      metric(
        "Cảnh báo hàng hóa",
        qty(suggestions.length),
        "Tồn thấp, bán chậm, cận hạn",
      ),
    ),
    toolbar(
      link("+ Bán hàng", "/pos", "button primary"),
      link("Nhập hàng", "/warehouse"),
      link("Báo cáo chi tiết", "/reports"),
    ),
    el(
      "div",
      { class: "grid-two" },
      panel(
        "Đơn hàng mới",
        table(orders.slice(0, 6), [
          { label: "Mã đơn", key: "order_code" },
          { label: "Thành tiền", render: (o) => money(o.total_amount) },
          { label: "Trạng thái", render: (o) => badge(o.status) },
          {
            label: "",
            render: (o) => button("Xem", () => orderDetail(o.id), "small"),
          },
        ]),
      ),
      panel(
        "Cần chú ý",
        suggestions.length
          ? suggestions
              .slice(0, 4)
              .map((s) =>
                el(
                  "div",
                  { class: "suggestion" },
                  el(
                    "div",
                    {},
                    el("strong", {}, s.name),
                    el("p", {}, s.reason),
                  ),
                ),
              )
          : el("div", { class: "empty" }, "Không có cảnh báo hàng hóa."),
        link("Xem đề xuất →", "/suggestions", ""),
      ),
    ),
  );
}

export async function renderReports(content) {
  const start = el("input", {
      type: "date",
      value: today().slice(0, 8) + "01",
      ariaLabel: "Từ ngày",
    }),
    end = el("input", { type: "date", value: today(), ariaLabel: "Đến ngày" }),
    body = el("div");
  async function draw() {
    const r = await api("/reports?start=" + start.value + "&end=" + end.value);
    const max = Math.max(1, ...r.daily.map((d) => Math.abs(d.revenue)));
    replace(
      body,
      el(
        "div",
        { class: "cards" },
        metric(
          "Doanh số thuần",
          money(r.net_revenue),
          "Tiền hàng trừ hoàn tiền",
          true,
        ),
        metric(
          "Lợi nhuận gộp",
          money(r.gross_profit),
          "Chưa trừ chi phí vận hành",
        ),
        metric(
          "Giá vốn đã xuất",
          money(r.cost_of_goods),
          "Đã trừ hàng nhập lại khi trả",
        ),
        metric("Giá trị tồn", money(r.inventory_value), "Theo giá vốn từng lô"),
      ),
      r.missing_cost_entries
        ? el(
            "div",
            { class: "notice" },
            `Có ${r.missing_cost_entries} dòng bán/đơn cũ thiếu giá vốn. Lợi nhuận gộp chưa phản ánh đầy đủ các dòng này.`,
          )
        : null,
      panel(
        "Doanh số theo ngày",
        r.daily.length
          ? el(
              "div",
              { class: "bar-chart" },
              r.daily.slice(-20).map((d) => {
                const bar = el("div", {
                  class: "bar",
                  title: money(d.revenue),
                });
                bar.style.height =
                  Math.max(3, (Math.abs(d.revenue) / max) * 115) + "px";
                if (d.revenue < 0) bar.style.background = "#c97762";
                return el(
                  "div",
                  { class: "bar-column" },
                  el("small", {}, qty(d.revenue)),
                  bar,
                  el("span", {}, d.day.slice(5)),
                );
              }),
            )
          : el(
              "div",
              { class: "empty" },
              "Chưa có giao dịch trong khoảng ngày này.",
            ),
      ),
      el(
        "div",
        { class: "grid-equal" },
        panel(
          "Hàng bán chạy",
          table(r.top_products, [
            { label: "Mặt hàng", key: "product_name" },
            { label: "SKU", key: "sku" },
            { label: "Lượng xuất ròng", render: (p) => qty(p.quantity) },
          ]),
        ),
        panel(
          "Thu / chi theo phương thức",
          table(r.payments, [
            { label: "Phương thức", render: (p) => label(p.method) },
            { label: "Nghiệp vụ", render: (p) => label(p.kind) },
            { label: "Số tiền", render: (p) => money(p.amount) },
          ]),
        ),
      ),
      panel(
        "Trạng thái đơn",
        table(r.statuses, [
          { label: "Trạng thái", render: (o) => badge(o.status) },
          { label: "Số đơn", key: "count" },
        ]),
      ),
      panel(
        "Doanh số theo ca",
        table(r.cash_shifts, [
          { label: "Ca", render: (s) => "#" + s.id },
          { label: "Thu ngân", key: "cashier" },
          { label: "Mở lúc", key: "opened_at" },
          { label: "Bán hàng thuần", render: (s) => money(s.net_sales) },
          {
            label: "Thu/chi chuyển khoản",
            render: (s) => money(s.transfer_net),
          },
          {
            label: "Chênh lệch tiền mặt",
            render: (s) => (s.closed_at ? money(s.difference) : "Chưa chốt"),
          },
        ]),
      ),
      button("Xuất báo cáo ngày CSV", () =>
        csv("doanh-so.csv", r.daily, [
          { key: "day", label: "Ngày" },
          { key: "revenue", label: "Doanh số thuần" },
        ]),
      ),
    );
  }
  replace(
    content,
    toolbar(start, end, button("Xem báo cáo", draw, "primary")),
    body,
  );
  await draw();
}
