import { el, money } from "./ui.js?v=3.1";

export function qrPayment(
  order,
  { button, modal, privateView, refresh, login, report },
) {
  if (order.payment_method !== "QR") return null;
  if (["CANCELLED", "EXPIRED"].includes(order.status)) return null;
  if (order.paid >= order.total)
    return el(
      "section",
      { class: "qr-payment paid" },
      el("h3", {}, "Đã xác nhận nhận tiền"),
      el(
        "p",
        {},
        "Tiệm đã xác nhận " +
          money(order.paid) +
          ". Bạn không cần chuyển thêm.",
      ),
    );
  if (order.payment_status === "REPORTED")
    return el(
      "section",
      { class: "qr-payment waiting" },
      el("h3", {}, "Đã báo thanh toán · chờ cửa hàng duyệt"),
      el(
        "p",
        {},
        "Cửa hàng đang đối chiếu tiền thực nhận. Sau khi duyệt, hóa đơn sẽ xuất hiện và đơn chuyển sang chuẩn bị giao.",
      ),
      button("Cập nhật kết quả duyệt", refresh),
    );
  if (
    ["PENDING", "REVIEW"].includes(order.status) &&
    order.payment_flow !== "PREPAY"
  )
    return el(
      "section",
      { class: "qr-payment waiting" },
      el("h3", {}, "Thanh toán bằng cách quét QR"),
      el(
        "p",
        {},
        order.status === "REVIEW"
          ? "Đơn đang chờ duyệt điều chỉnh. Mã QR sẽ hiển thị khi tiệm xác nhận lại đơn."
          : "Tiệm đang kiểm tra và xác nhận có hàng. Mã QR sẽ hiện tại đây ngay khi đơn được xác nhận.",
      ),
      button("Cập nhật QR & trạng thái", refresh),
    );
  if (!["PENDING", "CONFIRMED", "SHIPPING"].includes(order.status)) return null;
  if (!privateView || !order.bank)
    return el(
      "section",
      { class: "qr-payment waiting" },
      el("h3", {}, "Quét QR để thanh toán đơn này"),
      el(
        "p",
        {},
        "Đăng nhập đúng tài khoản đã đặt đơn để mở mã QR và thông tin chuyển khoản.",
      ),
      button("Đăng nhập để mở mã QR", login, "primary"),
    );
  const bank = order.bank;
  const path = "/api/shop/orders/" + order.id + "/qr";
  const large = () =>
    modal(
      "Quét QR thanh toán · " + order.code,
      el(
        "div",
        { class: "qr-enlarged" },
        el("p", {}, bank.bank_name + " · " + bank.bank_account),
        el("strong", {}, money(bank.amount)),
        el("img", {
          src: path + "?format=png",
          alt: "Mã QR " + bank.bank_name + " cho đơn " + order.code,
        }),
        el("p", {}, "Nội dung: " + bank.reference),
        el(
          "small",
          {},
          "Kiểm tra người nhận, số tiền và nội dung trong ứng dụng ngân hàng trước khi xác nhận.",
        ),
      ),
    );
  const image = el("img", {
    class: "qr-code",
    src: path + "?format=png",
    alt: "Mã QR chuyển khoản cho đơn " + order.code,
  });
  const error = el("p", { class: "error", role: "alert", hidden: true });
  image.addEventListener("error", () => {
    error.hidden = false;
    error.textContent =
      "Chưa tải được mã QR. Bấm cập nhật để kiểm tra trạng thái đơn.";
  });
  return el(
    "section",
    { class: "qr-payment" },
    el(
      "div",
      { class: "qr-payment-heading" },
      el("span", { class: "qr-payment-symbol", ariaHidden: true }, "▦"),
      el(
        "div",
        {},
        el("h3", {}, "Quét QR để thanh toán"),
        el(
          "p",
          { class: "muted" },
          "Mã tự điền số tiền và nội dung của đơn " + order.code,
        ),
      ),
    ),
    el(
      "div",
      { class: "qr-payment-layout" },
      el("div", { class: "qr-image-box" }, image, error),
      el(
        "div",
        { class: "qr-payment-info" },
        el("p", {}, "Ngân hàng: ", el("strong", {}, bank.bank_name)),
        el("p", {}, "Số tài khoản: ", el("strong", {}, bank.bank_account)),
        el("p", { class: "qr-amount" }, money(bank.amount)),
        el("p", {}, "Nội dung: ", el("strong", {}, bank.reference)),
        el(
          "ol",
          {},
          el(
            "li",
            {},
            "Mở ứng dụng ngân hàng trên điện thoại và chọn Quét QR.",
          ),
          el(
            "li",
            {},
            "Quét mã trên màn hình, hoặc tải ảnh QR rồi chọn ảnh từ thư viện.",
          ),
          el(
            "li",
            {},
            "Kiểm tra người nhận, số tiền và nội dung, sau đó xác nhận trong ứng dụng ngân hàng.",
          ),
        ),
        el(
          "div",
          { class: "qr-order-summary" },
          el("strong", {}, "Món hàng đã chọn"),
          el(
            "ul",
            {},
            order.items.map((item) =>
              el(
                "li",
                {},
                item.product_name +
                  " × " +
                  item.quantity +
                  " " +
                  item.unit +
                  " · " +
                  money(item.charged_total),
              ),
            ),
          ),
        ),
        el(
          "div",
          { class: "qr-payment-actions" },
          button("Phóng to QR", large),
          el(
            "a",
            {
              class: "qr-download",
              href: path + "?format=png",
              download: order.code + "-qr.png",
            },
            "Tải ảnh QR (PNG)",
          ),
        ),
      ),
    ),
    el(
      "p",
      { class: "qr-confirm-note" },
      order.payment_flow === "PREPAY"
        ? "Hàng được giữ 30 phút. Sau khi chuyển tiền, bấm Xác nhận đã thanh toán để gửi yêu cầu cửa hàng duyệt."
        : "Tiệm đối chiếu giao dịch rồi xác nhận đã nhận tiền.",
    ),
    button(
      order.payment_flow === "PREPAY"
        ? "Xác nhận đã thanh toán"
        : "Cập nhật trạng thái thanh toán",
      order.payment_flow === "PREPAY" ? report : refresh,
      "primary",
    ),
  );
}
