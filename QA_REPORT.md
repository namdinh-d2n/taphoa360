# Địa chỉ giao hàng theo tài khoản — 17/11/2026

- Toàn bộ kiểm thử cuối: **199 ca, 198 đạt**, 1 ca OCR thực tùy chọn bỏ qua.
- 10 ca mới: lưu qua đăng xuất/đăng nhập lại/phiên trình duyệt mới, tách tài khoản,
  chuẩn hóa địa chỉ tỉnh/phường, chặn sửa khi thiếu phiên/CSRF hoặc sai origin,
  khu ngừng phục vụ không xóa địa chỉ, đơn thành công nhớ nơi nhận, gửi lại đơn
  cũ không ghi đè địa chỉ vừa sửa, lỗi đặt đơn không lưu, dùng lại cho đi chợ hộ,
  đổi tỉnh bỏ cửa hàng không tương thích và snapshot review loại dữ liệu riêng.
- Chrome headless với server/database QA riêng: tự nhắc địa chỉ lần đầu, lưu và
  hiện trên Giao tới, reload không nhắc lại, form sửa tự điền, checkout dùng địa
  chỉ lưu, đi chợ hộ tự điền tỉnh/địa chỉ, tài khoản khác không thấy dữ liệu cũ,
  đăng nhập lại khôi phục đúng địa chỉ; không lỗi JS/tràn ngang ở mobile 390px.
- Schema 14 tạo bảng riêng theo shop_accounts.id, có backup trước nâng cấp,
  không đổi địa chỉ trong đơn đã tạo và không tự lấy dữ liệu từ lịch sử đơn cũ.
  Form gửi expected_account_id để chặn lưu nhầm khi đổi phiên lúc đang nhập.
- Ruff F/E9, compileall, node --check và git diff --check đạt. Server chính đã
  chạy schema 14; QA tách biệt, không cập nhật địa chỉ khách thật khi kiểm thử.

# Lối vào khách hàng và nội bộ — 17/11/2026

- `/` mở `/shop` cho khách/không có phiên nội bộ. Phiên chủ tiệm, thu ngân, kiểm
  kho, giao hàng hợp lệ chuyển về đúng khu làm việc. `/admin` là lối nội bộ:
  chưa đăng nhập → `/login`, đã đăng nhập → khu vai trò; chưa thiết lập → `/setup`.
- Tài khoản mua hàng không được dùng vào nội bộ. Nếu có cả phiên khách và nhân
  viên trong cùng trình duyệt, `/` ưu tiên phiên nhân viên; `/shop` vẫn mở trực tiếp.
- Đã cập nhật liên kết Chủ tiệm & nhân viên ở shop, nút về mua hàng ở trang đăng
  nhập và launcher trên máy tiệm mở `/admin`.
- 65 kiểm thử đạt: 6 ca điều hướng mới, 53 ca retail/phân quyền hiện có và 6 ca
  production. Có trường hợp phiên hết hạn, tài khoản khóa, đăng xuất, khách đăng
  nhập, cả bốn vai trò và lần đầu thiết lập. Database kiểm thử riêng.
- Compileall, Ruff F/E9 cho kiểm thử mới và git diff --check đạt. Máy chủ local
  đã khởi động lại; HTTP kiểm tra `/` → `/shop`, `/admin` → `/login`, health 200.

# Đi chợ hộ: cập nhật trực tiếp, cửa hàng demo và QR — 16/11/2026

- Bộ kiểm thử cuối: **183 ca, 182 đạt**, 1 ca OCR thực tùy chọn bỏ qua.
- 8 ca bổ sung kiểm tra phát SSE sau commit, không phát sau rollback, giới hạn
  dữ liệu theo khách/nhân viên được phân công, thu hồi stream khi hết phiên,
  tỉnh/cửa hàng hợp lệ, chặn số lượng thập phân và QR đúng số còn phải trả.
- Schema 13 giữ nguyên đơn cũ, tạo backup trước nâng cấp, thêm 36 điểm demo tại
  34 tỉnh/thành trong môi trường development/test; Hà Nội và TP.HCM có 2 điểm.
  Cửa hàng demo không mở rộng vùng giao của luồng mua hàng cũ; kiểm thử checkout
  và production sạch đều đạt. Các điểm demo dùng chung dữ liệu vận hành hiện có.
- Chrome headless với API thật trên database QA riêng: mở Đi chợ hộ tại /shop
  không điều hướng/tải lại (navigation_count=0); chọn tỉnh và cửa hàng liên động;
  ô số lượng step=1 và từ chối 1.001; đơn mới xuất hiện bên nhân viên trong vòng
  chờ kiểm thử 4 giây; các bước duyệt khách/nhân viên tự hiện không bấm tải lại.
- QR ngân hàng tải ảnh thật, khi thu 100.000đ trên khoản dự kiến 300.000đ thì hộp
  QR đang mở tự chuyển còn 200.000đ. Chọn tiền mặt ẩn QR, chọn chuyển khoản hiện
  lại. Phần bản chốt chưa duyệt không tăng mức được chuyển của khách.
- Biểu mẫu bản nháp giữ nguyên khi có cập nhật hai chiều, kể cả sau khi đã mở/đóng
  QR. Đã xem ảnh giao diện desktop/mobile 390px; không tràn ngang hoặc lỗi JS.
- Ruff F/E9, định dạng Python/Prettier cho module mới và node --check toàn bộ
  static/*.js đạt; git diff --check đạt. Không gửi email, không chuyển tiền thật
  trong kiểm thử. Server chính đã chạy schema 13 tại 8000, QR dùng cấu hình ngân
  hàng sẵn có; server QA được tắt sau thử nghiệm.

# Đi chợ hộ — bản đầu, 16/11/2026

- Toàn bộ unittest: **175 ca, 174 đạt**, 1 bỏ qua (OCR thực tùy chọn).
- 20 kiểm thử đi chợ hộ: hai bước khách duyệt, thay thế có ảnh/lý do, bỏ món/chọn
  lại, thời hạn và phiên bản duyệt, chặn thu quá mức, trả trước 300.000đ → tổng
  295.000đ → hoàn đúng 5.000đ, chống trùng thu/chi, ca tiền mặt, xuất kho một lần,
  xử lí đồng thời, khiếu nại sau quyết toán, giới hạn giảm/hoàn và ảnh riêng tư.
- Migration schema 12 tạo backup, chạy lại an toàn khi bảng đã tồn tại. Đã sửa
  lỗi phát hiện bởi kiểm thử nâng lại từ schema 9; các kiểm thử khôi phục/OTP,
  báo cáo, sản phẩm, online, nhân sự và snapshot review đều đạt.
- Chrome headless với server/database riêng cổng 8002: tạo yêu cầu bằng UI khách,
  nhân viên báo giá, khách duyệt dự kiến, phân công, chọn và ghi chất lượng,
  ghi nhận trả trước, gửi/duyệt bản chốt, mua/giao, khách kiểm nhận, hoàn dư có
  biên nhận, ghi chi, quyết toán; khách khiếu nại sau đó và nhân viên duyệt khoản
  hoàn mới ở trạng thái chờ hoàn. Dùng API thật, giao dịch giả lập, không gửi thư.
- Desktop 1366/1440px và mobile 390px: không lỗi JavaScript, không tràn ngang;
  đã xem ảnh và sửa ảnh trống bị hiện null, nút phản hồi trùng và danh sách mobile.
- Prettier định dạng frontend mới; Ruff kiểm tra F/E9 và định dạng Python mới.
  node --check toàn bộ static/*.js, compileall và git diff --check đạt.
- Bản local đã chạy tại cổng 8000. Thông báo đi chợ hộ hiện trong ứng dụng, cập nhật
  mỗi 15 giây khi trang đang mở; chưa tích hợp push/SMS/email cho loại đơn này.
  Chuyển khoản/hoàn tiền do nhân viên thực hiện và đối chiếu; ảnh minh chứng cần
  sao lưu cùng thư mục database. Xem ERRANDS.md để vận hành và phân quyền.

# Khôi phục mật khẩu bằng email OTP — 16/11/2026

- Luồng thực hiện: nhập email → nhận OTP 6 chữ số → nhập và xác thực OTP → nhập,
  xác nhận mật khẩu mới → đăng nhập lại. Không cấp quyền đổi mật khẩu trước bước
  xác thực. Email khôi phục chủ tiệm đã liên kết được giữ nguyên.
- Toàn bộ unittest: **155 ca, 154 đạt**, 1 bỏ qua (OCR thực cần bật riêng).
  Trong đó 23 ca khôi phục kiểm tra SMTP/TLS, mã có số 0 ở đầu, hết hạn 10 phút,
  giới hạn 5 lần nhập sai, gửi lại sau 60 giây, giới hạn theo giờ, dùng mã một lần,
  gửi lại hủy mã cũ và tranh chấp xác thực/đổi mật khẩu đồng thời.
- Quyền đặt mật khẩu mới hết hạn sau 5 phút. Đổi mật khẩu thu hồi mọi phiên đăng
  nhập, OTP và quyền khôi phục của tài khoản; đổi email/quyền, khôi phục sao lưu
  cũng thu hồi thông tin khôi phục tương ứng.
- Migration 10 → 11 tạo snapshot trước nâng cấp, giữ nguyên tài khoản và dữ liệu
  kinh doanh, vô hiệu hóa liên kết khôi phục cũ. Xuất review loại OTP/email/token;
  snapshot review schema 9/10 vẫn nhập được.
- Chrome headless 1366×1000 và 390×844: cả ba bước, gửi lại mã, mã sai không mở
  form mật khẩu, xác thực đúng mới chuyển bước, giữ số 0 đầu, xác nhận mật khẩu,
  trạng thái thành công; không có lỗi JS hoặc tràn ngang trên mobile.
  API trình duyệt được giả lập; kiểm thử tích hợp dùng API thật và SMTP giả lập.
- Toàn bộ static/*.js qua node --check; compileall cho mã thay đổi và
  git diff --check đạt. Đã xem ảnh desktop và mobile để kiểm tra bố cục.
- Server cổng 8000 đã nạp `/api/verify-reset-otp` và schema 11. **Chưa gửi thư thật:**
  SMTP_PASSWORD chưa được cấu hình. Không thay đổi mật khẩu chủ tiệm khi test.

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
