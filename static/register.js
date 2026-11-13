document
  .getElementById("register-form")
  ?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const error = document.getElementById("register-error");
    error.textContent = "";
    const data = Object.fromEntries(new FormData(form));
    if (data.password !== data.confirm_password) {
      error.textContent = "Mật khẩu xác nhận không khớp";
      form.elements.confirm_password.focus();
      return;
    }
    button.disabled = true;
    try {
      const response = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "Không thể đăng ký. Vui lòng thử lại.",
        );
      form.reset();
      form.hidden = true;
      document.getElementById("registration-message").textContent =
        `Yêu cầu #${result.registration_id}. ${result.message}`;
      document.getElementById("register-success").hidden = false;
    } catch (err) {
      error.textContent = err.message;
    } finally {
      button.disabled = false;
    }
  });
