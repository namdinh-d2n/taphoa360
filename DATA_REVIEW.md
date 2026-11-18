# Dữ liệu cửa hàng để duyệt PR

`data/store-snapshot.json` là bản xuất **đã ẩn thông tin riêng**, schema 9, từ
cửa hàng local để review và chạy demo trên máy khác. File JSON dễ xem diff và
không phải database production hoặc bản backup nguyên trạng.

Bản này chứa 526 sản phẩm, 17 nhà cung cấp, 521 liên kết nhà cung cấp/sản phẩm,
10 lô tồn, 4 phiếu nhập, 2 đơn POS và 5 đơn online, cùng nghiệp vụ thu/chi, công
nợ, lịch ca và lương với danh tính demo. Số lượng chính xác nằm tại trường
`counts` trong file; giá, tồn, trạng thái, số tiền và quan hệ nghiệp vụ được giữ.

Các phần đã xử lý trước khi đưa lên Git:

- Tên người dùng, nhân viên, khách hàng và đối tác thật thay bằng nhãn demo.
- Điện thoại, email, địa chỉ cụ thể, GPS, ghi chú tự do, mã giao dịch thật được bỏ
  hoặc thay bằng giá trị demo. Mã đơn/lô cũng được đổi để không lộ tham chiếu thật.
- Không xuất mật khẩu/băm mật khẩu, token đăng nhập/theo dõi, CSRF hoặc khóa
  chống gửi trùng từ dữ liệu thật. Tài khoản lịch sử bị vô hiệu hóa khi nhập.
- Không xuất `.env`, số tài khoản ngân hàng hoặc thông tin xác thực triển khai.
- Không xuất session, login attempts, đăng ký chờ duyệt, audit logs và khóa nội bộ.
- Chỉ giữ ảnh đã có trong thư mục `static/` được version control. Ảnh tải lên
  riêng trong `.local/shop-media/` không được đưa vào snapshot.
- Phiếu lương/số tiền nghiệp vụ vẫn hiện với danh tính demo để kiểm tra tính toán;
  đây không phải dữ liệu chuẩn bị để vận hành một cửa hàng thật.

## Tạo database demo mới

Dùng môi trường Python của repository, cài requirements như README. Xem trước:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/store_snapshot.py restore
```

Tạo bản riêng để review (script hỏi mật khẩu mới của chủ tiệm, không lưu mật khẩu
vào JSON hay Git):

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/store_snapshot.py restore --apply --database .local/review-demo.db --username review_owner --name "Chủ tiệm demo"
$env:SQLITE_PATH = (Resolve-Path .local/review-demo.db).Path
$env:PORT = '8002'
$env:SEED_DEMO = 'false'
.\.venv\Scripts\python.exe -X utf8 start_local.py --no-browser
```

Mở `http://127.0.0.1:8002/login/owner` và đăng nhập tài khoản chủ tiệm vừa tạo.
Không sử dụng tài khoản cũ: chúng chỉ là tham chiếu lịch sử, đã khóa. QR bị để
trống cấu hình; người review tự cấu hình bằng dữ liệu thử nếu cần. Có thể xem giá,
ảnh, tồn và các nghiệp vụ đã ẩn danh trong các màn hình tương ứng.

Công cụ chỉ tạo database **chưa tồn tại**, từ chối ghi đè `.local/taphoa360.db`
hoặc bất kỳ file có sẵn, và từ chối import khi `APP_ENV=production`. Tạo chủ tiệm
mới là thay đổi chỉ trên bản demo; không sửa database cửa hàng nguồn. Các đơn cũ
có thể hết thời gian chờ khi mở demo do ngày dữ liệu đã qua.

## Cập nhật snapshot

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/store_snapshot.py export
```

Lệnh mặc định đọc database trong cấu hình hiện tại và chỉ ghi file JSON đã xử lý.
Kiểm tra diff và quyền công khai trước mỗi lần push. Không dùng `git add -f` với
`.local/`, `.env` hoặc các file `.db` để thay cho quy trình xuất này.

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_store_snapshot.py -v
```

Kiểm thử tạo database tạm để kiểm tra toàn vẹn/khóa ngoại, số lượng từng bảng,
giá/tồn khớp snapshot, chỉ tài khoản chủ tiệm mới đăng nhập được, không xuất lại
băm mật khẩu và từ chối ghi đè database có sẵn.
