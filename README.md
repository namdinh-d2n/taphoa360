# Tạp hóa 360 · Retail v3

**Bản chuẩn bị triển khai 3.1:** xem [DEPLOY.md](DEPLOY.md) để deploy trên PythonAnywhere
Free với dữ liệu lưu riêng, HTTPS và cửa hàng trống. FastAPI dùng ASGI beta.
Có healthcheck, cấu hình production, script triển khai qua API và GitHub Actions.
Gói Free có hạn mức tài nguyên; không đảm bảo hoạt động 24/7 miễn phí.

Ứng dụng quản lý một cửa hàng: POS, kho theo lô, đơn giao hàng, đổi trả, khách hàng,
nhà cung cấp, công nợ, chốt ca, nhân sự và báo cáo. Backend **FastAPI**, giao diện
**Jinja2 + JavaScript/CSS cục bộ**, database **SQLite**. Không cần build frontend hoặc CDN.

## Chạy trên Windows

Yêu cầu Python 3.11+. Nhấp đúp **`BAT_TAPHOA360.bat`** để bật toàn bộ hệ thống và tự
mở trang đăng nhập trong trình duyệt. `run.bat` cũng gọi cùng bộ khởi động này.
Hoặc dùng PowerShell tại thư mục dự án:

```powershell
python -m venv .venv
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe app.py
```

Mở **http://127.0.0.1:8000**. Lần đầu, tạo tên đăng nhập và mật khẩu chủ tiệm
(từ 10 ký tự). Không có mật khẩu quản trị mặc định. Sau đó đăng nhập và thêm tài khoản
cho từng nhân viên tại **Cài đặt → Tài khoản & quyền**.

### Đăng nhập và khu làm việc theo vai trò

Trang `/login` cho chọn vai trò, mỗi vai trò có trang đăng nhập và khu làm việc riêng:

| Vai trò | Đăng nhập | Trang làm việc |
|---|---|---|
| Chủ tiệm | `/login/owner` | `/owner`: toàn bộ quản lý, mở được cả ba khu nhân viên |
| Thu ngân | `/login/cashier` | `/cashier`: POS, ca tiền, khách hàng và đổi trả |
| Kiểm kho | `/login/inventory` | `/inventory`: nhập, kiểm kê, lô và chuẩn bị đơn |
| Giao hàng | `/login/shipper` | `/shipper`: đơn được phân công, địa chỉ và xác nhận giao |

Tài khoản phải đúng vai trò của trang đăng nhập. Chọn vai trò không thay đổi quyền tài khoản.
Sau đăng nhập hệ thống chuyển thẳng tới khu phù hợp; truy cập trang không có quyền được
chuyển về trang của mình. Nút **Đăng xuất** luôn nằm ở đầu trang, trên cả desktop và điện thoại,
và thu hồi phiên hiện tại trước khi về trang đăng nhập của vai trò.

Số lượng nhập/bán/kiểm kê mới là số nguyên (1, 2, 3…), ô nhập tăng/giảm mỗi lần 1 và API
từ chối số lẻ. POS hiển thị phần nguyên của lượng tồn có thể bán. Số lẻ đã lưu trước nâng cấp
không bị tự ý làm tròn trong database/lịch sử; dùng kiểm kê với lý do để điều chỉnh tồn thật.

### Đăng ký theo vai trò

Mở `/register` hoặc bấm **Đăng ký** trên trang đăng nhập của vai trò:
`/register/owner`, `/register/cashier`, `/register/inventory`, `/register/shipper`.
Nhập họ tên, tên đăng nhập, mật khẩu từ 10 ký tự, xác nhận mật khẩu và điện thoại (tùy chọn).
Đăng ký thành công hiển thị mã yêu cầu và trạng thái **Chờ chủ tiệm duyệt**; chưa cấp phiên đăng nhập.

Chủ tiệm vào **Cài đặt → Duyệt đăng ký** để duyệt hoặc từ chối kèm lý do. Khi duyệt,
có thể chọn hồ sơ nhân viên đang hoạt động chưa liên kết tài khoản; nếu để trống,
hệ thống tạo hồ sơ mới với mức lương 0 để chủ tiệm cấu hình sau. Vai trò được duyệt
là vai trò đã đăng ký; chỉnh quyền sau đó tại **Tài khoản & quyền** nếu cần.
Đăng ký thêm chủ tiệm cũng phải được chủ tiệm hiện tại duyệt. Cửa hàng chưa có tài khoản
được chuyển tới `/setup` để tạo chủ tiệm đầu tiên như trước.

Tên đăng nhập không phân biệt hoa/thường, không được trùng tài khoản hay yêu cầu đang chờ.
Yêu cầu đã từ chối có thể gửi lại. Mật khẩu chỉ lưu dạng băm; danh sách duyệt không trả về
mật khẩu/băm. Tối đa 10 lần gửi hợp lệ sơ bộ trong một giờ cho mỗi địa chỉ truy cập.
API: `POST /api/register`; chủ tiệm dùng `GET /api/v1/registrations` và
`POST /api/v1/registrations/{id}/review` với `status=APPROVED` hoặc `REJECTED`.

Tính năng đăng ký nâng schema từ 3 lên 4, tự sao lưu trước nâng cấp, không tạo lại tồn đầu
hoặc thay đổi đơn hàng cũ. Bản sao lưu trước schema 4 được giữ để phục hồi thủ công;
giao diện khôi phục chỉ chấp nhận schema hiện tại.

File bật nhanh tự chuyển vào thư mục dự án, tạo `.venv`/`.env` khi thiếu, chỉ cài thư viện
khi phiên bản chưa khớp `requirements.lock.txt`, rồi bật server và database SQLite.
Trình duyệt chỉ mở khi server sẵn sàng. Nếu hệ thống đã chạy, nhấp lần nữa chỉ mở lại
trang đăng nhập, không bật thêm server. Nếu cổng bị ứng dụng khác chiếm, cửa sổ báo lỗi.

Giữ cửa sổ server mở khi sử dụng; nhấn **Ctrl+C** để dừng. Bộ bật nhanh tắt tự reload
để chạy ổn định; khi phát triển cần reload, dùng `python app.py` như trên.
Lần cài thư viện đầu tiên cần Internet. Những lần chạy tiếp theo dùng thư viện đã cài.
Có thể dùng `BAT_TAPHOA360.bat --no-browser` nếu không muốn tự mở trình duyệt.

## Môi trường và dữ liệu

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `HOST` | `127.0.0.1` | Chỉ máy hiện tại; dùng `0.0.0.0` khi cần truy cập từ cùng LAN |
| `PORT` | `8000` | Cổng ứng dụng |
| `RELOAD` | `true` | Tự nạp lại khi sửa Python; dùng `false` khi vận hành |
| `DB_TYPE` | `sqlite` | Retail v3 yêu cầu SQLite |
| `SQLITE_PATH` | `.local/taphoa360.db` | Đường dẫn tương đối với thư mục dự án hoặc đường dẫn tuyệt đối |

`config.py` đọc `.env`; biến môi trường tiến trình được ưu tiên. `.env`, `.venv`,
`.local` được loại khỏi Git. File database gốc `taphoa360.db` được giữ nguyên.

- Khi nâng cấp database cũ, migration tự sao lưu trước khi thêm bảng/cột.
- Tồn kho cũ được chuyển thành lô `OPENING`; không tự trừ lại tồn cho đơn cũ.
- Giá vốn lô cũ mặc định là 0 nếu chưa có dữ liệu. Chủ tiệm vào **Kho → Sửa lô**
  để khai báo giá vốn/hạn dùng trước khi bán. Lô đã xuất không được sửa giá vốn lịch sử.
- Database mới với `SEED_DEMO=true` được khởi tạo với dữ liệu mẫu của repo. Đây là dữ liệu demo,
  không phải lịch sử kinh doanh/chấm công thật.
- Runtime mới không dùng MySQL. Các cấu hình MySQL và module cũ còn giữ để tham khảo,
  chưa có migration cho các nghiệp vụ v3 trên MySQL.

## Quy trình sử dụng

1. **Thiết lập:** tạo chủ tiệm; thêm hồ sơ nhân viên, tài khoản và liên kết nhân viên.
2. **Hàng hóa:** thêm SKU, mã vạch, đơn vị, giá, khu/kệ và ngưỡng tồn. Thêm nhà cung cấp.
3. **Nhập kho:** lập phiếu có nhiều dòng, số lượng, giá vốn, mã lô và hạn dùng; phần
   chưa thanh toán đi vào công nợ nhà cung cấp.
4. **Bán hàng:** mở ca nếu nhận tiền mặt; quét mã bằng máy quét dạng bàn phím hoặc gõ
   SKU + Enter; chọn khách, giảm giá/đổi điểm, phương thức nhận và thanh toán. Có thể
   kết hợp tiền mặt, chuyển khoản và công nợ trong một đơn. Server tính lại giá/tổng.
5. **Giao hàng:** xác nhận → soạn hàng → đánh dấu từng món → phân công tài khoản giao
   hàng → đang giao → hoàn tất. Shipper chỉ thấy đơn được giao cho mình.
6. **Đổi trả:** mở đơn đã hoàn tất, chọn dòng và số lượng trả; khai báo hàng nhập lại
   hay hỏng. Hệ thống tính tiền hoàn sau giảm giá, điều chỉnh điểm và công nợ.
   Đổi hàng thực hiện bằng trả hàng và tạo đơn thay thế, mỗi giao dịch có lịch sử riêng.
7. **Cuối ca:** nhập tiền thực đếm, giải trình chênh lệch và chốt ca. Tiền dự kiến đã
   tính cả thu nợ, hoàn tiền, nhập hàng và trả nợ bằng tiền mặt.
8. **Nhân sự:** tạo ca, xếp ca, chấm vào/ra; nhân viên gửi xin nghỉ/đổi ca và chủ tiệm
   xét duyệt. Điều chỉnh công cần lý do. Tính lương theo công/tháng hoặc giờ, thêm
   thưởng/khấu trừ, rồi duyệt và khóa bảng lương.
9. **Báo cáo:** chọn khoảng ngày để xem doanh số thuần, giá vốn, lợi nhuận gộp,
   hàng bán chạy, thu/chi và trạng thái đơn. Xuất CSV sản phẩm, doanh số, bảng lương.
10. **Sao lưu:** vào Cài đặt để tạo/tải bản sao. Khôi phục yêu cầu nhập `KHOI PHUC`,
    kiểm tra toàn vẹn, tự sao lưu trạng thái hiện tại và đăng xuất mọi phiên.

## Quyền truy cập

| Vai trò | Phạm vi |
|---|---|
| Chủ tiệm | Toàn bộ nghiệp vụ; giá bán, tài khoản, duyệt lương, báo cáo, sao lưu và nhật ký |
| Thu ngân | POS, khách hàng, công nợ khách, đơn hàng, soạn hàng, trả/hủy đơn, ca tiền mặt |
| Kiểm kho | Sản phẩm, nhập hàng, kiểm kê, lô, nhà cung cấp, công nợ nhà cung cấp, soạn và phân công giao |
| Giao hàng | Đơn được phân công; xác nhận giao thành công |
| Mọi nhân viên | Lịch, công, lương của bản thân và yêu cầu nghỉ/đổi ca khi tài khoản đã liên kết hồ sơ |

Quyền được kiểm tra tại API, không chỉ ẩn nút giao diện. Mật khẩu dùng PBKDF2;
phiên đăng nhập hết hạn sau 8 giờ, cookie HttpOnly/SameSite, yêu cầu ghi dữ liệu
bằng cookie cần CSRF token. Có giới hạn thử sai đăng nhập và nhật ký nghiệp vụ.

## API / tích hợp Android

Swagger: **/docs**. API mới dưới `/api/v1`. Đường dẫn `.php` cũ cho các trang và API
bán hàng vẫn được giữ. Client cũ cần bổ sung đăng nhập và mã chống tạo trùng.

```http
POST /api/login
Content-Type: application/json

{"username":"thu_ngan","password":"mat-khau-cua-ban"}
```

Phản hồi chứa `token` cho client mobile dùng `Authorization: Bearer <token>`.
Web dùng cookie và `X-CSRF-Token` lấy từ `/api/session`.

```http
POST /api/v1/orders
Authorization: Bearer <token>
Idempotency-Key: <uuid-duy-nhat-cho-lan-thanh-toan>
Content-Type: application/json

{
  "items": [{"product_id": 1, "quantity": 2}],
  "payment_method": "TRANSFER",
  "discount": 0,
  "fulfillment": "PICKUP"
}
```

- Mã chống trùng phải giữ nguyên khi gửi lại cùng yêu cầu sau lỗi mạng; không dùng
  lại cho giỏ hàng khác. Tên/giá/tổng do client gửi không thay thế giá trong database.
- `payments` hỗ trợ tối đa 3 dòng `{method, amount}` với `CASH`, `TRANSFER`, `DEBT`;
  tổng phải khớp số tiền server tính. `DEBT` cần `customer_id`.
- `fulfillment=DELIVERY` cần `apartment`. `PICKUP` hoàn tất tại quầy.
- Alias: `/create_order.php`, `/search_inventory.php`, `/get_merchant_orders.php`,
  `/stream_orders.php` cùng các URL `/api/...` tương ứng.
- SSE `/api/v1/events` bắt đầu từ hiện tại; dùng `Last-Event-ID` hoặc `?after=` để
  tiếp tục từ mã sự kiện. Không phát lại toàn bộ đơn cũ khi mở trang.
- Chấm công dùng `action=IN` hoặc `OUT` rõ ràng. API nhân sự cũ áp dụng quyền mới.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kiểm thử tạo database tạm, kiểm tra transaction/rollback, bán đồng thời, FEFO,
chống đơn trùng, đổi trả, công nợ, điểm, chốt ca, phân quyền/CSRF, lương và khôi phục.
Không ghi vào database cửa hàng. Kiểm tra giao diện trên server thử riêng với dữ liệu demo.

## Phạm vi triển khai

- Hệ thống dành cho một cửa hàng dùng SQLite, một replica/worker. Đã có cấu hình
  triển khai PythonAnywhere/Docker; chưa đồng bộ nhiều chi nhánh. Xem DEPLOY_STATUS.md để biết trạng thái triển khai thực tế.
- Ghi nhận tiền mặt/chuyển khoản là thao tác xác nhận của thu ngân; chưa nối cổng thanh toán/ngân hàng.
- Hóa đơn in là phiếu bán hàng nội bộ; chưa tích hợp nhà cung cấp hóa đơn điện tử.
- Đề xuất thông minh dùng quy tắc tồn thấp, không bán 30 ngày và hạn dùng trong 7 ngày;
  không cần API AI bên ngoài. Giảm giá áp dụng theo sản phẩm, xuất kho vẫn ưu tiên FEFO.
- Sơ đồ nhóm theo khu/kệ đã khai báo, không phải bản đồ định tuyến theo tọa độ.
- GPS lưu thông tin người dùng gửi; chưa có xác minh geofence hoặc chống giả vị trí.
- Lương tính từ công thực tế và thưởng/khấu trừ nhập tay; chưa tích hợp thuế, bảo hiểm hoặc chuyển lương.
- Đơn cũ thiếu phân bổ lô/thanh toán được giữ để tra cứu; không tự động hoàn/hủy tồn của chúng.

Xem [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) để biết cấu trúc và các bất biến dữ liệu.
