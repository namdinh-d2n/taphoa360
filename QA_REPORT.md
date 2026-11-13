# Kiểm tra bản 3.1 — 07/11/2026

## Kết quả thực tế

- `python -m unittest discover -s tests -v`: **53/53 đạt**, 53,116 giây (bản PythonAnywhere).
- Bao gồm transaction/rollback, bán đồng thời, chống tạo đơn trùng, FEFO, hoàn/hủy,
  công nợ, điểm, chốt ca, nhân sự/lương, CSRF/phân quyền, đăng ký, backup/restore.
- Kiểm tra mới: production trống không demo; mã thiết lập; Secure/HttpOnly cookie;
  chặn host lạ; tắt docs; giữ dữ liệu qua hai lần startup; từ chối cấu hình production
  không an toàn; giới hạn body kể cả chunked; JSON sai kiểu; tổng tiền quá lớn;
  không liên kết hai tài khoản vào cùng hồ sơ nhân viên.
- Kiểm tra bổ sung PythonAnywhere: Unix domain socket, SQLite DELETE journal và
  PUBLIC_ORIGIN sau proxy HTTP nội bộ; vẫn từ chối nguồn khác.
- `node --check` cho mọi module `static/*.js`: đạt.
- `pip check`: không có xung đột dependency.
- `compileall` cho backend và test: đạt.
- Tải đầy đủ wheel theo `requirements.lock.txt` cho **CPython 3.11 Linux x86_64**:
  đạt. Không cần biên dịch pydantic-core hoặc MarkupSafe tại deploy.
- `git diff --check`: đạt (Git chỉ cảnh báo quy đổi LF/CRLF trên Windows).

## Kiểm tra trình duyệt

Server thử dùng database riêng `.local/qa-deploy/shop.db`, không ghi database cửa hàng.
Đăng nhập chủ tiệm thành công. Cả 13 trang tải xong không có lỗi trang hoặc console:
owner, POS, đơn hàng, sản phẩm, kho, sơ đồ kệ, khách hàng, nhà cung cấp, ca thu ngân,
nhân sự, báo cáo, đề xuất, cài đặt.

Đã xem bố cục desktop 1440px và mobile 390px; mở menu mobile và chuyển trang POS.
Tạo một đơn thử 1 gói mì, 4.500đ, phương thức chuyển khoản: màn hình xác nhận thành
công, tồn giảm từ 60 xuống 59, đơn xuất hiện trên tổng quan. Đây là giao dịch giả lập
trong database thử, không phải xác nhận chuyển tiền thật.

Ảnh minh họa lưu tại `output/deploy-review/desktop.jpg` (dữ liệu demo).

## Giới hạn xác minh

- Máy làm việc chưa cài Docker: **chưa build/chạy image Docker tại chỗ**.
  Workflow GitHub Actions đã có bước test Linux và build Docker nhưng chưa chạy
  trên GitHub trong phiên này.
- Đã deploy thật trên PythonAnywhere Free và kiểm tra HTTPS, setup, API bảo vệ,
  static, nguồn POST và dữ liệu giữ nguyên sau reload. Xem `DEPLOY_STATUS.md`.
  Chủ tiệm cần tự đặt thông tin đăng nhập lần đầu và nghiệm thu giao dịch trước vận hành.
- Chưa thực hiện kiểm thử tải dài hạn hay pentest độc lập.
- Bản này phục vụ một cửa hàng; không tích hợp thanh toán ngân hàng tự động,
  hóa đơn điện tử, đồng bộ nhiều chi nhánh. Gói PythonAnywhere Free có hạn mức tài nguyên; ASGI đang ở beta.
