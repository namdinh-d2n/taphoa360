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

## Khôi phục tài khoản qua email OTP (schema 11)

`retail/password_recovery.py` quản lý ba bước: gửi email OTP, xác thực OTP và đặt
mật khẩu mới. Mã 6 số có hiệu lực 10 phút, tối đa 5 lần nhập sai. Gửi lại cách
nhau ít nhất 60 giây, hủy yêu cầu OTP cũ; giới hạn 5 email/giờ cho một hộp thư và
20 yêu cầu/giờ cho một địa chỉ truy cập. Thông báo giống nhau cho email đã/chưa
đăng ký và tài khoản đã khóa.

Mỗi yêu cầu có challenge ngẫu nhiên 256 bit; chỉ SHA-256 của challenge được lưu.
OTP lưu HMAC-SHA256 với khóa là challenge gốc (không có trong database). Xác thực
so sánh hằng thời gian, tăng số lần sai và commit trước khi trả lỗi. Khi đúng,
transaction xóa OTP và cấp quyền đặt lại mật khẩu ngẫu nhiên 256 bit, chỉ lưu
SHA-256, có hiệu lực 5 phút. Hai yêu cầu xác thực/sử dụng đồng thời chỉ một yêu
cầu thành công. API đặt mật khẩu mới kiểm tra quyền này độc lập với giao diện.

Đổi mật khẩu/email/quyền hoặc khôi phục backup thu hồi OTP và quyền đặt lại mật
khẩu; đổi mật khẩu thu hồi phiên đăng nhập. Dấu vân tay mật khẩu/email ngăn sử
dụng mã sau khi dữ liệu tài khoản thay đổi ngoài API. SMTP dùng STARTTLS/SSL có
kiểm tra chứng chỉ, gửi sau commit ngoài khóa ghi. Lỗi gửi thư chỉ xóa OTP của
lần gửi đó; không đưa mã hay lỗi chứa thông tin SMTP vào log.

`users.email` duy nhất khi khác rỗng. Công cụ `scripts/set_recovery_email.py` gắn
email cho chủ tiệm cũ từ máy chủ, có backup và audit. Schema 11 sao lưu trước
nâng cấp và xóa token từ cơ chế gửi liên kết cũ; giữ nguyên email và nghiệp vụ.

## Đi chợ hộ (schema 12–13)

`errand_schema.py` migration cộng thêm; `errands.py` giữ quy tắc nghiệp vụ,
`errand_api.py` nối xác thực khách/nhân viên và minh chứng riêng tư. UI dùng
`errands-view.js` chung cho trang khách `errands-shop.js` và khu nhân viên
`errands-admin.js`. Schema 13 thêm tỉnh/cửa hàng demo và phương thức thanh toán. `live_events.py` đánh thức SSE sau commit; revision theo quyền khách/nhân viên, không cần polling. QR do server tính từ số tiền đã duyệt còn phải thu. Khách duyệt dự kiến, từng thay thế và bản chốt cuối, kiểm tra
phiên bản và thời hạn tại server trước khi mua. `errand_money` nối với `payments`
để ghi thu/hoàn/chi và chốt ca, có mã chống trùng và mã biên nhận duy nhất.

Xem ERRANDS.md về trạng thái, phân quyền, kiểm hàng và quyết toán. Báo cáo tách
chỉ tiêu đi chợ hộ; ảnh nằm ngoài SQLite và phải sao lưu cùng dữ liệu. Tất cả
bảng đi chợ hộ được loại khỏi snapshot review để ẩn nội dung riêng của khách.

## Dữ liệu và bất biến

Schema 9 bổ sung luồng QR trả trước (`PREPAY`): giữ hàng khi tạo đơn, QR/số tiền/tài
khoản nhận được chụp theo đơn; khách báo chuyển đưa sang `PAYMENT_REVIEW` nhưng
không ghi thu. Thu ngân phụ trách/chủ tiệm đối chiếu và duyệt tiền trong transaction,
ghi `payments.online_order_id`, xuất `online_invoices` một lần và chuyển chuẩn bị
giao. Soạn từng món/phân công được kiểm tra trước khi bắt đầu giao. Hóa đơn nội bộ
có snapshot khi duyệt và hiển thị phần kiểm nhận/hoàn thực tế sau giao. Đơn QR cũ
giữ `LEGACY`, không viết lại trạng thái/giá hoặc chứng từ cũ khi nâng cấp.

`online_workflow.py` quản lý giữ/hoàn tồn, báo/duyệt tiền, phân công trách nhiệm,
khoản chi có idempotency và biên nhận bàn giao COD. Báo chuyển chưa vào thu; bàn
giao COD không tạo thêm một khoản thu. Khoản hết hạn chưa báo chuyển được trả tồn/
điểm; báo chuyển muộn ở đơn hủy/hết hạn đi vào đối chiếu và hoàn, không tự giao.
Đã báo chuyển không tự hết hạn trước khi nhân viên xử lý. Quyền người phụ trách
được kiểm tra ở API, chủ tiệm luôn có quyền quản lý. Có snapshot `before-v9-*.db`.

Schema 6 thêm `rescue_campaigns` và bản chụp tên/số lượt combo trong `orders`, có
snapshot trước nâng cấp. `retail/rescue.py` phân tích tồn cận hạn, mô phỏng FEFO,
thống kê mua chung và tính giá bảo vệ lãi gộp; chỉ chủ tiệm bật/dừng combo.
`sales.create_order` kiểm tra lại combo trong transaction, phân bổ giảm giá riêng
cho hai mặt hàng và dùng `orders` để tính giới hạn lượt (không đếm đơn hủy).
Đơn gửi lại không đếm/trừ kho lần nữa; hoàn tiền dùng net_subtotal đã lưu.
`static/rescue.js` cung cấp bản xem trước; POS hỗ trợ chọn một combo trên mỗi đơn.
Phân tích cục bộ không gọi API bên ngoài hoặc gán mức tăng nhu cầu giả định.

Schema 7 thêm storefront: `shop_accounts`, `shop_sessions`, `delivery_zones`,
`shop_banners`, `timed_sales`, `online_orders`, `online_items`, `online_events` và
`shop_points_ledger`; đồng thời thêm danh mục/loại bảo quản/mô tả/ảnh online cho sản
phẩm, `sell_until`/`quality_status` cho lô và `shipping_fee` cho đơn. Migration tự
sao lưu trước khi thêm bảng/cột. Khách xem công khai nhưng checkout cần tài khoản
khách riêng; token theo dõi chỉ trả trạng thái/các khoản tiền, không trả địa chỉ.
`retail/commerce.py` tính server-side catalog, ngân sách, cặp mua chung, sale giờ,
giữ điểm, COD/QR, FEFO giữ tồn và kiểm nhận/hoàn; `retail/shop_api.py` nối các quyền
khách/nhân viên. Hàng tươi/lạnh bị từ chối đi vào `HOLD`, không tự bán lại.

`retail/invoice_ai.py` dùng RapidOCR/ONNX trên CPU, nạp mô hình Latin PP-OCRv5 từ
đĩa khi cần. Không có lời gọi mạng lúc đọc ảnh. Kết quả OCR được coi là văn bản
không tin cậy, chỉ tách dữ liệu/so tên, không sinh SQL hay thực thi chỉ dẫn trên ảnh.
`retail/invoice_api.py` cung cấp preview chỉ đọc cho chủ tiệm/kiểm kho, có CSRF và
giới hạn upload riêng 8 MB. Không thay đổi schema hoặc nghiệp vụ. `static/invoice-ai.js`
cho đối chiếu/chỉnh kết quả trước khi chuyển vào các dòng nhập thông thường.
Việc tạo hàng mới hoặc ghi kho vẫn đi qua API đã kiểm tra quyền và transaction.

Schema 5 bổ sung `supplier_products` với khóa chính `(supplier_id, product_id)`,
giá nhập riêng và mã hàng của nhà cung cấp. Migration có snapshot trước nâng cấp,
khởi tạo liên kết theo dòng phiếu nhập gần nhất cho mỗi cặp và không đổi tồn/phiếu cũ.
API tạo nhanh hàng và liên kết trong cùng transaction, SKU trống được tự tạo.
Ghi danh mục không tạo lô, biến động kho, thanh toán hay công nợ. Khi nhập hàng,
giá thực nhập cập nhật giá gợi ý của đúng nhà cung cấp; giá phiếu/lô cũ giữ nguyên.
Các client nhập hàng cũ tiếp tục được hỗ trợ: phiếu hợp lệ tự bổ sung liên kết nếu thiếu.
`static/purchasing.js` quản lý ô tìm hàng, editor thêm nhanh và hồ sơ nhà cung cấp;
editor nằm trong phiếu đang mở để không thay thế dữ liệu nháp bằng modal khác.

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
