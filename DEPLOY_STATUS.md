# Trạng thái triển khai — 07/11/2026

**Đã triển khai thành công trên PythonAnywhere Free**, tài khoản `huunguyenthuan`.

- Website: https://huunguyenthuan.pythonanywhere.com
- Thiết lập chủ tiệm: https://huunguyenthuan.pythonanywhere.com/setup
- Healthcheck: https://huunguyenthuan.pythonanywhere.com/health/ready
- Nền tảng không sử dụng: Zeabur, Railway, Render.
- Không đăng ký gói trả phí; tài khoản hiển thị Beginner/Free, dung lượng 512 MB.
- Thư viện và mã nguồn dùng khoảng 48 MB tính cả wheel offline; database mới 188 KiB.

## Đã xác minh trên server thật

- HTTPS hợp lệ; healthcheck, setup, static CSS trả 200.
- `/api/v1/products` trả 401 khi chưa đăng nhập; `/docs` trả 404.
- Có HSTS, cookie production, kiểm tra nguồn POST đúng HTTPS và chặn nguồn lạ.
- Thiếu mã thiết lập trả 403: khách truy cập không thể tự chiếm tài khoản chủ tiệm.
- Reload ASGI thành công; database trước/sau có cùng SHA-256, integrity_check=ok,
  schema=4, không tạo sản phẩm/đơn/tài khoản demo.
- Trang thiết lập hiển thị trong trình duyệt, không có lỗi JavaScript console.
- Wheel Linux cài offline thành công; FastAPI 0.162.0, Python 3.11, một worker.

## Bước của chủ cửa hàng

Mở trang `/setup`, nhập mã từ file riêng
`.local/PYTHONANYWHERE_SETUP.txt`, đặt họ tên, tên đăng nhập và mật khẩu của bạn.
Chưa tạo tài khoản chủ tiệm hoặc dữ liệu kinh doanh trên server; người dùng tự chọn
thông tin đăng nhập. Sau thiết lập, kiểm tra một giao dịch thử theo `DEPLOY.md`.

## Quản trị

API token được tạo theo xác nhận của người dùng, lưu tại
`.local/pythonanywhere-credentials.json`, không có trong Git hoặc ZIP bàn giao.
Mã thiết lập riêng cũng chỉ ở `.local` và file cấu hình private trong tài khoản hosting.
Không upload file `.env`, database local hay lịch sử Git.

Xem `DEPLOY.md` cho cách cập nhật và sao lưu. FastAPI trên PythonAnywhere dùng
ASGI beta; gói Free có hạn mức và cần theo dõi ngày gia hạn website trong tài khoản.
Ảnh kiểm chứng: `output/deploy-review/pythonanywhere-live.jpg`.
