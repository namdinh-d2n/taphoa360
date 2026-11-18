import { el, money, qty } from "./ui.js?v=3.1";

const STORAGE = {
  FRESH: "Hàng tươi",
  FROZEN: "Đông lạnh",
  CHILLED: "Bảo quản mát",
  DRY: "Đồ khô",
  HOUSEHOLD: "Gia dụng",
};

export function productDetailPanel(
  data,
  {
    button,
    image,
    add,
    cartQuantity,
    browseBrand,
    browseCategory,
    buyNow,
    timeText,
  },
) {
  const product = data.product;
  const root = el("div", { class: "product-detail-layout" });
  const photo = el("div", { class: "detail-photo" }, image(product));
  const gallery = el(
    "section",
    { class: "detail-gallery", ariaLabel: "Ảnh và sản phẩm liên quan" },
    photo,
    el(
      "p",
      { class: "detail-photo-note" },
      product.image_path.endsWith(".svg")
        ? "Ảnh minh họa · đối chiếu quy cách và bao bì thực tế."
        : "Hình ảnh bao bì để tham khảo · quy cách theo tên sản phẩm.",
    ),
  );
  const feedback = el("p", {
    class: "detail-cart-feedback",
    role: "status",
    ariaLive: "polite",
  });
  const quantity = el("input", {
    type: "number",
    min: 1,
    max: Math.max(1, product.stock),
    step: 1,
    value: 1,
    ariaLabel: "Số lượng " + product.product_name,
    disabled: product.stock < 1,
  });
  function selectedQuantity() {
    const value = Number(quantity.value);
    if (!Number.isSafeInteger(value) || value < 1 || value > product.stock) {
      quantity.reportValidity();
      throw new Error(
        "Chọn số lượng nguyên từ 1 đến " + qty(product.stock) + ".",
      );
    }
    return value;
  }
  const step = (delta) => {
    const value = Number(quantity.value);
    quantity.value = Math.max(
      1,
      Math.min(
        product.stock,
        (Number.isSafeInteger(value) ? value : 1) + delta,
      ),
    );
    updateSummary();
  };
  const minus = button("−", () => step(-1), "detail-step");
  minus.setAttribute("aria-label", "Giảm số lượng " + product.product_name);
  const plus = button("+", () => step(1), "detail-step");
  plus.setAttribute("aria-label", "Tăng số lượng " + product.product_name);
  minus.disabled = plus.disabled = product.stock < 1;
  const subtotal = el("strong", { class: "detail-subtotal" });
  function updateSummary() {
    const value = Number(quantity.value);
    subtotal.textContent =
      Number.isSafeInteger(value) && value >= 1
        ? money(value * product.price)
        : "Kiểm tra số lượng";
  }
  quantity.addEventListener("input", updateSummary);
  const purchase = button(
    product.stock > 0 ? "Thêm vào giỏ" : "Chưa có hàng để mua",
    () => {
      add(product, selectedQuantity());
      feedback.textContent =
        "Đã thêm vào giỏ. Hiện có " +
        cartQuantity(product.id) +
        " " +
        product.unit +
        " của sản phẩm này.";
    },
    "primary",
  );
  purchase.disabled = product.stock < 1;
  const now = button(
    "Mua ngay",
    async () => {
      const count = selectedQuantity();
      await buyNow(product, count);
    },
    "detail-buy-now",
  );
  now.disabled = product.stock < 1;
  const info = el(
    "section",
    { class: "detail-buy-panel", ariaLabel: "Thông tin và đặt mua" },
    el("p", { class: "eyebrow" }, product.category_group),
    el("h2", { class: "detail-title" }, product.product_name),
    el(
      "div",
      { class: "detail-brand-line" },
      el("span", {}, "Thương hiệu: "),
      product.brand
        ? button(
            product.brand,
            () => browseBrand(product.brand),
            "link detail-text-button",
          )
        : el("span", {}, "Chưa cập nhật"),
    ),
    el(
      "div",
      { class: "detail-price-row" },
      el("strong", { class: "detail-main-price" }, money(product.price)),
      product.regular_price > product.price
        ? el("del", { class: "muted" }, money(product.regular_price))
        : null,
      product.regular_price > product.price
        ? el(
            "span",
            { class: "badge" },
            "−" +
              Math.round(
                ((product.regular_price - product.price) * 100) /
                  product.regular_price,
              ) +
              "%",
          )
        : null,
    ),
    el(
      "p",
      { class: "muted" },
      "Quy cách: " + product.unit + " · " + STORAGE[product.storage_kind],
    ),
    product.stock > 0
      ? el(
          "p",
          { class: "detail-stock" },
          "Còn " + qty(product.stock) + " " + product.unit + " có thể bán",
        )
      : el(
          "p",
          { class: "detail-stock unavailable" },
          "Chưa có tồn bán được. Bạn có thể xem các lựa chọn liên quan.",
        ),
    product.sale
      ? el(
          "div",
          { class: "detail-sale" },
          el("strong", {}, "⚡ " + product.sale.name),
          el(
            "p",
            {},
            "Còn " + product.sale.remaining + " đơn vị theo chương trình",
          ),
          el(
            "span",
            { class: "countdown", "data-ends": product.sale.ends_at },
            "Đến " + timeText(product.sale.ends_at),
          ),
        )
      : null,
    el(
      "div",
      { class: "detail-quantity-line" },
      el("label", { htmlFor: "detail-quantity" }, "Số lượng"),
      el("div", { class: "detail-stepper" }, minus, quantity, plus),
      subtotal,
    ),
    el("div", { class: "detail-buy-actions" }, purchase, now),
    feedback,
  );
  quantity.id = "detail-quantity";
  updateSummary();
  if (product.expiry || product.sell_until) {
    info.append(
      el(
        "div",
        { class: "detail-freshness" },
        el("strong", {}, "Hạn dùng & nhận hàng"),
        product.expiry
          ? el(
              "p",
              {},
              "HSD lô xuất trước: " +
                product.expiry.split("-").reverse().join("/"),
            )
          : null,
        product.sell_until
          ? el("p", {}, "Cần giao/nhận trước " + timeText(product.sell_until))
          : null,
      ),
    );
  }
  if (data.cross_sell.length) {
    const accessories = el(
      "section",
      { class: "detail-addons", ariaLabel: "Gợi ý mua kèm" },
      el("h3", {}, "Có thể bạn muốn mua cùng"),
      el(
        "p",
        { class: "muted" },
        "Giá từng món · không tự thêm hàng hoặc giảm giá.",
      ),
    );
    for (const candidate of data.cross_sell) {
      const open = button(
        "",
        () => openRelated(candidate),
        "detail-addon-image",
      );
      open.setAttribute("aria-label", "Xem " + candidate.product_name);
      open.append(image(candidate));
      const addButton = button(
        "+ " + money(candidate.price),
        () => {
          add(candidate);
          feedback.textContent =
            "Đã thêm " +
            candidate.product_name +
            " · tăng " +
            money(candidate.price) +
            ".";
        },
        "detail-addon-add",
      );
      addButton.setAttribute(
        "aria-label",
        "Thêm món kèm " + candidate.product_name,
      );
      accessories.append(
        el(
          "article",
          { class: "detail-addon" },
          open,
          el(
            "div",
            {},
            button(
              candidate.product_name,
              () => openRelated(candidate),
              "detail-addon-name",
            ),
            el("small", {}, candidate.unit),
            el("p", { class: "detail-reason" }, candidate.suggestion_reason),
          ),
          addButton,
        ),
      );
    }
    info.append(accessories);
  } else
    info.append(
      el(
        "p",
        { class: "muted detail-empty-addon" },
        "Chưa có món mua kèm phù hợp còn hàng tại tiệm.",
      ),
    );
  info.append(
    el(
      "p",
      { class: "notice" },
      "Có thể kiểm hàng khi nhận. Nếu thiếu món, tiệm đề nghị điều chỉnh để bạn duyệt trước khi giao.",
    ),
  );
  const relatedGrid = el("div", { class: "detail-related-grid" });
  function openRelated(candidate) {
    root.dispatchEvent(
      new CustomEvent("open-product", { detail: candidate, bubbles: true }),
    );
  }
  for (const candidate of data.related) {
    const cover = button(
      "",
      () => openRelated(candidate),
      "detail-related-image",
    );
    cover.setAttribute("aria-label", "Xem " + candidate.product_name);
    cover.append(image(candidate));
    const buy = button(
      candidate.stock > 0 ? "+ Thêm" : "Chờ nhập kho",
      () => {
        add(candidate);
        feedback.textContent =
          "Đã thêm " + candidate.product_name + " vào giỏ.";
      },
      "detail-related-buy",
    );
    buy.disabled = candidate.stock < 1;
    relatedGrid.append(
      el(
        "article",
        { class: "detail-related-card" },
        cover,
        button(
          candidate.product_name,
          () => openRelated(candidate),
          "detail-related-name",
        ),
        el("p", { class: "muted" }, candidate.unit),
        el("strong", {}, money(candidate.price)),
        el("small", { class: "detail-reason" }, candidate.suggestion_reason),
        buy,
      ),
    );
  }
  gallery.append(
    el(
      "section",
      { class: "detail-related" },
      el("h3", {}, "Sản phẩm liên quan"),
      data.related.length
        ? relatedGrid
        : el("p", { class: "muted" }, "Tiệm đang bổ sung sản phẩm cùng loại."),
    ),
  );
  const description = el(
    "section",
    { class: "detail-description" },
    el("h3", {}, "Thông tin sản phẩm"),
    el(
      "p",
      { class: "detail-description-text" },
      product.description ||
        "Tiệm đang cập nhật mô tả. Kiểm tra quy cách và hướng dẫn trên bao bì khi nhận hàng.",
    ),
    el(
      "dl",
      { class: "detail-specs" },
      el("dt", {}, "Quy cách"),
      el("dd", {}, product.unit),
      el("dt", {}, "Danh mục"),
      el(
        "dd",
        {},
        button(
          product.category,
          () => browseCategory(product),
          "detail-text-button",
        ),
      ),
      el("dt", {}, "Thương hiệu"),
      el("dd", {}, product.brand || "Chưa cập nhật"),
      el("dt", {}, "Loại bảo quản"),
      el("dd", {}, STORAGE[product.storage_kind]),
      el("dt", {}, "Mã sản phẩm"),
      el("dd", {}, product.sku),
    ),
  );
  if (product.catalog_origin === "REFERENCE")
    description.append(
      el(
        "p",
        { class: "notice" },
        "Giá tham khảo ngày " +
          product.reference_checked_at +
          ". Hàng mới chỉ đặt mua khi tiệm đã nhập kho. ",
        product.reference_source
          ? el(
              "a",
              {
                href: product.reference_source,
                target: "_blank",
                rel: "noopener noreferrer",
                class: "link",
              },
              "Nguồn giá/ảnh",
            )
          : null,
      ),
    );
  const brandSection = el(
    "section",
    { class: "detail-brands" },
    el("h3", {}, "Khám phá sản phẩm & nhãn hàng"),
  );
  if (data.brands.length) {
    brandSection.append(
      el(
        "p",
        { class: "muted" },
        "Các thương hiệu có mặt hàng cùng nhóm tại tiệm.",
      ),
      el(
        "div",
        { class: "detail-brand-grid" },
        data.brands.map((brand) => {
          const control = button(
            "",
            () => browseBrand(brand.name),
            "detail-brand-choice",
          );
          control.append(
            el("strong", {}, brand.name),
            el(
              "small",
              {},
              brand.current ? "Thương hiệu đang xem" : brand.reason,
            ),
            el(
              "span",
              {},
              brand.product_count +
                " sản phẩm · " +
                brand.available_count +
                " còn hàng",
            ),
          );
          control.setAttribute("aria-label", "Xem nhãn hàng " + brand.name);
          return control;
        }),
      ),
    );
  } else
    brandSection.append(
      el("p", { class: "muted" }, "Chưa có thông tin nhãn hàng cho nhóm này."),
    );
  root.append(gallery, info, description, brandSection);
  return root;
}
