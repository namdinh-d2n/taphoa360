const emailForm = document.getElementById("recovery-email-form");
const otpForm = document.getElementById("recovery-otp-form");
const passwordForm = document.getElementById("recovery-password-form");
const recoveryError = document.getElementById("recovery-error");
const recoveryStatus = document.getElementById("recovery-status");
const title = document.getElementById("recovery-title");
const description = document.getElementById("recovery-description");
const resendButton = document.getElementById("resend-otp");
const steps = [...document.querySelectorAll(".recovery-steps li")];
let email = "", challenge = "", resetToken = "", step = 0;
let otpExpiresAt = 0, resendAt = 0, busy = false;

// Recovery credentials remain in memory, never URLs or browser storage.
if (location.hash) history.replaceState(null, "", location.pathname);

function clearFeedback() {
  recoveryError.textContent = "";
  recoveryStatus.hidden = true;
}

function showStep(next) {
  step = next;
  emailForm.hidden = step !== 0;
  otpForm.hidden = step !== 1;
  passwordForm.hidden = step !== 2;
  steps.forEach((item, index) => {
    item.removeAttribute("aria-current");
    item.removeAttribute("data-complete");
    if (index === step) item.setAttribute("aria-current", "step");
    if (index < step) item.setAttribute("data-complete", "");
  });
  if (step === 0) {
    title.textContent = "Quên mật khẩu?";
    description.textContent = "Nhập email khôi phục đã liên kết với tài khoản cửa hàng để nhận mã OTP gồm 6 chữ số.";
    emailForm.elements.email.focus();
  } else if (step === 1) {
    title.textContent = "Nhập mã OTP";
    description.textContent = `Nếu ${email} đã liên kết với tài khoản, mã OTP đã được gửi đến hộp thư này. Kiểm tra cả thư rác rồi nhập mã bên dưới.`;
    otpForm.elements.otp.focus();
  } else if (step === 2) {
    title.textContent = "Đặt mật khẩu mới";
    description.textContent = "Email đã được xác thực. Tạo mật khẩu mới từ 10 đến 200 ký tự trong vòng 5 phút.";
    passwordForm.elements.password.focus();
  }
  updateControls();
}

function updateControls() {
  document.querySelectorAll("form button").forEach(button => { button.disabled = busy; });
  const wait = Math.max(0, Math.ceil((resendAt - Date.now()) / 1000));
  resendButton.disabled = busy || wait > 0;
  resendButton.textContent = wait > 0 ? `Gửi lại mã sau ${wait}s` : "Gửi lại mã OTP";
  if (step === 1) {
    const left = Math.max(0, Math.ceil((otpExpiresAt - Date.now()) / 1000));
    document.getElementById("otp-time-left").textContent = left > 0
      ? `Mã còn hiệu lực ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}. Tối đa 5 lần nhập sai.`
      : "Mã OTP đã hết hạn. Hãy yêu cầu gửi lại mã mới.";
  }
}

async function post(url, data) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data), signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Không thể xử lý yêu cầu. Vui lòng thử lại.");
    return result;
  } finally { clearTimeout(timer); }
}

async function run(action) {
  if (busy) return;
  busy = true;
  clearFeedback();
  updateControls();
  try { await action(); }
  catch (error) {
    recoveryError.textContent = error.name === "AbortError" ? "Kết nối quá lâu. Vui lòng thử lại." : error.message;
  } finally {
    busy = false;
    updateControls();
  }
}

async function requestOtp(address) {
  const result = await post("/api/forgot-password", { email: address });
  email = address;
  challenge = result.challenge_id;
  resetToken = "";
  otpExpiresAt = Date.now() + result.expires_in * 1000;
  resendAt = Date.now() + result.resend_after * 1000;
  otpForm.reset();
  showStep(1);
}

emailForm.addEventListener("submit", event => {
  event.preventDefault();
  run(() => requestOtp(emailForm.elements.email.value.trim().toLowerCase()));
});
resendButton.addEventListener("click", () => {
  if (Date.now() >= resendAt) run(() => requestOtp(email));
});
otpForm.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const result = await post("/api/verify-reset-otp", { challenge_id: challenge, otp: otpForm.elements.otp.value.trim() });
    resetToken = result.reset_token;
    challenge = "";
    otpForm.reset();
    showStep(2);
  });
});
passwordForm.addEventListener("submit", event => {
  event.preventDefault();
  clearFeedback();
  const data = Object.fromEntries(new FormData(passwordForm));
  if (data.password !== data.confirm_password) {
    recoveryError.textContent = "Mật khẩu xác nhận không khớp";
    passwordForm.elements.confirm_password.focus();
    return;
  }
  run(async () => {
    const result = await post("/api/reset-password", { ...data, token: resetToken });
    resetToken = challenge = email = "";
    passwordForm.reset();
    emailForm.reset();
    showStep(3);
    clearInterval(countdown);
    title.textContent = "Đã đổi mật khẩu";
    description.textContent = "Bạn có thể đăng nhập lại bằng mật khẩu mới.";
    recoveryStatus.textContent = result.message;
    recoveryStatus.hidden = false;
  });
});
function restart() {
  if (busy) return;
  challenge = resetToken = "";
  otpForm.reset();
  passwordForm.reset();
  clearFeedback();
  showStep(0);
}
document.getElementById("change-recovery-email").addEventListener("click", restart);
document.getElementById("restart-recovery").addEventListener("click", restart);
const countdown = setInterval(updateControls, 1000);
showStep(0);
