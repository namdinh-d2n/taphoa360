# Triển khai Tạp hóa 360 trên PythonAnywhere Free

Mục tiêu: một website HTTPS trên `<username>.pythonanywhere.com`, một worker,
database SQLite lưu trong thư mục riêng. Không cần Docker hoặc database trả phí.

## Phạm vi gói Free

Kiểm tra ngày 07/11/2026: gói Beginner có 1 website, 512 MB lưu trữ riêng, 2 console,
hạn mức CPU và kết nối Internet ra ngoài có giới hạn. Không chọn Upgrade/Subscribe.
FastAPI sử dụng tính năng **ASGI beta**: giao diện/API và chính sách giá có thể thay
đổi. Đây là lựa chọn khởi đầu miễn phí, không phải cam kết SLA cho vận hành 24/7.
Theo dõi hạn sử dụng website trong tài khoản và gia hạn miễn phí khi nền tảng yêu cầu.

Nguồn: [Pricing](https://www.pythonanywhere.com/pricing/),
[ASGI beta](https://help.pythonanywhere.com/pages/ASGICommandLine/),
[ASGI API](https://help.pythonanywhere.com/pages/ASGIAPI/).

## Đường dẫn triển khai

| Đường dẫn trong tài khoản | Nội dung |
|---|---|
| `~/taphoa360-release.zip` | Gói mã nguồn đã kiểm tra SHA-256 |
| `~/taphoa360_bootstrap.py` | Khởi tạo môi trường và chạy ứng dụng |
| `~/taphoa360-settings.json` | Domain và SETUP_TOKEN, quyền file 600 |
| `~/taphoa360-app/` | Mã nguồn được giải nén khi khởi động |
| `~/taphoa360-venv/` | Môi trường Python 3.11, chỉ cài lại khi lockfile đổi |
| `~/taphoa360-wheels.zip`, `~/taphoa360-wheels/` | Thư viện Linux để cài offline |
| `~/taphoa360-data/taphoa360.db` | Database cửa hàng, tồn tại qua cập nhật |
| `~/taphoa360-data/backups/` | Bản sao lưu do ứng dụng tạo |

`serve.py` lắng nghe Unix socket do PythonAnywhere cấp qua `DOMAIN_SOCKET`.
FastAPI phục vụ cả static file vì ASGI beta không hỗ trợ static mapping của WSGI.
Journal SQLite đặt `DELETE` cho môi trường lưu trữ chia sẻ; chỉ dùng một worker.

## Deploy từ máy này qua API

1. Đăng nhập/tạo tài khoản Free trên PythonAnywhere.
2. Account → API Token: tạo token nếu chưa có. Token cấp quyền quản lý file/website;
   giữ kín, không commit và không đưa vào ảnh chụp hoặc bản bàn giao công khai.
3. Lưu thông tin trong `.local/pythonanywhere-credentials.json`:

```json
{
  "username": "TEN_TAI_KHOAN",
  "api_token": "TOKEN_RIENG_CUA_BAN",
  "host": "www.pythonanywhere.com"
}
```

Với tài khoản EU dùng `eu.pythonanywhere.com`. `.local` được loại khỏi Git và gói ZIP.
Chạy bằng PowerShell tại thư mục dự án:

```powershell
.\.venv\Scripts\python.exe scripts/package_release.py
.\.venv\Scripts\python.exe scripts/deploy_pythonanywhere.py
.\.venv\Scripts\python.exe scripts/deploy_pythonanywhere.py --deploy
```

Lệnh không có `--deploy` chỉ kiểm tra tài khoản và phiên bản Python. Lệnh deploy
kiểm tra domain trước khi tải mã nguồn; dừng nếu đã có ứng dụng khác, không xóa
website đang tồn tại. Không upload database, `.env`, lịch sử Git hoặc dữ liệu demo.

Script tạo mã `SETUP_TOKEN` ngẫu nhiên riêng và lưu bản local trong
`.local/pythonanywhere-<username>-settings.json`. Không in mã vào logs.
ASGI worker Free không truy cập Internet: script deploy tải wheel Linux x86_64
cho Python 3.11 từ máy local, upload cùng bản release và cài bằng `--no-index`.
ASGI worker tự tạo virtualenv, cài đúng lockfile rồi khởi động ứng dụng. Lần đầu có
thể cần vài phút. Log xem ở PythonAnywhere Files trong `/var/log/` hoặc qua API.

## Cấu hình runtime

Bootstrap tự đặt: production, tắt reload/demo/docs, Secure cookie, hostname đúng
website, múi giờ Việt Nam, đường dẫn database riêng. Proxy được tin cậy chỉ trong
worker không có cổng TCP public của PythonAnywhere. Không tự đặt các cấu hình này
cho server public chạy trực tiếp.

`PUBLIC_ORIGIN=https://<username>.pythonanywhere.com` cố định nguồn HTTPS hợp lệ
cho kiểm tra CSRF khi proxy nội bộ không truyền scheme như Uvicorn mong đợi.
Nguồn khác vẫn bị từ chối; không tắt CSRF. Lệnh ASGI dùng đường dẫn đầy đủ
`/usr/local/bin/python3.11 /home/<username>/taphoa360_bootstrap.py`.

## Tạo chủ tiệm

Mở `https://<username>.pythonanywhere.com/setup`. Nhập mã SETUP_TOKEN từ file cài đặt
riêng, họ tên, tên đăng nhập và mật khẩu từ 10 ký tự. Đây là cửa hàng trống để sử dụng
thật. Sau khi tạo chủ tiệm, endpoint setup bị khóa. Đăng ký nhân viên cần chủ tiệm duyệt.

## Sau triển khai và cập nhật

- `/health/ready` phải trả `{"status":"ok"}`; `/docs` và `/openapi.json` bị tắt.
- Kiểm tra login, thêm sản phẩm/nhập hàng, bán thử và trừ tồn đúng.
- Tạo/tải backup, reload website và xác nhận dữ liệu vẫn còn.
- Trước cập nhật mã nguồn: tạo backup. Sau đó đóng gói lại và chạy `--deploy`;
  script giữ nguyên mã thiết lập và thư mục dữ liệu, chỉ reload ứng dụng này.
- Theo dõi dung lượng 512 MB cho cả virtualenv, source, database và backups.
  Tải backup về máy khác; backup cùng tài khoản không bảo vệ khi mất tài khoản.
- Khi cần quay lại bản cũ: giữ ZIP của bản đã chạy, upload lại qua script rồi reload.
  Với thay đổi schema, đối chiếu phiên bản và bản sao lưu trước khi phục hồi.
- Không xóa virtualenv, settings hoặc data nếu chưa có bản sao bên ngoài.

## Kiểm tra local

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`Dockerfile` vẫn dùng được cho một máy Linux/VPS khác nhưng không được dùng trên
PythonAnywhere Free. Cấu hình Railway đã được bỏ theo yêu cầu.
