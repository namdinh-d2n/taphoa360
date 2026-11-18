import { el } from "./ui.js?v=3.1";

export async function addressPicker(request, initial = {}) {
  const mode = el(
    "select",
    { name: "address_mode", ariaLabel: "Cách nhập địa chỉ" },
    el("option", { value: "SELECT" }, "Chọn tỉnh/thành, phường/xã"),
    el("option", { value: "MANUAL" }, "Tự nhập địa chỉ đầy đủ"),
  );
  mode.value = initial.address_mode || "SELECT";
  const province = el(
    "select",
    { name: "province_code", ariaLabel: "Tỉnh / thành phố" },
    el("option", { value: "" }, "Chọn tỉnh / thành phố"),
  );
  const ward = el(
    "select",
    { name: "ward_code", ariaLabel: "Phường / xã / đặc khu", disabled: true },
    el("option", { value: "" }, "Chọn tỉnh/thành trước"),
  );
  const line = el("input", {
    name: "address_line",
    type: "text",
    maxLength: 300,
    autocomplete: "address-line1",
    placeholder: "Số nhà, căn hộ, tòa, thôn, đường",
    value: initial.address_line || "",
  });
  const manual = el("textarea", {
    name: "address",
    maxLength: 500,
    rows: 3,
    autocomplete: "street-address",
    placeholder: "Số nhà/căn hộ, đường/thôn, phường/xã, tỉnh/thành phố",
    value: initial.address || "",
  });
  const preview = el("p", { class: "muted address-preview", role: "status" });
  const note = el(
    "p",
    { class: "hint muted" },
    "Danh sách địa chỉ toàn quốc độc lập với vùng/phí giao do tiệm phục vụ.",
  );
  const selectedBox = el(
    "div",
    { class: "form-grid address-selected" },
    el("label", {}, "Tỉnh / thành phố", province),
    el("label", {}, "Phường / xã / đặc khu", ward),
    el("label", { class: "full" }, "Số nhà / căn hộ / đường / thôn", line),
  );
  const manualBox = el("label", {}, "Địa chỉ đầy đủ do bạn nhập", manual);
  const root = el(
    "section",
    { class: "address-picker full" },
    el("label", {}, "Cách nhập địa chỉ", mode),
    selectedBox,
    manualBox,
    preview,
    note,
  );
  let loadId = 0;
  function update() {
    const selected = mode.value === "SELECT";
    selectedBox.hidden = !selected;
    manualBox.hidden = selected;
    province.required = ward.required = line.required = selected;
    manual.required = !selected;
    province.disabled = !selected;
    ward.disabled = !selected || !province.value;
    line.disabled = !selected;
    manual.disabled = selected;
    preview.textContent =
      selected && province.value && ward.value
        ? [
            line.value,
            ward.selectedOptions[0].textContent,
            province.selectedOptions[0].textContent,
          ]
            .filter(Boolean)
            .join(", ")
        : !selected
          ? manual.value
          : "";
  }
  async function loadWards(value) {
    const id = ++loadId;
    ward.replaceChildren(el("option", { value: "" }, "Đang tải phường/xã…"));
    ward.disabled = true;
    try {
      const response = await request("/locations/" + Number(value) + "/wards");
      if (id !== loadId) return;
      ward.replaceChildren(
        el("option", { value: "" }, "Chọn phường / xã / đặc khu"),
        ...response.wards.map((w) => el("option", { value: w.code }, w.name)),
      );
      if (Number(value) === initial.province_code && initial.ward_code)
        ward.value = initial.ward_code;
      update();
    } catch (error) {
      if (id !== loadId) return;
      mode.value = "MANUAL";
      note.textContent =
        "Không tải được danh sách. Bạn vẫn có thể tự nhập địa chỉ đầy đủ.";
      update();
    }
  }
  mode.addEventListener("change", update);
  line.addEventListener("input", update);
  manual.addEventListener("input", update);
  ward.addEventListener("change", update);
  province.addEventListener("change", () => {
    if (province.value) loadWards(province.value);
    else {
      ++loadId;
      ward.replaceChildren(
        el("option", { value: "" }, "Chọn tỉnh/thành trước"),
      );
      update();
    }
  });
  try {
    const response = await request("/locations");
    province.append(
      ...response.provinces.map((p) => el("option", { value: p.code }, p.name)),
    );
    if (initial.province_code) {
      province.value = initial.province_code;
      await loadWards(initial.province_code);
    }
  } catch (error) {
    mode.value = "MANUAL";
    note.textContent =
      "Bạn có thể tự nhập địa chỉ đầy đủ khi danh sách chưa tải được.";
  }
  update();
  return {
    element: root,
    value() {
      if (mode.value === "MANUAL")
        return { address_mode: "MANUAL", address: manual.value.trim() };
      return {
        address_mode: "SELECT",
        province_code: Number(province.value),
        ward_code: Number(ward.value),
        address_line: line.value.trim(),
      };
    },
  };
}
