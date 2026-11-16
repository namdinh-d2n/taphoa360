import {
  api,
  el,
  button,
  toolbar,
  table,
  money,
  qty,
  field,
  readFields,
  showModal,
  closeModal,
  replace,
  toast,
  refresh,
  tabs,
  today,
} from "./ui.js?v=3.1";
import { invoiceAssistant } from "./invoice-ai.js?v=3.1";

const normalize = (text) =>
  String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
const text = (name, label, extra = {}) => ({ name, label, ...extra });
const number = (name, label, value = 0, extra = {}) => ({
  name,
  label,
  type: "number",
  value,
  ...extra,
});

// Keep the chosen ID separate from typed text, including when names are identical.
function productPicker(getProducts, onSelect) {
  const id = "product-" + crypto.randomUUID();
  const input = el("input", {
    id,
    type: "text",
    placeholder: "Gõ tên, SKU hoặc mã vạch",
    required: true,
    role: "combobox",
    ariaAutocomplete: "list",
    ariaExpanded: "false",
    ariaControls: id + "-list",
    autocomplete: "off",
  });
  const list = el("div", {
    id: id + "-list",
    role: "listbox",
    class: "product-options",
    hidden: true,
  });
  let matches = [],
    highlighted = -1;
  function hide() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  function choose(product) {
    input.value = product.product_name;
    onSelect(product);
    hide();
  }
  function draw() {
    const term = normalize(input.value.trim());
    matches = getProducts()
      .filter((p) =>
        normalize(
          [p.product_name, p.sku, p.barcode, p.supplier_sku].join(" "),
        ).includes(term),
      )
      .slice(0, 30);
    highlighted = -1;
    input.removeAttribute("aria-activedescendant");
    replace(
      list,
      matches.length
        ? matches.map((p, index) => {
            const option = el(
              "button",
              {
                id: id + "-option-" + index,
                type: "button",
                role: "option",
                tabIndex: -1,
                onmousedown: (event) => event.preventDefault(),
                onclick: () => choose(p),
              },
              el("strong", {}, p.product_name),
              el(
                "small",
                {},
                p.sku +
                  " · " +
                  p.unit +
                  " · " +
                  money(p.supplier_cost_price ?? p.cost_price),
              ),
            );
            return option;
          })
        : el(
            "p",
            { class: "muted" },
            "Chưa có sản phẩm phù hợp trong danh mục.",
          ),
    );
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }
  input.addEventListener("input", () => {
    onSelect(null);
    draw();
  });
  input.addEventListener("focus", draw);
  input.addEventListener("blur", hide);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !list.hidden) {
      event.preventDefault();
      event.stopPropagation();
      hide();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) draw();
      if (!matches.length) return;
      highlighted =
        highlighted < 0
          ? event.key === "ArrowDown"
            ? 0
            : matches.length - 1
          : (highlighted +
              (event.key === "ArrowDown" ? 1 : -1) +
              matches.length) %
            matches.length;
      [...list.children].forEach((node, index) => {
        node.setAttribute("aria-selected", String(index === highlighted));
        if (index === highlighted) {
          input.setAttribute("aria-activedescendant", node.id);
          node.scrollIntoView({ block: "nearest" });
        }
      });
    } else if (event.key === "Enter" && !list.hidden) {
      event.preventDefault();
      if (matches.length) choose(matches[highlighted >= 0 ? highlighted : 0]);
    }
  });
  return {
    element: el(
      "div",
      { class: "product-picker" },
      el("label", { htmlFor: id }, "Sản phẩm"),
      input,
      list,
    ),
    input,
    choose,
    clear: () => {
      input.value = "";
      onSelect(null);
      hide();
    },
  };
}

// An inline editor avoids replacing the purchase dialog and losing its draft.
async function catalogueEditor(
  supplier,
  {
    product,
    create = false,
    name = "",
    unit = "",
    costPrice = 0,
    onSaved,
    onCancel,
  },
) {
  let selected = product || null;
  const fields = [
    number(
      "cost_price",
      "Giá nhập từ nhà cung cấp",
      product?.supplier_cost_price ?? 0,
    ),
    text("supplier_sku", "Mã hàng nhà cung cấp", {
      required: false,
      maxLength: 64,
    }),
  ];
  if (create)
    fields.unshift(
      text("product_name", "Tên sản phẩm", { value: name, maxLength: 150 }),
      text("unit", "Đơn vị", { value: unit || "cái", maxLength: 30 }),
      number("price", "Giá bán"),
      text("sku", "SKU", {
        required: false,
        maxLength: 64,
        placeholder: "Để trống để tự tạo mã",
      }),
      text("barcode", "Mã vạch", { required: false, maxLength: 64 }),
    );
  const grid = el(
    "div",
    { class: "form-grid" },
    fields.map((spec) => field(spec, product?.[spec.name])),
  );
  // Product cost_price is global; this form always edits the supplier's own price.
  grid.querySelector('[name="cost_price"]').value =
    product?.supplier_cost_price ?? costPrice;
  const error = el("p", { class: "error", role: "alert" });
  const box = el(
    "section",
    { class: "inline-editor" },
    el(
      "h3",
      {},
      create
        ? "Thêm sản phẩm mới · " + supplier.name
        : product
          ? "Sửa giá nhập · " + product.product_name
          : "Thêm hàng có sẵn · " + supplier.name,
    ),
  );
  if (supplier.is_sample || product?.is_sample_price)
    box.append(
      el(
        "p",
        { class: "hint" },
        "Nhà cung cấp/giá nhập mẫu để tham khảo. Điền lại báo giá thực tế trước khi nhập hàng.",
      ),
    );
  if (!create && !product) {
    const products = (await api("/products")).filter((p) => p.active);
    const picker = productPicker(
      () => products,
      (p) => {
        selected = p;
        if (p)
          grid.querySelector('[name="cost_price"]').value = p.cost_price || 0;
      },
    );
    box.append(picker.element);
  }
  const save = button(
    "Lưu vào danh mục",
    async () => {
      error.textContent = "";
      const inputs = [...box.querySelectorAll("input")];
      if (inputs.some((input) => !input.reportValidity())) return;
      if (!create && !selected) {
        error.textContent = "Hãy chọn một sản phẩm từ kết quả tìm kiếm.";
        return;
      }
      const data = {};
      for (const spec of fields) {
        const input = grid.querySelector('[name="' + spec.name + '"]');
        data[spec.name] =
          spec.type === "number" ? Number(input.value) : input.value;
      }
      if (!create) data.product_id = selected.id;
      try {
        const result = await api(
          "/suppliers/" + supplier.id + "/products",
          data,
        );
        onSaved(result.product);
        toast(
          create
            ? "Đã tạo sản phẩm. Tồn kho chỉ tăng khi lưu phiếu nhập."
            : "Đã lưu danh mục nhà cung cấp",
        );
      } catch (err) {
        error.textContent = err.message;
      }
    },
    "primary",
  );
  box.append(
    grid,
    error,
    el(
      "div",
      { class: "form-actions" },
      button("Hủy thêm / sửa", onCancel),
      save,
    ),
  );
  return box;
}

export async function supplierProfile(supplier, selectedTab = "products") {
  const [products, entries] = await Promise.all([
    api("/suppliers/" + supplier.id + "/products"),
    api("/accounts/SUPPLIER/" + supplier.id),
  ]);
  let catalogue = products;
  const body = el("div"),
    nav = el("div");
  const search = el("input", {
    placeholder: "Tìm trong danh mục nhà cung cấp",
    ariaLabel: "Tìm sản phẩm cung cấp",
  });
  let editor = null;
  async function edit(options) {
    if (editor) {
      toast("Hãy lưu hoặc hủy phần thêm / sửa đang mở.");
      return;
    }
    const slot = el("div");
    editor = slot;
    body.prepend(slot);
    try {
      slot.append(
        await catalogueEditor(supplier, {
          ...options,
          onSaved: (product) => {
            catalogue = [
              ...catalogue.filter((p) => p.id !== product.id),
              product,
            ];
            editor = null;
            draw();
          },
          onCancel: () => {
            editor = null;
            draw();
          },
        }),
      );
      slot.querySelector("input")?.focus();
    } catch (err) {
      editor = null;
      slot.remove();
      throw err;
    }
  }
  function draw() {
    editor = null;
    replace(
      nav,
      tabs(
        [
          ["info", "Thông tin"],
          ["products", "Sản phẩm cung cấp"],
          ["debt", "Sổ công nợ"],
        ],
        selectedTab,
        (id) => {
          if (editor) {
            toast("Hãy lưu hoặc hủy phần thêm / sửa đang mở.");
            return;
          }
          selectedTab = id;
          draw();
        },
      ),
    );
    if (selectedTab === "info") {
      replace(
        body,
        el("p", {}, "Điện thoại: " + (supplier.phone || "Chưa có")),
        el("p", {}, "Địa chỉ: " + (supplier.address || "Chưa có")),
        el("p", {}, "Công nợ: " + money(supplier.debt)),
      );
    } else if (selectedTab === "debt") {
      replace(
        body,
        table(entries, [
          { label: "Ngày", key: "created_at" },
          { label: "Thay đổi", render: (p) => money(p.amount) },
          { label: "Tham chiếu", key: "reference" },
          { label: "Ghi chú", key: "note" },
        ]),
      );
    } else {
      const results = el("div");
      const drawProducts = () =>
        replace(
          results,
          table(
            catalogue.filter((p) =>
              normalize(
                [p.product_name, p.sku, p.supplier_sku, p.barcode].join(" "),
              ).includes(normalize(search.value)),
            ),
            [
              {
                label: "Sản phẩm",
                render: (p) =>
                  el(
                    "div",
                    {},
                    p.product_name,
                    el("small", {}, p.sku + " · " + p.unit),
                  ),
              },
              { label: "Mã hàng NCC", key: "supplier_sku" },
              {
                label: "Giá nhập riêng",
                render: (p) => money(p.supplier_cost_price),
              },
              {
                label: "Trạng thái",
                render: (p) => (p.active ? "Đang bán" : "Ngừng bán"),
              },
              {
                label: "Thao tác",
                render: (p) =>
                  button(
                    "Sửa giá / mã hàng",
                    () => edit({ product: p }),
                    "small",
                  ),
              },
            ],
          ),
        );
      search.oninput = drawProducts;
      replace(
        body,
        toolbar(
          search,
          button("+ Hàng có sẵn", () => edit({})),
          button(
            "+ Thêm sản phẩm mới",
            () => edit({ create: true }),
            "primary",
          ),
        ),
        el(
          "p",
          { class: "hint" },
          "Giá riêng của nhà cung cấp được gợi ý khi nhập hàng. Các phiếu nhập đã lưu giữ nguyên giá cũ.",
        ),
        results,
      );
      drawProducts();
    }
  }
  showModal(supplier.name, el("div", {}, nav, body));
  draw();
}

export async function purchaseForm(_products, suppliers) {
  if (!suppliers.length)
    throw new Error("Hãy thêm nhà cung cấp trước khi nhập hàng");
  let catalogue = [],
    lines = [],
    loading = false,
    saving = false,
    requestId = 0,
    editor = null,
    aiOpen = false;
  const lineBox = el("div"),
    error = el("p", { class: "error", role: "alert" }),
    totalLabel = el("strong"),
    hint = el("p", { class: "hint", role: "status" });
  const fields = [
    {
      name: "supplier_id",
      label: "Nhà cung cấp",
      options: suppliers.map((s) => [s.id, s.name]),
      numeric: true,
    },
    {
      name: "method",
      label: "Phương thức trả",
      options: [
        ["CASH", "Tiền mặt"],
        ["TRANSFER", "Chuyển khoản"],
      ],
      value: "TRANSFER",
    },
    number("paid", "Đã trả (bỏ trống để trả đủ)", null, { required: false }),
    text("note", "Ghi chú", { required: false }),
  ];
  const form = el(
    "form",
    {},
    el(
      "div",
      { class: "form-grid" },
      fields.map((spec) => field(spec)),
    ),
  );
  const supplierInput = form.elements.namedItem("supplier_id");
  const save = el(
    "button",
    { type: "submit", class: "primary", disabled: true },
    "Ghi nhận phiếu nhập",
  );
  const total = () =>
    lines.reduce(
      (sum, line) =>
        sum + Math.round(Number(line.quantity.value) * Number(line.cost.value)),
      0,
    );
  const update = () => {
    totalLabel.textContent = money(total());
    save.disabled = loading || saving || !!editor || aiOpen;
    assistant.button.disabled = loading || saving || !!editor || aiOpen;
  };
  const available = () => catalogue.filter((p) => p.active);
  async function loadCatalogue() {
    const current = ++requestId;
    loading = true;
    error.textContent = "";
    catalogue = [];
    lines.forEach((line) => line.picker.clear());
    hint.textContent = "Đang tải danh mục nhà cung cấp…";
    update();
    try {
      const data = await api("/suppliers/" + supplierInput.value + "/products");
      if (current !== requestId) return;
      catalogue = data;
      hint.textContent = available().length
        ? "Tìm trong " +
          available().length +
          " sản phẩm của nhà cung cấp. Giá nhập có thể sửa theo hóa đơn."
        : "Nhà cung cấp chưa có hàng đang bán. Thêm hàng có sẵn hoặc tạo sản phẩm mới ngay bên dưới.";
    } catch (err) {
      if (current === requestId) {
        error.textContent = err.message;
        hint.textContent = "Chưa tải được danh mục.";
      }
    } finally {
      if (current === requestId) {
        loading = false;
        update();
      }
    }
  }
  async function openEditor(line, create) {
    if (loading || saving || aiOpen) return;
    if (editor) {
      toast("Hãy lưu hoặc hủy phần thêm sản phẩm đang mở.");
      return;
    }
    const supplier = suppliers.find(
      (s) => s.id === Number(supplierInput.value),
    );
    const slot = el("div");
    editor = { line, slot };
    supplierInput.disabled = true;
    update();
    const close = () => {
      slot.remove();
      editor = null;
      supplierInput.disabled = false;
      update();
    };
    line.row.append(slot);
    try {
      slot.append(
        await catalogueEditor(supplier, {
          create,
          name: create ? line.picker.input.value : "",
          unit: line.invoiceUnit || "",
          costPrice: Number(line.cost.value),
          onSaved: (product) => {
            catalogue = [
              ...catalogue.filter((p) => p.id !== product.id),
              product,
            ];
            line.picker.choose(product);
            close();
            hint.textContent =
              "Danh mục đã cập nhật. Kiểm tra phiếu và ghi nhận để tăng tồn kho.";
          },
          onCancel: close,
        }),
      );
      slot.querySelector("input")?.focus();
    } catch (err) {
      close();
      throw err;
    }
  }
  function add(initial = {}) {
    const line = { product: null, invoiceUnit: initial.unit || "" };
    const quantity = el("input", {
      type: "number",
      min: 1,
      step: 1,
      value: "quantity" in initial ? (initial.quantity ?? "") : 1,
      required: true,
    });
    const cost = el("input", {
      type: "number",
      min: 0,
      step: 1,
      value: "cost_price" in initial ? (initial.cost_price ?? "") : 0,
      required: true,
    });
    const lot = el("input", {
      placeholder: "Mã lô (tự tạo nếu trống)",
      maxLength: 64,
    });
    const expiry = el("input", { type: "date", min: today() });
    const picker = productPicker(available, (product) => {
      line.product = product;
      if (product) cost.value = product.supplier_cost_price;
      update();
    });
    const row = el(
      "div",
      { class: "form-section" },
      el(
        "div",
        { class: "form-grid" },
        picker.element,
        el("label", {}, "Số lượng", quantity),
        el("label", {}, "Giá vốn / đơn vị", cost),
        el("label", {}, "Mã lô", lot),
        el("label", {}, "Hạn sử dụng", expiry),
      ),
      toolbar(
        button("+ Thêm sản phẩm mới", () => openEditor(line, true), "small"),
        button(
          "+ Hàng có sẵn vào danh mục",
          () => openEditor(line, false),
          "small",
        ),
        button(
          "Bỏ dòng",
          () => {
            if (editor?.line === line) {
              editor.slot.remove();
              editor = null;
              supplierInput.disabled = false;
            }
            lines = lines.filter((item) => item !== line);
            row.remove();
            update();
          },
          "small",
        ),
      ),
    );
    Object.assign(line, { quantity, cost, lot, expiry, picker, row });
    lines.push(line);
    lineBox.append(row);
    const matched = catalogue.find(
      (p) => p.id === initial.product_id && p.active,
    );
    if (matched) picker.choose(matched);
    else if (initial.name) picker.input.value = initial.name;
    if ("cost_price" in initial) cost.value = initial.cost_price ?? "";
    [quantity, cost].forEach((input) =>
      input.addEventListener("input", update),
    );
    update();
  }
  const assistant = invoiceAssistant({
    supplierId: () => Number(supplierInput.value),
    products: () => catalogue,
    canOpen: () => !loading && !saving && !editor,
    onOpenChange: (open) => {
      aiOpen = open;
      supplierInput.disabled = open || !!editor || saving;
      update();
    },
    onApply: (draft) => {
      lines = lines.filter((line) => {
        const empty =
          !line.product &&
          !line.picker.input.value.trim() &&
          line.quantity.value === "1" &&
          line.cost.value === "0" &&
          !line.lot.value &&
          !line.expiry.value;
        if (empty) line.row.remove();
        return !empty;
      });
      draft.forEach((item) => add(item));
      hint.textContent =
        "Các dòng AI đã vào phiếu nháp. Hàng chưa khớp cần chọn sản phẩm hoặc thêm mới; đối chiếu đơn vị và giá trước khi ghi nhận.";
    },
  });
  supplierInput.addEventListener("change", loadCatalogue);
  form.append(
    assistant.button,
    assistant.element,
    hint,
    lineBox,
    toolbar(
      button("+ Thêm dòng", () => add()),
      el("span", { class: "spacer" }),
      totalLabel,
    ),
    error,
    el("div", { class: "form-actions" }, button("Hủy", closeModal), save),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    if (loading || saving || editor || aiOpen) return;
    if (!lines.length || lines.some((line) => !line.product)) {
      error.textContent =
        "Mỗi dòng cần chọn một sản phẩm từ danh mục nhà cung cấp.";
      return;
    }
    saving = true;
    supplierInput.disabled = true;
    update();
    try {
      const data = readFields(form, fields);
      data.paid = data.paid ?? total();
      data.items = lines.map((line) => ({
        product_id: line.product.id,
        quantity: Number(line.quantity.value),
        cost_price: Number(line.cost.value),
        lot_code: line.lot.value,
        expires_on: line.expiry.value || null,
      }));
      await api("/purchases", data);
      closeModal();
      toast("Đã nhập kho");
      await refresh();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      saving = false;
      supplierInput.disabled = false;
      update();
    }
  });
  showModal("Nhập hàng từ nhà cung cấp", form);
  add();
  await loadCatalogue();
}
