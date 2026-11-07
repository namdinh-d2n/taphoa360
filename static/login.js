document
  .getElementById("login-form")
  ?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      button = form.querySelector("button"),
      error = document.getElementById("login-error");
    button.disabled = true;
    error.textContent = "";
    const data = Object.fromEntries(new FormData(form));
    try {
      if (form.dataset.setup === "true") {
        const setup = await fetch("/api/setup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
        if (!setup.ok)
          throw new Error(
            (await setup.json()).detail || "Không thể tạo tài khoản",
          );
        form.dataset.setup = "false";
      }
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!response.ok)
        throw new Error((await response.json()).detail || "Đăng nhập thất bại");
      const result = await response.json();
      location.href = result.redirect_url;
    } catch (err) {
      error.textContent = err.message;
    } finally {
      button.disabled = false;
    }
  });
