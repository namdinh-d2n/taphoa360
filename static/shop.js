import { el, money, qty } from "./ui.js?v=3.1";
import { addressPicker } from "./address-picker.js?v=4.1";
import { productDetailPanel } from "./product-detail.js?v=4.2";
import { qrPayment } from "./qr-payment.js?v=4.3";
const $ = (selector) => document.querySelector(selector);
const dialog = $("#shop-dialog");
const readSaved = () => {
  try {
    return JSON.parse(localStorage.getItem("th360-cart") || "{}");
  } catch {
    return {};
  }
};
const state = {
  data: null,
  user: null,
  cart: readSaved(),
  combo: null,
  category: "",
  categoryGroup: "",
  brand: "",
  address: null,
  storage: "",
  interest: sessionStorage.getItem("th360-interest") || "",
  page: 24,
  zone: "",
  offset: 0,
};
let timer,
  requestNumber = 0,
  orderKey = null,
  orderFingerprint = null;
const types = {
  FRESH: "Hàng tươi",
  FROZEN: "Đông lạnh",
  CHILLED: "Bảo quản mát",
  DRY: "Đồ khô",
  HOUSEHOLD: "Gia dụng",
};
const statuses = {
  PENDING: "Chờ tiệm xác nhận",
  PAYMENT_REVIEW: "Đã báo thanh toán · chờ cửa hàng duyệt",
  REVIEW: "Cần bạn duyệt thay đổi",
  CONFIRMED: "Tiệm đã giữ hàng",
  SHIPPING: "Đang giao",
  COMPLETED: "Đã kiểm nhận",
  CANCELLED: "Đã hủy",
  EXPIRED: "Hết thời gian xác nhận",
};
const glyph = {
  FRESH: "🥬",
  FROZEN: "❄",
  CHILLED: "🥛",
  DRY: "🛒",
  HOUSEHOLD: "⌂",
};
function toast(text) {
  $("#shop-toast").textContent = text;
  $("#shop-toast").hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => ($("#shop-toast").hidden = true), 5000);
}
function button(text, fn, cls = "") {
  const node = el("button", { type: "button", class: cls }, text);
  node.addEventListener("click", async () => {
    node.disabled = true;
    try {
      await fn();
    } catch (error) {
      toast(error.message);
    } finally {
      node.disabled = false;
    }
  });
  return node;
}
async function api(path, data, method) {
  const response = await fetch("/api/shop" + path, {
    method: method || (data === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": state.user?.csrf || "",
      ...(orderKey && path === "/orders"
        ? { "Idempotency-Key": orderKey }
        : {}),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(30000),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Không xử lý được yêu cầu.",
    );
    error.status = response.status;
    throw error;
  }
  return result;
}
function modal(title, body, productView = false) {
  dialog.classList.toggle("product-dialog", productView);
  $("#dialog-title").textContent = title;
  $("#dialog-content").replaceChildren(body);
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}
$("#close-dialog").onclick = () => dialog.close();
function fields(form, specs, values = {}) {
  const grid = el("div", { class: "form-grid" });
  for (const [name, label, type, options] of specs) {
    const input = options
      ? el(
          "select",
          { name },
          options.map(([value, text]) => el("option", { value }, text)),
        )
      : el(type === "textarea" ? "textarea" : "input", {
          name,
          type: type === "textarea" ? undefined : type || "text",
          required: true,
          maxLength: name === "address" ? 500 : 200,
          min: type === "number" ? 0 : undefined,
          step: type === "number" ? 1 : undefined,
        });
    if (values[name] !== undefined) input.value = values[name];
    grid.append(
      el("label", { class: name === "address" ? "full" : "" }, label, input),
    );
  }
  form.append(grid);
  return grid;
}
function formData(form) {
  return Object.fromEntries(new FormData(form));
}
function persist() {
  localStorage.setItem("th360-cart", JSON.stringify(state.cart));
  sessionStorage.setItem("th360-interest", state.interest);
  cartBar();
}
function visibleProduct(id) {
  return state.data?.products.find((p) => p.id === Number(id));
}
function currentCart() {
  return Object.entries(state.cart)
    .filter(([id, n]) => Number.isSafeInteger(n) && n > 0)
    .map(([id, n]) => ({ product_id: Number(id), quantity: n }));
}
function cartBar() {
  const count = currentCart().reduce((sum, i) => sum + i.quantity, 0);
  const total = currentCart().reduce(
    (sum, i) => sum + (visibleProduct(i.product_id)?.price || 0) * i.quantity,
    0,
  );
  $("#cart-count").textContent = count;
  $("#dock-total").textContent = count ? money(total) : "Chưa chọn món";
  $("#dock-note").textContent = state.combo
    ? "Giá combo được tính lại trước khi đặt"
    : count
      ? "Tạm tính tiền hàng · chưa gồm phí giao"
      : "Khám phá tiệm gần nhà";
}
function add(product, n = 1) {
  if (!Number.isSafeInteger(n) || n < 1)
    throw new Error("Số lượng cần là số nguyên lớn hơn 0.");
  if ((state.cart[product.id] || 0) + n > product.stock)
    throw new Error("Số lượng vượt tồn bán được.");
  state.cart[product.id] = (state.cart[product.id] || 0) + n;
  state.interest = product.category;
  persist();
  toast("Đã thêm " + product.product_name);
}
function timeText(value) {
  return value
    ? new Date(value + "+07:00").toLocaleString("vi-VN", {
        timeZone: "Asia/Ho_Chi_Minh",
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
}
function image(p) {
  return p.image_path
    ? el("img", { src: p.image_path, alt: p.product_name, loading: "lazy" })
    : el(
        "span",
        { class: "glyph", ariaHidden: true },
        glyph[p.storage_kind] || "🛒",
      );
}
function productCard(p) {
  return el(
    "article",
    { class: "product" },
    (() => {
      const b = button("", () => productDetail(p), "product-art");
      b.setAttribute("aria-label", "Xem " + p.product_name);
      return b;
    })(),
    button(p.product_name, () => productDetail(p), "product-name"),
    el("p", { class: "muted" }, p.unit + " · " + types[p.storage_kind]),
    p.sale
      ? el(
          "span",
          { class: "badge" },
          p.sale.name +
            " · −" +
            Math.round(((p.regular_price - p.price) * 100) / p.regular_price) +
            "%",
        )
      : null,
    p.sell_until
      ? el("p", { class: "countdown" }, "Nhận trước " + timeText(p.sell_until))
      : null,
    el(
      "div",
      { class: "price-row" },
      el("span", { class: "price" }, money(p.price)),
      button(p.stock ? "+ Thêm" : "Hết hàng", () => add(p), "add-product"),
    ),
    el("small", { class: "muted" }, p.reason),
    p.catalog_origin === "REFERENCE"
      ? el(
          "small",
          { class: "muted reference-label" },
          p.stock
            ? "Giá tham khảo · tiệm xác nhận"
            : "Giá tham khảo · chờ nhập kho",
        )
      : null,
  );
}
function renderProducts() {
  const all = state.filtered || state.data.products;
  $("#products").replaceChildren(
    ...all.slice(0, state.page).map((p) => {
      const card = productCard(p);
      card.querySelector(".product-art").append(image(p));
      if (!p.stock) card.querySelector(".add-product").disabled = true;
      return card;
    }),
  );
  if (!all.length)
    $("#products").append(
      el(
        "p",
        { class: "muted" },
        "Chưa có mặt hàng phù hợp. Thử danh mục hoặc từ khóa khác nhé.",
      ),
    );
  $("#more").hidden = state.page >= all.length;
}
function applyFilter() {
  let list = state.data.products.filter(
    (p) =>
      (!state.categoryGroup || p.category_group === state.categoryGroup) &&
      (!state.brand ||
        p.brand.trim().toLocaleLowerCase("vi") ===
          state.brand.trim().toLocaleLowerCase("vi")) &&
      (!state.category || p.category === state.category) &&
      (!state.storage || p.storage_kind === state.storage),
  );
  const q = $("#search")
    .value.trim()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .toLowerCase();
  if (q)
    list = list.filter((p) =>
      (p.product_name + " " + p.sku + " " + p.category)
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/đ/g, "d")
        .toLowerCase()
        .includes(q),
    );
  if ($("#sort").value === "price") list.sort((a, b) => a.price - b.price);
  state.filtered = list;
  state.page = 24;
  renderProducts();
  $("#catalog-title").textContent = state.brand
    ? "Sản phẩm " + state.brand
    : state.category || "Gợi ý cho bạn";
  $("#recommendation-note").textContent = state.interest
    ? "Có thêm gợi ý từ " +
      state.interest +
      ". Bạn luôn có thể đổi danh mục và cách sắp xếp."
    : "Gợi ý từ hàng có sẵn và lịch sử mua chung tại tiệm.";
}
async function load() {
  const number = ++requestNumber;
  const data = await api(
    "/catalog?cart=" +
      currentCart()
        .map((i) => i.product_id)
        .join(",") +
      "&interest=" +
      encodeURIComponent(state.interest) +
      "&sort=" +
      $("#sort").value,
  );
  if (number !== requestNumber) return;
  state.data = data;
  state.offset = new Date(data.server_time + "+07:00").getTime() - Date.now();
  $("#store-name").textContent = data.settings.store_name;
  $("#zone").replaceChildren(
    el("option", { value: "" }, "Chọn khu/phường/chung cư"),
    ...data.zones.map((z) => el("option", { value: z.id }, z.name)),
  );
  if (!data.zones.some((z) => String(z.id) === state.zone))
    state.zone = data.zones.length === 1 ? String(data.zones[0].id) : "";
  $("#zone").value = state.zone;
  zoneNote();
  $("#categories").replaceChildren(
    button(
      "Tất cả",
      () => {
        state.category = "";
        applyFilter();
        categoriesActive();
      },
      state.category ? "" : "active",
    ),
    ...(state.categoryGroup
      ? data.category_groups.find((g) => g.name === state.categoryGroup)
          ?.categories || []
      : [
          "Snack & bim bim",
          "Bánh quy",
          "Kẹo dẻo & marshmallow",
          "Sữa tươi",
          "Nước ngọt",
          "Mì ăn liền",
          "Rau lá",
          "Trái cây tươi",
        ].filter((c) => data.categories.includes(c))
    ).map((c) =>
      button(
        c,
        () => {
          state.category = c;
          applyFilter();
          categoriesActive();
        },
        state.category === c ? "active" : "",
      ),
    ),
  );
  $("#category-group").replaceChildren(
    el("option", { value: "" }, "Tất cả nhóm hàng"),
    ...data.category_groups.map((g) => el("option", { value: g.name }, g.name)),
  );
  $("#category-group").value = state.categoryGroup;
  $("#brand").replaceChildren(
    el("option", { value: "" }, "Tất cả nhãn hàng"),
    ...data.brands.map((brand) => el("option", { value: brand }, brand)),
  );
  $("#brand").value = state.brand;
  renderBanners();
  renderCombos();
  applyFilter();
  cartBar();
}
function categoriesActive() {
  $("#categories")
    .querySelectorAll("button")
    .forEach((b) =>
      b.classList.toggle(
        "active",
        b.textContent === (state.category || "Tất cả"),
      ),
    );
}
function zoneNote() {
  const saved = state.user?.saved_address;
  $("#saved-address-summary").textContent = saved
    ? `${saved.receiver} · ${saved.phone} · ${saved.address}`
    : "";
  $("#saved-address-summary").hidden = !saved;
  $("#edit-address").textContent = saved
    ? "Thay đổi địa chỉ"
    : "Nhập địa chỉ nhận";

  const zone = state.data?.zones.find((z) => String(z.id) === state.zone);
  $("#delivery-note").textContent = zone
    ? "Phí " +
      money(zone.fee) +
      " · " +
      (zone.eta || state.data.settings.delivery_note) +
      (zone.minimum_order ? " · Đơn từ " + money(zone.minimum_order) : "")
    : state.data?.zones.length
      ? "Chọn khu vực để xem phí giao."
      : "Tiệm chưa mở vùng giao online; bạn có thể xem hàng.";
}
function renderBanners() {
  const banners = state.data.banners.length
    ? state.data.banners
    : [
        {
          title: "Một bữa sáng thảnh thơi hơn.",
          image_path: "/static/shop-hero-groceries.svg",
          subtitle: "Chọn bánh, thêm sữa. Phần còn lại để tiệm lo.",
          theme: "GREEN",
        },
        {
          title: "Chọn vừa đủ, dùng thật ngon.",
          subtitle: "Tự điều chỉnh giỏ theo ngân sách của bạn.",
          theme: "ORANGE",
        },
        {
          title: "Kiểm hàng khi nhận.",
          subtitle: "Tiền và điểm tính theo phần bạn nhận thực tế.",
          theme: "BLUE",
        },
      ];
  $("#banners").replaceChildren(
    ...banners.slice(0, 3).map((b, index) => {
      const item = el(
        "article",
        { class: "banner " + b.theme + (b.image_path ? " has-image" : "") },
        b.image_path ? el("img", { src: b.image_path, alt: "" }) : null,
        el(
          "span",
          { class: "sale-mark" },
          index === 0 ? "TIỆM GẦN NHÀ" : "CHỌN THÔNG MINH",
        ),
        el("h2", {}, b.title),
        el("p", {}, b.subtitle),
      );
      if (b.category)
        item.append(
          button("Khám phá ngay →", () => {
            state.category = b.category;
            applyFilter();
            categoriesActive();
            $("#catalog-title").scrollIntoView({ behavior: "smooth" });
          }),
        );
      return item;
    }),
  );
  const sales = state.data.products.filter((p) => p.sale);
  if (sales.length) {
    const ending = sales.map((p) => p.sale.ends_at).sort()[0];
    $("#banners").append(
      el(
        "article",
        { class: "banner ORANGE" },
        el("span", { class: "sale-mark" }, "GIỜ SALE VÀNG"),
        el("h2", {}, "Ưu đãi đúng giờ, giá tốt trong tầm tay."),
        el("p", {}, sales.length + " mặt hàng đang có giá theo khung giờ"),
        el("span", { class: "countdown" }),
      ),
    );
    const countdown =
      $("#banners").lastElementChild.querySelector(".countdown");
    countdown.dataset.ends = ending;
    tick();
  }
}
function tick() {
  document.querySelectorAll("[data-ends]").forEach((node) => {
    const diff = Math.max(
      0,
      new Date(node.dataset.ends + "+07:00").getTime() -
        Date.now() -
        state.offset,
    );
    node.textContent = diff
      ? "Còn " +
        Math.floor(diff / 3600000) +
        " giờ " +
        (Math.floor(diff / 60000) % 60) +
        " phút " +
        (Math.floor(diff / 1000) % 60) +
        " giây"
      : "Khung sale vừa kết thúc — giá được kiểm tra lại lúc đặt.";
  });
}
setInterval(tick, 1000);
function renderCombos() {
  $("#combo-section").hidden = !state.data.combos.length;
  $("#combos").replaceChildren(
    ...state.data.combos.map((c) =>
      el(
        "article",
        { class: "combo-card" },
        el(
          "span",
          { class: "badge" },
          "Hàng dùng sớm · HSD " + c.expires_on.split("-").reverse().join("/"),
        ),
        el("h3", {}, c.name),
        el(
          "p",
          {},
          "1 " +
            c.product_unit +
            " " +
            c.product_name +
            " + 1 " +
            c.partner_unit +
            " " +
            c.partner_name,
        ),
        el("strong", { class: "price" }, money(c.price)),
        el(
          "small",
          {},
          c.condition + " Còn tối đa " + c.available_sets + " combo.",
        ),
        button(
          "Chọn combo",
          () => {
            if (state.combo && state.combo.id !== c.id)
              throw new Error(
                "Mỗi giỏ dùng một combo. Bỏ combo cũ trước khi đổi.",
              );
            for (const id of [c.product_id, c.partner_id]) {
              const p = visibleProduct(id);
              if (!p || p.stock < (state.cart[id] || 0) + 1)
                throw new Error("Không đủ hàng cho combo.");
            }
            for (const id of [c.product_id, c.partner_id])
              state.cart[id] = (state.cart[id] || 0) + 1;
            state.combo = { id: c.id, sets: (state.combo?.sets || 0) + 1 };
            persist();
            cartDialog();
          },
          "primary",
        ),
      ),
    ),
  );
}
async function productDetail(p) {
  state.interest = p.category;
  sessionStorage.setItem("th360-interest", p.category);
  const loading = el(
    "div",
    { class: "detail-loading", role: "status" },
    "Đang tải thông tin và gợi ý sản phẩm…",
  );
  modal("Chi tiết sản phẩm", loading, true);
  try {
    const details = await api("/products/" + p.id);
    if (!loading.isConnected || !dialog.open) return;
    state.offset =
      new Date(details.server_time + "+07:00").getTime() - Date.now();
    const remember = (product) => {
      const old = visibleProduct(product.id);
      if (old) Object.assign(old, product);
    };
    [details.product, ...details.cross_sell, ...details.related].forEach(
      remember,
    );
    const panel = productDetailPanel(details, {
      button,
      image,
      add,
      timeText,
      cartQuantity: (id) => state.cart[id] || 0,
      browseBrand: async (brand) => {
        state.brand = brand;
        state.category = state.categoryGroup = state.storage = "";
        $("#storage").value = "";
        $("#search").value = "";
        dialog.close();
        await load();
        $("#catalog-title").scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      },
      browseCategory: async (product) => {
        state.brand = "";
        state.storage = "";
        $("#storage").value = "";
        $("#search").value = "";
        state.category = product.category;
        state.categoryGroup = product.category_group;
        dialog.close();
        await load();
        $("#catalog-title").scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      },
      buyNow: async (product, count) => {
        add(product, count);
        await cartDialog();
      },
    });
    panel.addEventListener("open-product", (event) =>
      productDetail(event.detail),
    );
    modal("Chi tiết sản phẩm", panel, true);
    tick();
    cartBar();
  } catch (error) {
    if (!loading.isConnected || !dialog.open) return;
    loading.replaceChildren(
      el("p", { class: "error", role: "alert" }, error.message),
      button("Thử tải lại", () => productDetail(p)),
    );
  }
}
async function budgetDialog(kind) {
  const amount = kind === "breakfast" ? 50000 : 150000;
  const data = await api("/budget?amount=" + amount + "&kind=" + kind);
  const body = el("div", {}, el("p", { class: "muted" }, data.note));
  const controls = data.items.map((p) => {
    const check = el("input", {
      type: "checkbox",
      checked: true,
      ariaLabel: "Chọn " + p.product_name,
    });
    const input = el("input", {
      type: "number",
      min: 1,
      max: p.stock,
      step: 1,
      value: 1,
      ariaLabel: "Số lượng " + p.product_name,
    });
    body.append(
      el(
        "div",
        { class: "budget-line" },
        check,
        el(
          "div",
          {},
          el("strong", {}, p.product_name),
          el("p", { class: "muted" }, money(p.price) + " / " + p.unit),
        ),
        input,
      ),
    );
    return { p, check, input };
  });
  const sum = el("p", { class: "notice", role: "status" });
  function total() {
    return controls.reduce(
      (s, c) => s + (c.check.checked ? c.p.price * Number(c.input.value) : 0),
      0,
    );
  }
  function update() {
    sum.textContent =
      "Tạm tính " +
      money(total()) +
      " · ngân sách " +
      money(amount) +
      " · chưa gồm phí giao";
  }
  controls.forEach((c) => {
    c.check.onchange = update;
    c.input.oninput = update;
  });
  body.append(
    sum,
    el(
      "div",
      { class: "actions" },
      button("Đóng", () => dialog.close()),
      button(
        "Thêm các món đã chọn",
        () => {
          if (total() > amount)
            throw new Error(
              "Giỏ đang vượt ngân sách; hãy giảm hoặc bỏ một món.",
            );
          const selected = controls.filter((c) => c.check.checked);
          if (!selected.length) throw new Error("Chọn ít nhất một món.");
          for (const c of selected)
            if (
              !Number.isSafeInteger(Number(c.input.value)) ||
              Number(c.input.value) < 1 ||
              (state.cart[c.p.id] || 0) + Number(c.input.value) > c.p.stock
            )
              throw new Error("Kiểm tra số lượng và tồn trước khi thêm.");
          for (const c of selected)
            state.cart[c.p.id] =
              (state.cart[c.p.id] || 0) + Number(c.input.value);
          persist();
          dialog.close();
          cartDialog();
        },
        "primary",
      ),
    ),
  );
  if (!controls.length)
    body.prepend(el("p", {}, "Chưa có đủ hàng phù hợp ngân sách này."));
  update();
  modal(
    kind === "breakfast" ? "Bữa sáng dưới 50.000đ" : "Thiết yếu dưới 150.000đ",
    body,
  );
}
function applySavedAddress(saved) {
  state.address = saved || null;
  state.zone = saved?.zone_available ? String(saved.zone_id) : "";
  if (state.data) {
    if (!state.data.zones.some((z) => String(z.id) === state.zone))
      state.zone =
        state.data.zones.length === 1 ? String(state.data.zones[0].id) : "";
    $("#zone").value = state.zone;
  }
  zoneNote();
}
async function editDeliveryAddress(after) {
  if (!state.user) return authDialog(() => editDeliveryAddress(after));
  const accountId = state.user.id;
  const address = await addressPicker(api, state.address || {});
  const form = el("form");
  fields(
    form,
    [
      ["receiver", "Người nhận", "text"],
      ["phone", "Số điện thoại nhận hàng", "tel"],
      [
        "zone_id",
        "Khu giao của tiệm",
        "text",
        [
          ["", "Chọn khu giao"],
          ...(state.data?.zones || []).map((z) => [
            z.id,
            z.name + " · " + money(z.fee),
          ]),
        ],
      ],
    ],
    {
      receiver: state.address?.receiver || state.user.name,
      phone: state.address?.phone || state.user.phone,
      zone_id: state.zone,
    },
  );
  if (!state.data?.zones.length) form.elements.zone_id.required = false;
  form.append(
    address.element,
    el(
      "p",
      { class: "hint" },
      "Địa chỉ được lưu riêng cho tài khoản và tự điền vào những lần mua sau. Bạn có thể thay đổi khi muốn nhận ở nơi khác.",
    ),
  );
  const error = el("p", { class: "error", role: "alert" });
  const save = el(
    "button",
    { type: "submit", class: "primary" },
    "Lưu địa chỉ cho lần sau",
  );
  form.append(error, el("div", { class: "actions" }, save));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    error.textContent = "";
    try {
      const result = await api(
        "/address",
        {
          ...address.value(),
          expected_account_id: accountId,
          receiver: form.elements.receiver.value,
          phone: form.elements.phone.value,
          zone_id: form.elements.zone_id.value
            ? Number(form.elements.zone_id.value)
            : null,
        },
        "PUT",
      );
      if (state.user?.id !== accountId)
        throw Error("Tài khoản đã thay đổi. Hãy tải lại trang.");
      state.user.saved_address = result.saved_address;
      applySavedAddress(result.saved_address);
      dialog.close();
      toast("Đã lưu địa chỉ cho tài khoản. Lần sau bạn không cần nhập lại.");
      window.dispatchEvent(
        new CustomEvent("saved-delivery-address", {
          detail: { accountId, saved: result.saved_address },
        }),
      );
      if (after) await after();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  });
  modal(
    state.user.saved_address
      ? "Thay đổi địa chỉ nhận hàng"
      : "Lưu địa chỉ nhận hàng lần đầu",
    form,
  );
}

async function refreshUser() {
  const previous = state.user?.id;
  try {
    state.user = await api("/me");
  } catch (error) {
    if (error.status !== 401) throw error;
    state.user = null;
  }
  if (previous !== state.user?.id) {
    state.address = null;
    state.zone = "";
    errandView?.close();
    errandView = null;
    errandStream?.close();
    errandStream = null;
    document.getElementById("errand-inline").hidden = true;
    document.getElementById("browse").hidden = false;
    document.querySelector(".cart-dock").hidden = false;
  }
  applySavedAddress(state.user?.saved_address);
  startErrandNotifications().catch(() => {});
  $("#account").textContent = state.user
    ? state.user.name + " · " + state.user.points + " điểm"
    : "Đăng nhập";
}
function authDialog(after, register = false) {
  const body = el("div");
  const form = el("form");
  const specs = register
    ? [
        ["name", "Họ tên", "text"],
        ["phone", "Số điện thoại", "tel"],
        ["password", "Mật khẩu từ 10 ký tự", "password"],
        ["confirm_password", "Xác nhận mật khẩu", "password"],
      ]
    : [
        ["phone", "Số điện thoại", "tel"],
        ["password", "Mật khẩu", "password"],
      ];
  fields(form, specs);
  const error = el("p", { class: "error", role: "alert" });
  const submit = el(
    "button",
    { type: "submit", class: "primary" },
    register ? "Tạo tài khoản" : "Đăng nhập",
  );
  form.append(error, el("div", { class: "actions" }, submit));
  form.onsubmit = async (event) => {
    event.preventDefault();
    submit.disabled = true;
    error.textContent = "";
    try {
      const data = formData(form);
      if (register) await api("/register", data);
      await api("/login", data);
      await refreshUser();
      dialog.close();
      if (!state.user.saved_address) await editDeliveryAddress(after);
      else if (after) await after();
      else accountDialog();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      submit.disabled = false;
    }
  };
  body.append(
    el(
      "p",
      { class: "notice" },
      "Đăng nhập khi đặt mua để quản lý đơn và tích điểm theo hàng thực nhận.",
    ),
    form,
    button(
      register ? "Đã có tài khoản? Đăng nhập" : "Chưa có tài khoản? Đăng ký",
      () => authDialog(after, !register),
    ),
  );
  modal(register ? "Tạo tài khoản khách hàng" : "Đăng nhập khách hàng", body);
}
function accountDialog() {
  if (!state.user) return authDialog();
  const ledger = el("div");
  state.user.ledger
    .slice(0, 12)
    .forEach((item) =>
      ledger.append(
        el(
          "div",
          { class: "order-item" },
          el("span", {}, item.reason),
          el("b", {}, (item.amount > 0 ? "+" : "") + item.amount + " điểm"),
        ),
      ),
    );
  modal(
    "Tài khoản của bạn",
    el(
      "div",
      {},
      el("h3", {}, state.user.name),
      el(
        "p",
        { class: "notice" },
        state.user.points +
          " điểm · 1 điểm = 100đ. Tích 1 điểm mỗi 10.000đ tiền hàng thực nhận.",
      ),
      ledger,
      el(
        "div",
        { class: "actions" },
        button("Đơn của tôi", () => myOrders()),
        button("Đăng xuất", async () => {
          await api("/logout", {});
          state.user = null;
          dialog.close();
          await refreshUser();
        }),
      ),
    ),
  );
}
async function cartDialog() {
  await load();
  const items = currentCart();
  const body = el("div");
  if (!items.length) {
    modal(
      "Giỏ của bạn",
      el("p", {}, "Chưa có món nào. Chọn vài món từ tiệm nhé."),
    );
    return;
  }
  for (const item of items) {
    const p = visibleProduct(item.product_id);
    const input = el("input", {
      type: "number",
      min: 1,
      max: p?.stock || item.quantity,
      step: 1,
      value: item.quantity,
      ariaLabel: "Số lượng " + (p?.product_name || "mặt hàng"),
    });
    input.onchange = () => {
      const n = Number(input.value);
      if (!Number.isSafeInteger(n) || n < 1) {
        input.value = item.quantity;
        return;
      }
      state.cart[item.product_id] = n;
      persist();
      cartDialog();
    };
    body.append(
      el(
        "div",
        { class: "cart-row" },
        el(
          "div",
          {},
          el("strong", {}, p?.product_name || "Mặt hàng đã ngừng bán online"),
          el(
            "p",
            { class: "muted" },
            p ? money(p.price) + " / " + p.unit : "Hãy bỏ món này khỏi giỏ.",
          ),
        ),
        input,
        button("Bỏ", () => {
          delete state.cart[item.product_id];
          state.combo = null;
          persist();
          cartDialog();
        }),
      ),
    );
  }
  if (state.combo)
    body.append(
      el(
        "p",
        { class: "notice" },
        "Giỏ có " +
          state.combo.sets +
          " combo dùng sớm; giá và lượt được kiểm tra khi đặt.",
      ),
      button("Bỏ ưu đãi combo, giữ món", () => {
        state.combo = null;
        cartDialog();
      }),
    );
  const rec = state.data.products
    .filter((p) => p.stock > 0 && !state.cart[p.id])
    .slice(0, 3);
  if (rec.length)
    body.append(
      el("h3", { style: "margin-top:20px" }, "Bạn có muốn mua cùng?"),
      el(
        "div",
        { class: "related" },
        rec.map((p) =>
          el(
            "article",
            {},
            el("strong", {}, p.product_name),
            el("p", { class: "muted" }, p.reason),
            button("+ " + money(p.price), () => {
              add(p);
              cartDialog();
            }),
          ),
        ),
      ),
    );
  const zone = state.data.zones.find((z) => String(z.id) === state.zone);
  body.append(
    el(
      "div",
      { class: "cart-summary" },
      el("span", {}, "Phí giao khu đang chọn"),
      el("b", {}, zone ? money(zone.fee) : "Chọn vùng giao"),
    ),
    el(
      "div",
      { class: "actions" },
      button("Mua thêm", async () => {
        dialog.close();
        await load();
      }),
      button(
        state.user ? "Tiếp tục đặt giao" : "Đăng nhập để đặt giao",
        () => (state.user ? checkoutDialog() : authDialog(checkoutDialog)),
        "primary",
      ),
    ),
  );
  modal("Giỏ hàng của bạn", body);
}
async function checkoutDialog() {
  if (!state.user) return authDialog(checkoutDialog);
  if (!state.zone)
    throw new Error("Chọn khu giao ở đầu trang trước khi đặt hàng.");
  const form = el("form");
  fields(
    form,
    [
      ["receiver", "Người nhận", "text"],
      ["phone", "Số điện thoại nhận hàng", "tel"],
      [
        "substitution",
        "Nếu hết món",
        "text",
        [
          ["CALL", "Gọi trước khi thay món"],
          ["DROP", "Đề nghị bỏ món hết"],
          ["CONTACT", "Liên hệ lại để xác nhận đơn"],
        ],
      ],
      [
        "payment_method",
        "Thanh toán",
        "text",
        [
          ["COD", "Trả khi nhận hàng (COD)"],
          ["QR", "Chuyển khoản QR, tiệm xác nhận tiền"],
        ],
      ],
      ["points_used", "Điểm muốn đổi (1 điểm = 100đ)", "number"],
      ["note", "Ghi chú giao hàng", "text"],
    ],
    {
      receiver: state.address?.receiver || state.user.name,
      phone: state.address?.phone || state.user.phone,
      points_used: 0,
      note: "",
    },
  );
  const address = await addressPicker(api, state.address || {});
  const saved = state.user.saved_address;
  const addressDetails = el(
    "details",
    { class: "checkout-saved-address full", open: !saved },
    el(
      "summary",
      {},
      saved ? "Địa chỉ đã lưu · bấm để thay đổi" : "Nhập địa chỉ nhận hàng",
    ),
    address.element,
  );
  if (saved)
    addressDetails.prepend(
      el("p", { class: "address-preview" }, saved.address),
    );
  form.querySelector(".form-grid").prepend(addressDetails);
  form.addEventListener(
    "invalid",
    () => {
      addressDetails.open = true;
    },
    true,
  );
  form.elements.note.required = false;
  const result = el("div");
  const error = el("p", { class: "error", role: "alert" });
  const calculate = el(
    "button",
    { type: "submit", class: "primary" },
    "Kiểm tra giá & phí giao",
  );
  let latest = null;
  const placeButton = button(
    "Xác nhận đặt hàng",
    async () => {
      if (!latest) throw new Error("Hãy kiểm tra lại giá trước khi đặt.");
      const payload = {
        ...latest.input,
        fingerprint: latest.quote.fingerprint,
      };
      const hash = JSON.stringify(payload);
      if (hash !== orderFingerprint) {
        orderKey = crypto.randomUUID();
        orderFingerprint = hash;
      }
      const placed = await api("/orders", payload);
      state.cart = {};
      state.combo = null;
      persist();
      dialog.close();
      history.replaceState({}, "", "/shop/track/" + placed.token);
      await showTrack(placed.token);
      await refreshUser();
      toast(
        payload.payment_method === "QR"
          ? "Đã tạo đơn và giữ hàng. Quét QR bên dưới, rồi bấm Xác nhận đã thanh toán để cửa hàng duyệt."
          : "Tiệm đã nhận yêu cầu. Bạn có thể kiểm hàng và trả tiền khi nhận.",
      );
      orderKey = orderFingerprint = null;
    },
    "primary",
  );
  placeButton.hidden = true;
  form.append(
    error,
    result,
    el("div", { class: "actions" }, calculate, placeButton),
  );
  form.addEventListener("input", () => {
    latest = null;
    placeButton.hidden = true;
  });
  form.addEventListener("change", () => {
    latest = null;
    placeButton.hidden = true;
  });
  form.onsubmit = async (event) => {
    event.preventDefault();
    calculate.disabled = true;
    error.textContent = "";
    try {
      const input = {
        ...formData(form),
        ...address.value(),
        zone_id: Number(state.zone),
        points_used: Number(form.elements.points_used.value),
        items: currentCart(),
        ...(state.combo
          ? {
              rescue_campaign_id: state.combo.id,
              rescue_sets: state.combo.sets,
            }
          : {}),
      };
      const q = await api("/quote", input);
      state.address = address.value();
      latest = { input, quote: q };
      result.replaceChildren(
        el(
          "div",
          { class: "notice" },
          "Đổi " +
            q.points_used +
            " điểm. Điểm mới chỉ cộng sau kiểm nhận thành công.",
        ),
        el(
          "div",
          { class: "cart-summary" },
          el("span", {}, "Tiền hàng sau ưu đãi/đổi điểm"),
          el("b", {}, money(q.goods_total)),
        ),
        el(
          "div",
          { class: "cart-summary" },
          el("span", {}, "Phí giao"),
          el("b", {}, money(q.shipping_fee)),
        ),
        el(
          "div",
          { class: "cart-summary total" },
          el("span", {}, "Tổng thanh toán"),
          el("b", {}, money(q.total)),
        ),
        el(
          "p",
          { class: "muted" },
          q.eta +
            (q.payment_method === "QR"
              ? " · Sau khi đặt, tiệm giữ hàng 30 phút. Quét QR rồi xác nhận đã thanh toán để cửa hàng đối chiếu và duyệt đơn."
              : " · Có thể kiểm hàng khi nhận. Đơn COD chờ tiệm xác nhận tối đa 30 phút."),
        ),
      );
      placeButton.hidden = false;
    } catch (err) {
      error.textContent = err.message;
    } finally {
      calculate.disabled = false;
    }
  };
  modal("Đặt giao · kiểm hàng khi nhận", form);
}
function orderCard(order, privateView = false, paymentActions = {}) {
  const card = el(
    "article",
    { class: "order-card" },
    el(
      "h3",
      {},
      order.code +
        " · " +
        (order.status === "PENDING" && order.payment_flow === "PREPAY"
          ? "Chờ bạn quét QR thanh toán"
          : statuses[order.status]),
    ),
    el(
      "p",
      {},
      "Tiền hàng " +
        money(order.goods_total) +
        " · giao " +
        money(order.shipping_fee),
    ),
    el(
      "p",
      {},
      "Đã nhận tiền " +
        money(order.paid) +
        " · cần hoàn " +
        money(order.refund_due) +
        " · đã hoàn " +
        money(order.refund_paid),
    ),
    el(
      "p",
      { class: "notice" },
      "Điểm sử dụng " +
        order.points_used +
        " · điểm tích sau kiểm nhận " +
        order.points_earned,
    ),
  );
  const payment = qrPayment(order, {
    button,
    modal,
    privateView,
    refresh: paymentActions.refresh || myOrders,
    login: paymentActions.login || (() => authDialog(myOrders)),
    report: async () => {
      if (!privateView) return authDialog(paymentActions.refresh || myOrders);
      await api("/orders/" + order.id + "/report-payment", {});
      toast("Đã báo chuyển khoản. Chờ cửa hàng đối chiếu và duyệt.");
      await (paymentActions.refresh || myOrders)();
    },
  });
  if (payment) card.append(payment);
  if (order.invoice && privateView)
    card.append(
      el(
        "p",
        { class: "notice" },
        "Cửa hàng đã duyệt · ",
        el(
          "a",
          {
            class: "link",
            href: "/shop/orders/" + order.id + "/invoice",
            target: "_blank",
            rel: "noopener",
          },
          "Mở / in hóa đơn " + order.invoice.code,
        ),
      ),
    );
  if (privateView)
    card.append(
      el("p", {}, order.receiver + " · " + order.phone + " · " + order.address),
    );
  for (const i of order.items)
    card.append(
      el(
        "div",
        { class: "order-item" },
        el(
          "span",
          {},
          i.product_name +
            " · " +
            i.quantity +
            " " +
            i.unit +
            (i.accepted !== null ? " · thực nhận " + i.accepted : ""),
        ),
        el("span", {}, money(i.charged_total)),
      ),
    );
  if (order.status === "REVIEW" && privateView && !order.approved)
    card.append(
      el(
        "p",
        { class: "notice" },
        "Tiệm đã đề nghị điều chỉnh do thiếu hàng. Kiểm tra món và tổng tiền ở trên trước khi đồng ý.",
      ),
      button(
        "Đồng ý phương án này",
        async () => {
          await api("/orders/" + order.id + "/approve", {
            version: order.version,
          });
          await myOrders();
        },
        "primary",
      ),
    );
  if (order.tracking_token)
    card.append(
      el(
        "p",
        {},
        "Lưu liên kết theo dõi riêng: ",
        el(
          "a",
          { class: "link", href: "/shop/track/" + order.tracking_token },
          "Theo dõi " + order.code,
        ),
      ),
    );
  card.append(
    el(
      "ol",
      { class: "event-list" },
      order.events.map((event) =>
        el("li", {}, timeText(event.created_at) + " · " + event.note),
      ),
    ),
  );
  return card;
}
async function myOrders() {
  await refreshUser();
  if (!state.user) return authDialog(myOrders);
  const orders = await api("/orders");
  dialog.close();
  $("#browse").hidden = true;
  $("#order-page").hidden = false;
  $("#order-page").replaceChildren(
    button("← Tiếp tục mua sắm", () => {
      history.replaceState({}, "", "/shop");
      $("#order-page").hidden = true;
      $("#browse").hidden = false;
      load();
    }),
    el("h2", {}, "Đơn hàng & tích điểm"),
    ...orders.map((order) => orderCard(order, true)),
  );
  if (!orders.length)
    $("#order-page").append(
      el("p", { class: "notice" }, "Bạn chưa có đơn online."),
    );
}
async function showTrack(token) {
  await refreshUser();
  let order = await api("/track/" + encodeURIComponent(token));
  let privateView = false;
  if (state.user) {
    try {
      order = await api("/orders/" + order.id);
      privateView = true;
    } catch (error) {
      if (![401, 404].includes(error.status)) throw error;
    }
  }
  $("#browse").hidden = true;
  $("#order-page").hidden = false;
  $("#order-page").replaceChildren(
    button("← Về cửa hàng", () => {
      history.replaceState({}, "", "/shop");
      $("#order-page").hidden = true;
      $("#browse").hidden = false;
      load();
    }),
    orderCard(order, privateView, {
      refresh: () => showTrack(token),
      login: () => authDialog(() => showTrack(token)),
    }),
    button("Tải lại tiến độ", () => showTrack(token)),
    button("Mở đơn của tôi / QR thanh toán", () => myOrders(), "primary"),
  );
}
$("#zone").onchange = async () => {
  const accountId = state.user?.id;
  const old = state.zone;
  state.zone = $("#zone").value;
  zoneNote();
  if (!state.user?.saved_address) return;
  $("#zone").disabled = true;
  try {
    const result = await api(
      "/address",
      {
        expected_account_id: accountId,
        zone_id: state.zone ? Number(state.zone) : null,
      },
      "PUT",
    );
    if (state.user?.id !== accountId) return;
    state.user.saved_address = result.saved_address;
    window.dispatchEvent(
      new CustomEvent("saved-delivery-address", {
        detail: { accountId, saved: result.saved_address },
      }),
    );
  } catch (error) {
    state.zone = old;
    $("#zone").value = old;
    zoneNote();
    toast(error.message);
  } finally {
    $("#zone").disabled = false;
  }
};
$("#category-group").onchange = () => {
  state.categoryGroup = $("#category-group").value;
  state.category = "";
  load().catch((e) => toast(e.message));
};
$("#edit-address").onclick = () =>
  editDeliveryAddress().catch((error) => toast(error.message));
$("#search").oninput = applyFilter;
$("#storage").onchange = () => {
  state.storage = $("#storage").value;
  applyFilter();
};
$("#sort").onchange = () => load();
$("#brand").onchange = () => {
  state.brand = $("#brand").value;
  applyFilter();
};
$("#more").onclick = () => {
  state.page += 24;
  renderProducts();
};
$("#account").onclick = accountDialog;
$("#my-orders").onclick = () => myOrders().catch((e) => toast(e.message));
$("#cart-button").onclick = $("#dock-cart").onclick = () =>
  cartDialog().catch((e) => toast(e.message));
document
  .querySelectorAll("[data-budget]")
  .forEach(
    (b) =>
      (b.onclick = () =>
        budgetDialog(b.dataset.budget).catch((e) => toast(e.message))),
  );
$("#fresh-button").onclick = () => {
  state.storage = "FRESH";
  $("#storage").value = "FRESH";
  applyFilter();
  $("#catalog-title").scrollIntoView({ behavior: "smooth" });
};
async function init() {
  await Promise.all([load(), refreshUser()]);
  if (document.body.dataset.track) await showTrack(document.body.dataset.track);
  else if (state.user && !state.user.saved_address) await editDeliveryAddress();
}
let trackingPoll = false;
setInterval(async () => {
  const match = location.pathname.match(/^\/shop\/track\/([a-f0-9]{64})$/);
  if (
    !match ||
    document.hidden ||
    dialog.open ||
    trackingPoll ||
    $("#order-page").hidden
  )
    return;
  trackingPoll = true;
  try {
    await showTrack(match[1]);
  } catch {
  } finally {
    trackingPoll = false;
  }
}, 8000);
init().catch((error) => ($("#page-error").textContent = error.message));

let errandView = null,
  errandStream = null;
async function openErrands(event) {
  event?.preventDefault();
  if (!state.user) {
    authDialog(() => openErrands());
    return;
  }
  document.getElementById("browse").hidden = true;
  document.querySelector(".cart-dock").hidden = true;
  document.getElementById("errand-inline").hidden = false;
  document.getElementById("modal-close").onclick = () =>
    document.getElementById("modal").close();
  if (!errandView) {
    const module = await import("./errands-shop.js?v=2");
    errandView = module.mountErrands(document.getElementById("errand-root"));
  }
  document
    .getElementById("errand-inline")
    .scrollIntoView({ behavior: "smooth", block: "start" });
}
document.getElementById("errand-entry").addEventListener("click", openErrands);
document
  .getElementById("errand-service-open")
  .addEventListener("click", openErrands);
document.getElementById("errand-back").addEventListener("click", () => {
  document.getElementById("errand-inline").hidden = true;
  document.getElementById("browse").hidden = false;
  document.querySelector(".cart-dock").hidden = false;
  errandView?.close();
  errandView = null;
});
async function startErrandNotifications() {
  if (!state.user) {
    errandStream?.close();
    errandStream = null;
    return;
  }
  if (errandStream) return;
  const { connectErrands } = await import("./errands-live.js?v=2");
  errandStream = connectErrands("/api/shop/errands/events", async () => {
    const [result] = await Promise.all([api("/errands"), refreshUser()]);
    const waiting = result.orders.filter((o) =>
      ["ESTIMATE_REVIEW", "CHANGE_REVIEW", "FINAL_REVIEW"].includes(o.status),
    ).length;
    const badge = document.getElementById("errand-notifications");
    if (badge) badge.textContent = waiting ? `(${waiting} cần duyệt)` : "";
  });
}

window.addEventListener("saved-delivery-address", (event) => {
  if (state.user?.id !== event.detail.accountId) return;
  state.user.saved_address = event.detail.saved;
  applySavedAddress(event.detail.saved);
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshUser().catch(() => {});
});
