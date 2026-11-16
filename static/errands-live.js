// One authenticated event stream per view. The browser reconnects automatically.
export function connectErrands(url, onChange, onStatus = () => {}) {
  let source,
    closed = false,
    queued = false,
    running = false,
    retryTimer;
  async function drain() {
    if (running || closed) return;
    running = true;
    try {
      while (queued && !closed) {
        queued = false;
        await onChange();
      }
    } catch {
      onStatus("Đang kết nối lại…");
      clearTimeout(retryTimer);
      retryTimer = setTimeout(sync, 2000);
    } finally {
      running = false;
    }
  }
  function sync() {
    queued = true;
    return drain();
  }
  function open() {
    source = new EventSource(url);
    source.addEventListener("open", () => onStatus("Đang cập nhật trực tiếp"));
    source.addEventListener("changed", sync);
    source.addEventListener("error", () => onStatus("Đang kết nối lại…"));
    source.addEventListener("session-expired", () => {
      source.close();
      onStatus("Phiên đăng nhập đã hết hạn");
    });
  }
  const visible = () => {
    if (!document.hidden) sync();
  };
  document.addEventListener("visibilitychange", visible);
  window.addEventListener("pagehide", close, { once: true });
  function close() {
    closed = true;
    clearTimeout(retryTimer);
    source?.close();
    document.removeEventListener("visibilitychange", visible);
  }
  open();
  return { close, sync };
}
