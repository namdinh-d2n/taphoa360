# Kiến trúc Retail v3

## Bản triển khai 3.1

`serve.py` là entry point production một worker, đọc PORT/proxy từ môi trường.
Docker lưu SQLite/WAL và backups trong `/data`, đặt múi giờ Việt Nam và hạ quyền
xuống UID 10001 trước khi chạy server. PythonAnywhere dùng DOMAIN_SOCKET và script bootstrap; dữ liệu nằm ngoài thư mục mã nguồn.

`APP_ENV=production` bắt buộc tắt demo/reload, bật Secure cookie, không cho wildcard
host; bước tạo chủ tiệm đầu tiên cần SETUP_TOKEN ngẫu nhiên >=32 ký tự. Dữ liệu cũ
được giữ nguyên khi tắt SEED_DEMO. `/health/live` kiểm tra tiến trình,
`/health/ready` đọc database/schema. Giới hạn request body 1 MB trước parse, kiểm tra
JSON scalar/container trước domain handlers, thêm CSP/host validation.

Frontend dùng SVG icon cục bộ, menu mobile, retry khi tải lỗi, timeout HTTP và
phiên bản tài nguyên 3.1; không cần build Node/CDN. Xem `QA_REPORT.md` và `DEPLOY.md`.

## Thành phần

| Thành phần | Vai trò |
|---|---|
| `app.py` | Khởi tạo, migration, đăng ký API, trang đăng nhập, ứng dụng và hóa đơn |
| `config.py` | Nạp `.env`, địa chỉ server và đường dẫn database |
| `retail/database.py` | Migration cộng thêm, sao lưu trước nâng cấp, transaction và khóa ghi |
| `retail/auth.py` | Chủ tiệm đầu tiên, mật khẩu, phiên, CSRF, phân quyền, khóa tài khoản |
| `retail/access.py` | Trang riêng theo vai trò, đích sau đăng nhập và quyền truy cập trang |
| `retail/inventory.py` | Sản phẩm, lô FEFO, biến động kho, nhập hàng, đối tác, công nợ, đề xuất |
| `retail/sales.py` | Tạo đơn chống trùng, phân bổ tiền giảm, thanh toán, giao hàng, hoàn/hủy, chốt ca |
| `retail/people.py` | Nhân viên, ca, lịch, chấm công, xin nghỉ/đổi ca và lương |
| `retail/reporting.py` | Báo cáo, kiểm tra và khôi phục sao lưu |
| `retail/api.py` | Endpoint được kiểm tra quyền và các alias dành cho client cũ |
| `static/` | Giao diện JS module và CSS, chạy offline về tài nguyên giao diện |
| `templates/login.html`, `retail.html`, `receipt.html` | Khung đăng nhập, ứng dụng, phiếu bán hàng |
| `tests/test_retail.py` | Kiểm thử tích hợp trên SQLite tạm |

Các router Python cũ ở thư mục gốc, template cũ và `backup_php/` không được đăng ký
trong runtime v3. `db.py` chỉ được dùng để tạo schema nền/dữ liệu mẫu khi database mới.

Schema 4 bổ sung `registrations`: đăng ký theo vai trò, trạng thái chờ/duyệt/từ chối,
người xét duyệt, ghi chú và liên kết tài khoản. Migration schema 4 chạy riêng sau schema 3,
có snapshot trước nâng cấp và không chạy lại logic tạo tồn đầu của schema 3.
Trang `register.html`/`static/register.js` gửi yêu cầu công khai, chưa tạo user hay session.
Chỉ chủ tiệm được duyệt; tạo tài khoản, liên kết/tạo hồ sơ nhân viên và đóng yêu cầu trong
cùng transaction. Băm mật khẩu trong yêu cầu được xóa sau khi duyệt/từ chối.

## Dữ liệu và bất biến

- Mỗi nghiệp vụ ghi nằm trong một `BEGIN IMMEDIATE`, commit hoặc rollback toàn bộ.
  Kết nối bật foreign keys, timeout 20 giây. Mỗi hàm giữ kết nối trong phạm vi thao tác.
- `products.stock` bằng tổng `stock_batches.remaining`. Mọi thay đổi tồn sinh
  `stock_movements`. Lô hết hạn bị loại khỏi lượng có thể bán.
- `orders` lưu thông tin khách/thu ngân, giá trước giảm, giảm giá, điểm và mã chống trùng.
  `order_items` có `product_id` và bản chụp tên/giá/vị trí; `order_allocations` lưu lô,
  lượng xuất và giá vốn tại thời điểm bán.
- Giá bán lấy từ database/khuyến mãi còn hiệu lực. Tiền là số đồng nguyên; lượng hàng
  nhập mới là số nguyên. Giá trị không hữu hạn, số lượng lẻ, âm và vượt giới hạn bị từ chối.
  Dữ liệu lẻ cũ được giữ nguyên để đối chiếu; POS chỉ cung cấp lượng đơn vị nguyên.
  Hủy đơn cũ hoặc trả toàn bộ phần còn lại giữ số lượng chính xác để đảo nghiệp vụ lịch sử.
- Tổng net của chi tiết bằng tổng đơn. Hoàn từng phần dùng chênh lệch làm tròn lũy kế
  để tổng hoàn không vượt số tiền hàng. Hàng hỏng không được cộng lại tồn.
- `payments` ghi thu dương/chi âm, phương thức và ca. `account_entries` ghi công nợ.
  Hoàn đơn bán chịu trừ dư nợ trước, phần đã thu được hoàn bằng tiền mặt/chuyển khoản.
- Khách nhận 1 điểm mỗi 10.000đ sau giảm, đổi 1 điểm = 100đ. Trả hàng hoàn điểm đã đổi
  và thu hồi điểm đã tích theo tỷ lệ. Nếu điểm đã tích đã dùng hết, giá trị thiếu được
  khấu trừ khỏi tiền hoàn để tránh tích điểm nhiều lần bằng việc mua rồi trả.
- `cash_shifts` chỉ có một ca mở cho mỗi tài khoản; mọi thu/chi tiền mặt cần có ca mở.
  Không sửa số liệu của ca đã chốt; khoản hoàn muộn được ghi vào ca hiện tại.
- Đơn giao: PENDING → PROCESSING → SHIPPING → COMPLETED. Chỉ được xuất giao khi đã
  đánh dấu đủ mặt hàng và có shipper. Hủy trước khi giao hoàn tồn và tiền trong cùng transaction.
- `attendance` mới lưu cả ngày giờ cho ca qua đêm. Ca mới không được trùng giờ ngày
  kế bên. Công có đủ vào/ra mới được tính lương. Bảng lương đã duyệt khóa sửa công/lịch
  và tính lại; bảng mẫu cũ phải tính lại trước khi duyệt.
- `audit_log` ghi người, hành động, đối tượng và chi tiết. Đổi vai trò/khóa tài khoản
  hoặc đổi mật khẩu thu hồi phiên. Khôi phục database thu hồi tất cả phiên.

## Sao lưu và khôi phục

SQLite backup API tạo snapshot nhất quán vào thư mục `backups` cạnh database.
Trước restore: kiểm tra tên file, tính toàn vẹn SQLite, khóa ngoại, phiên bản schema,
tài khoản chủ tiệm và đủ bảng/cột. Sau đó tạo snapshot an toàn, khôi phục, xóa phiên và
lưu nhật ký người yêu cầu. Bản trước v3 được giữ để phục hồi thủ công, không dùng trực
 tiếp trong giao diện v3.

## Giao diện

Các trang chính dùng cùng thanh điều hướng, tùy vai trò. Nội dung từ database được
render bằng `textContent`/DOM node, không ghép dữ liệu người dùng vào `innerHTML`.
Form có trạng thái lỗi, khóa nút khi gửi; POS giữ mã chống trùng qua lần thử lại.
SSE dùng mã sự kiện để nối lại và chỉ trả sự kiện của đơn được giao đối với shipper.
Trang receipt dùng Jinja2 autoescape. Các bảng hỗ trợ màn hình hẹp bằng cuộn ngang.

## Kiểm chứng và giới hạn

Chạy bộ kiểm thử bằng lệnh trong README. Dữ liệu test được tạo và dọn trong thư mục
 tạm, không thay thế dữ liệu thực. Browser QA dùng port riêng và tài khoản giả lập.

Bản này triển khai trên SQLite một cửa hàng. Không có mã Android trong repo; client
Android cần cập nhật đăng nhập, idempotency và action chấm công. Cổng thanh toán,
hóa đơn điện tử, dịch vụ AI bên ngoài, geofence và đồng bộ đa chi nhánh chưa tích hợp.
Các giới hạn nghiệp vụ và cách xử lý dữ liệu cũ được ghi chi tiết trong README.
