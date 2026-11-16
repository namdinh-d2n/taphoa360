import { api, el, button, money, replace, state, toast } from "./ui.js?v=3.1";

export function invoiceAssistant({ supplierId, products, canOpen, onOpenChange, onApply }) {
  let controller = null, run = 0, previewUrl = null, opened = false, busy = false;
  const error = el("p", { class: "error", role: "alert" });
  const status = el("p", { class: "hint", role: "status" });
  const results = el("div");
  const image = el("img", { class: "invoice-preview", alt: "Ảnh hóa đơn đang đối chiếu", hidden: true });
  const upload = el("input", { type: "file", accept: "image/jpeg,image/png,image/webp", ariaLabel: "Ảnh hóa đơn" });
  const clearImage = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null; image.removeAttribute("src"); image.hidden = true;
  };
  const close = () => {
    ++run; controller?.abort(); controller = null; busy = false; opened = false;
    clearImage(); upload.value = ""; upload.disabled = false;
    root.hidden = true; replace(results); error.textContent = "";
    onOpenChange(false);
  };
  async function analyze() {
    const file = upload.files[0];
    if (!file) { error.textContent = "Hãy chọn ảnh hóa đơn trước."; return; }
    if (file.size > 8 * 1024 * 1024) { error.textContent = "Ảnh tối đa 8 MB. Hãy thu nhỏ ảnh rồi chọn lại."; return; }
    const current = ++run;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 120000);
    busy = true; upload.disabled = true; error.textContent = ""; replace(results);
    status.textContent = "Đang đọc hóa đơn trên máy… Lần đầu có thể chậm hơn. Bạn có thể hủy và nhập thủ công.";
    try {
      const data = new FormData();
      data.append("image", file); data.append("supplier_id", String(supplierId()));
      const response = await fetch("/api/v1/ai/invoices/preview", {
        method: "POST", headers: { "X-CSRF-Token": state.user?.csrf || "" },
        body: data, signal: controller.signal,
      });
      const draft = await response.json();
      if (current !== run) return;
      if (!response.ok) throw new Error(typeof draft.detail === "string" ? draft.detail : "Chưa đọc được ảnh hóa đơn.");
      status.textContent = "Đã đọc " + draft.items.length + " dòng. Kiểm tra với ảnh, sửa các ô cần thiết rồi đưa vào phiếu nháp.";
      draw(draft);
    } catch (err) {
      if (current === run) {
        error.textContent = err.name === "AbortError" ? "Đọc ảnh quá lâu. Thử ảnh nhỏ hơn hoặc nhập thủ công." : err.message;
        status.textContent = "Chưa có dữ liệu nào được ghi vào kho.";
      }
    } finally {
      clearTimeout(timeout);
      if (current === run) { busy = false; upload.disabled = false; }
    }
  }
  const analyzeButton = button("Đọc ảnh và tạo bản nháp", analyze, "primary");
  analyzeButton.disabled = true;
  const root = el("section", { class: "invoice-assistant", hidden: true },
    el("h3", {}, "AI đọc hóa đơn nhập hàng"),
    el("p", { class: "hint" }, "Ảnh được xử lý cục bộ, không dùng API trả phí. Chọn ảnh JPG, PNG hoặc WebP rõ bảng tên hàng, số lượng và đơn giá (tối đa 8 MB)."),
    el("label", {}, "Ảnh hóa đơn", upload), image,
    el("div", { class: "toolbar" }, analyzeButton, button("Hủy đọc ảnh", close)), status, error, results);
  upload.addEventListener("change", () => {
    clearImage(); replace(results); error.textContent = "";
    const file = upload.files[0];
    if (file) { previewUrl = URL.createObjectURL(file); image.src = previewUrl; image.hidden = false; }
  });
  function draw(draft) {
    const warnings = el("ul", { class: "invoice-warnings" }, draft.warnings.map((text) => el("li", {}, text)));
    const controls = [];
    const rows = draft.items.map((item, index) => {
      const use = el("input", { type: "checkbox", checked: true });
      const name = el("input", { value: item.name, maxLength: 150, ariaLabel: "Tên hàng trên ảnh dòng " + (index + 1) });
      const unit = el("input", { value: item.unit, maxLength: 30, ariaLabel: "Đơn vị trên ảnh dòng " + (index + 1) });
      const quantity = el("input", { type: "number", min: 1, step: 1, value: item.quantity ?? "", placeholder: "Cần kiểm tra" });
      const cost = el("input", { type: "number", min: 0, step: 1, value: item.cost_price ?? "", placeholder: "Cần kiểm tra" });
      const match = el("select", { ariaLabel: "Ghép sản phẩm dòng " + (index + 1) },
        el("option", { value: "" }, "Chưa chọn — chọn hoặc tạo mới trong phiếu"),
        products().filter((p) => p.active).map((p) => el("option", { value: p.id }, p.product_name + " · " + p.unit + " · " + p.sku)));
      match.value = item.product_id ?? "";
      const control = { use, name, unit, quantity, cost, match };
      controls.push(control);
      return el("div", { class: "invoice-draft-row" },
        el("label", { class: "invoice-include" }, use, "Dùng dòng " + (index + 1)),
        el("div", { class: "form-grid" },
          el("label", {}, "Tên đọc được trên ảnh", name), el("label", {}, "Sản phẩm trong danh mục", match),
          el("label", {}, "Đơn vị trên ảnh (kiểm tra quy cách)", unit), el("label", {}, "Số lượng", quantity),
          el("label", {}, "Đơn giá nhập", cost)),
        item.amount !== null ? el("p", { class: "hint" }, "Thành tiền đọc được: " + money(item.amount)) : null,
        item.warnings.length ? el("ul", { class: "invoice-warnings" }, item.warnings.map((text) => el("li", {}, text))) : null);
    });
    const apply = button("Đưa các dòng đã chọn vào phiếu nháp", () => {
      const included = controls.filter((control) => control.use.checked);
      if (!included.length) { error.textContent = "Hãy chọn ít nhất một dòng hàng."; return; }
      for (const control of included) {
        if (!control.name.value.trim()) { error.textContent = "Tên hàng không được để trống."; control.name.focus(); return; }
        if ([control.quantity, control.cost].some((input) => !input.reportValidity())) return;
      }
      const selected = included.map((control) => ({
        name: control.name.value.trim(), unit: control.unit.value.trim(),
        product_id: control.match.value ? Number(control.match.value) : null,
        quantity: control.quantity.value === "" ? null : Number(control.quantity.value),
        cost_price: control.cost.value === "" ? null : Number(control.cost.value),
      }));
      onApply(selected); close(); toast("Đã thêm vào phiếu nháp. Kiểm tra sản phẩm và ghi nhận phiếu để nhập kho.");
    }, "primary");
    const raw = el("details", {}, el("summary", {}, "Xem toàn bộ chữ đọc được"),
      el("pre", { class: "invoice-raw" }, draft.raw_text || "Không nhận dạng được chữ."));
    replace(results, warnings,
      draft.invoice_total !== null ? el("p", {}, "Tổng trên ảnh: " + money(draft.invoice_total) + " · Tổng dòng đọc được: " + money(draft.draft_total)) : null,
      rows, raw, draft.items.length ? apply : null);
  }
  const trigger = button("AI đọc ảnh hóa đơn", async () => {
    if (!canOpen() || opened) return;
    opened = true; root.hidden = false; onOpenChange(true);
    status.textContent = "Đang kiểm tra AI trên máy…";
    try {
      const result = await api("/ai/invoices/status");
      if (!opened) return;
      analyzeButton.disabled = !result.available;
      status.textContent = result.message;
    } catch (err) { if (opened) error.textContent = err.message; }
  });
  document.getElementById("modal").addEventListener("close", close, { once: true });
  return { element: root, button: trigger };
}
