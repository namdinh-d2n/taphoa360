import { api, el, button, link, panel, toolbar, table, money, qty, metric,
  showModal, closeModal, replace, owner, refresh, toast, can } from "./ui.js?v=3.1";

async function previewCombo(item) {
  const partner = el("select", { ariaLabel: "Hàng ghép combo" }, item.partners.map((p) =>
    el("option", { value: p.id }, p.name + " · " + p.unit)));
  partner.value = item.suggested_partner?.id || item.partners[0]?.id || "";
  const discount = el("input", { type: "number", min: 0, max: 50, step: 1,
    value: item.suggested_quote?.discount_percent ?? 15 });
  const limit = el("input", { type: "number", min: 1, step: 1, placeholder: "Tối đa theo tồn thực tế" });
  const result = el("div"), error = el("p", { class: "error", role: "alert" });
  let current = null, version = 0;
  const activate = button("Bật combo tại POS", async () => {
    if (!current) throw new Error("Hãy tính lại phương án trước khi bật combo.");
    await api("/rescue/campaigns", { ...parameters(), max_sets: current.max_sets, expected_price: current.price });
    closeModal(); toast("Đã bật combo giải cứu. Thu ngân có thể chọn tại POS."); await refresh();
  }, "primary");
  activate.disabled = true;
  function parameters() {
    return { batch_id: item.batch_id, partner_id: Number(partner.value), discount_percent: Number(discount.value),
      ...(limit.value ? { max_sets: Number(limit.value) } : {}) };
  }
  function invalidate() { ++version; current = null; activate.disabled = true; replace(result); }
  [partner,discount,limit].forEach((control) => control.addEventListener("input", invalidate));
  async function calculate() {
    if (![discount,limit].every((input) => input.reportValidity())) return;
    const revision = ++version;
    current = null; activate.disabled = true; error.textContent = "";
    try {
      const proposal = await api("/rescue/quote", parameters());
      if (revision !== version) return;
      current = proposal;
      const match = item.partners.find((p) => p.id === proposal.partner_id);
      const basis = match?.basis === "history" ? "Có " + match.co_orders + " đơn hoàn tất mua chung trong 28 ngày."
        : match?.basis === "category" ? "Gợi ý thử theo nhóm hàng; chưa có đủ lịch sử mua chung."
          : "Bạn chọn hàng ghép thủ công; chưa có đủ lịch sử mua chung.";
      replace(result,
        el("div", { class: "rescue-price" }, el("small", {}, "Giá cho 1 combo"), el("strong", {}, money(proposal.price)),
          el("span", {}, "Mua lẻ " + money(proposal.regular_price) + " · giảm " + proposal.actual_discount_percent + "%")),
        el("p", {}, "Mỗi combo: 1 " + proposal.product_unit + " " + proposal.product_name + " + 1 " + proposal.partner_unit + " " + proposal.partner_name),
        el("p", { class: "hint" }, basis),
        el("div", { class: "cards" },
          metric("Giới hạn", qty(proposal.max_sets) + " combo", "Đến hết " + proposal.expires_on),
          metric("Mục tiêu mỗi ngày", qty(proposal.sets_per_day) + " combo", "Để bán hết phần đã chọn"),
          metric("Lãi gộp nếu bán hết", money(proposal.gross_profit_if_all_sold), "Doanh thu " + money(proposal.revenue_if_all_sold))),
        el("p", { class: "hint" }, "Giá vốn theo lô xuất trước. Giữ lãi gộp ít nhất 10% mỗi combo, chưa trừ chi phí vận hành. Không cộng giảm giá thủ công hoặc đổi điểm."),
        proposal.margin_floor_applied ? el("p", { class: "notice" }, "Đã giảm mức ưu đãi để giữ ngưỡng lãi gộp; giá thực tế hiển thị bên trên.") : null);
      activate.disabled = !owner();
    } catch (err) { if (revision === version) error.textContent = err.message; }
  }
  const form = el("div", {},
    el("p", {}, "Lô " + item.lot_code + " · còn " + qty(item.remaining) + " " + item.unit + " · hạn " + item.expires_on),
    el("div", { class: "form-grid" }, el("label", { class: "full" }, "Hàng ghép", partner),
      el("label", {}, "Mức giảm đề nghị (%)", discount), el("label", {}, "Số combo tối đa", limit)),
    toolbar(button("Tính phương án", calculate)), error, result,
    el("div", { class: "form-actions" }, button("Đóng", closeModal), owner() ? activate : null));
  showModal("Xem trước combo giải cứu", form);
  await calculate();
}

export function rescuePanel(initial) {
  const root = el("section", { class: "panel rescue-panel" });
  let data = initial;
  const period = el("select", { ariaLabel: "Khoảng cận hạn" }, [7,14,30].map((days) => el("option", { value: days }, "Đến " + days + " ngày nữa")));
  period.value = data.horizon_days;
  period.addEventListener("change", async () => {
    period.disabled = true;
    try { data = await api("/rescue?days=" + period.value); draw(); }
    catch (err) { toast(err.message); period.value = data.horizon_days; }
    finally { period.disabled = false; }
  });
  function draw() {
    const knownCost = data.items.reduce((sum,item) => sum + item.remaining*item.cost_price,0);
    const unknown = data.items.filter((item) => item.cost_price<=0).length;
    const cards = data.items.map((item) => {
      const candidate = item.suggested_partner;
      const basis = candidate?.basis === "history" ? "Mua chung trong " + candidate.co_orders + " đơn gần đây"
        : candidate?.basis === "category" ? "Gợi ý thử theo nhóm hàng; chưa đủ lịch sử mua chung" : "Chọn hàng ghép để thử phương án";
      const earlier = !item.first_in_fefo ? " (gồm lượng các lô cần bán trước)" : "";
      return el("article", { class: "rescue-card" },
        el("div", { class: "rescue-card-head" }, el("div", {}, el("h3", {}, item.name),
          el("small", {}, "Lô " + item.lot_code + " · Hạn " + item.expires_on)),
          el("span", { class: "badge" + (item.days_left<=2 ? " red" : " warn") }, item.days_left===1 ? "Hết hạn hôm nay" : "Còn " + (item.days_left-1) + " ngày")),
        el("div", { class: "rescue-facts" },
          el("p", {}, el("strong", {}, qty(item.remaining) + " " + item.unit), " còn trong lô"),
          el("p", {}, "Cần bán ít nhất ", el("strong", {}, qty(item.daily_target) + " " + item.unit + "/ngày"), earlier),
          el("small", {}, "Tính cả hôm nay và ngày hết hạn."),
          item.daily_sales === null ? el("p", { class: "hint" }, "Chưa đủ lịch sử để ước tính tốc độ bán (cần 7 ngày dữ liệu và 3 đơn của mặt hàng).")
            : el("p", {}, "Tốc độ gần đây " + qty(item.daily_sales) + " " + item.unit + "/ngày; ước còn khoảng " + qty(Math.ceil(item.expected_unsold)) + " " + item.unit + " khi hết hạn nếu tốc độ giữ nguyên.")),
        candidate ? el("div", { class: "rescue-combo-hint" }, el("strong", {}, "Thử ghép với " + candidate.name),
          el("small", {}, basis), item.suggested_quote ? el("p", {}, "Giá gợi ý " + money(item.suggested_quote.price) + "/combo · lãi gộp nếu bán hết " + money(item.suggested_quote.gross_profit_if_all_sold)) : null)
          : el("p", { class: "hint" }, basis),
        item.blocked ? el("p", { class: "hint" }, item.blocked) : null,
        toolbar(item.first_in_fefo && item.remaining>=1 && item.partners.length
          ? button("Xem phương án combo", () => previewCombo(item), "primary") : null,
          link("Xem lô trong kho", "/warehouse")));
    });
    const active = data.campaigns.filter((campaign) => campaign.active);
    const expired = data.expired.length ? el("details", { class: "rescue-expired" },
      el("summary", {}, data.expired.length + " lô đã hết hạn — chuyển sang xử lý kho"),
      el("p", { class: "hint" }, "Các lô này không được đưa vào combo hoặc tồn có thể bán."),
      table(data.expired,[{label:"Sản phẩm",key:"name"},{label:"Lô",key:"lot_code"},{label:"Hạn",key:"expires_on"},
        {label:"Còn lại",render:(item)=>qty(item.remaining)+" "+item.unit}]),link("Mở kho để xử lý", "/warehouse")) : null;
    replace(root, el("div", { class: "panel-head" }, el("div", {}, el("p", { class: "eyebrow" }, "PHÂN TÍCH TẠI CỬA HÀNG"),
      el("h2", {}, "Giải cứu hàng cận hạn")), period),
      el("p", { class: "hint" }, data.note),
      el("div", { class: "cards" }, metric("Lô cần xem", data.items.length, "Tính đến " + data.as_of),
        metric("Giá vốn đang nằm trong lô", money(knownCost), unknown ? unknown + " lô chưa có giá vốn" : "Theo giá vốn đã khai báo"),
        metric("Combo đang bật", active.length, "Chủ tiệm duyệt, thu ngân chọn tại POS")),
      el("div", { class: "rescue-grid" }, cards.length ? cards : el("div", { class: "empty" }, "Chưa có lô còn hàng trong khoảng cận hạn đã chọn. Khai báo hạn dùng khi nhập kho để theo dõi.")),
      active.length ? panel("Combo đã bật", table(active,[{label:"Combo",key:"name"},{label:"Giá",render:(c)=>money(c.price)},
        {label:"Đã dùng / giới hạn",render:(c)=>c.used_sets+" / "+c.max_sets},
        {label:"Khả dụng",render:(c)=>c.available_sets>0?c.available_sets+" combo":c.reason},
        {label:"Đến hết",key:"expires_on"},
        {label:"Thao tác",render:(c)=>owner()?button("Dừng combo",async()=>{
          await api("/rescue/campaigns/"+c.id+"/stop",{}); toast("Đã dừng combo"); await refresh();
        },"small"):"Chủ tiệm quản lý"}])) : null,
      expired, can("cashier") ? link("Mở POS để bán combo", "/pos", "button primary") : null);
  }
  draw();
  return root;
}
