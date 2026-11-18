# Cửa hàng online Tạp hóa 360

Mở cửa hàng tại `/shop`. Khách được xem và tìm hàng không cần đăng nhập; khi đặt giao
cần đăng nhập số điện thoại để theo dõi đơn và tích điểm. Giỏ được lưu trong trình
duyệt trước khi đăng nhập. Tài khoản khách tách riêng với tài khoản POS/nhân viên.

Danh mục đã bổ sung khung 17 nhóm / 102 danh mục con và bộ 520 SKU tham khảo có ảnh,
giá bán công khai, giá nhập/NCC mẫu. Shop hỗ trợ chọn 34 tỉnh/thành và 3.321 phường/xã,
hoặc tự nhập địa chỉ. Xem [CATALOG_DATA.md](CATALOG_DATA.md) về nguồn, phạm vi, ảnh,
cách nhập kho thực tế và làm mới dữ liệu địa giới.

## Luồng khách hàng

### Chi tiết sản phẩm và gợi ý mua sắm

Nhấp ảnh hoặc tên mặt hàng để mở khung chi tiết: ảnh lớn, quy cách/thương hiệu,
giá và khung sale thật (nếu có), chọn số lượng, thêm giỏ hoặc mua ngay. Mô tả dùng
nội dung tiệm đã khai báo; không tự suy đoán thành phần, dinh dưỡng hoặc công dụng.
Trên điện thoại các phần xếp dọc; hàng chưa có tồn vẫn xem được nhưng không đặt mua.

- **Có thể bạn muốn mua cùng:** tối đa 3 món đang có tồn bán được. Ưu tiên mặt hàng
  xuất hiện cùng sản phẩm đang xem trong ít nhất 3 đơn hoàn tất trong 28 ngày;
  loại đơn hủy, đơn giao chưa hoàn tất, dữ liệu cũ thiếu phân bổ và phần hàng đã trả.
  Khi chưa đủ lịch sử, gợi ý theo cặp loại hàng như bánh/sữa, trứng/rau/gia vị và
  snack/đồ uống, có nhãn giải thích. Gợi ý theo loại hàng không đẩy món đắt hơn
  `max(100.000đ, 3 × giá sản phẩm đang xem)` nếu chưa có bằng chứng mua chung.
- **Sản phẩm liên quan:** mặt hàng cùng danh mục, nhóm hàng hoặc thương hiệu,
  ưu tiên hàng còn tồn, không lặp lại sản phẩm đang xem hoặc danh sách mua kèm.
- **Khám phá sản phẩm & nhãn hàng:** nhãn hàng thật từ danh mục của tiệm, số mặt
  hàng và số còn tồn trong nhóm. Bấm một nhãn hàng để lọc danh sách; bộ lọc
  **Thương hiệu** ở shop cho phép đổi hoặc bỏ lựa chọn.

Mua kèm hiển thị giá từng món, chỉ thêm sau thao tác của khách và không tự áp dụng
giảm giá. Tồn lô hết hạn, quá giờ ngừng bán hoặc cách ly không dùng cho gợi ý mua kèm.
Giá và tồn tiếp tục được server kiểm tra lại lúc đặt đơn. Nhân viên cập nhật mô tả,
thương hiệu tại **Sản phẩm → Sửa**. API chi tiết công khai: `GET /api/shop/products/{id}`;
lọc thương hiệu: `GET /api/shop/catalog?brand=...`. Các endpoint chỉ đọc dữ liệu.

### Đặt và nhận hàng

1. Chọn khu/phường/chung cư. Phí giao, đơn tối thiểu và thời gian dự kiến hiện ngay
   từ đầu. Địa chỉ ngoài vùng giao không thể đặt.
2. Duyệt theo danh mục hoặc loại bảo quản: hàng tươi, đông lạnh, mát, đồ khô và gia
   dụng. Tìm kiếm, lọc, bán chạy/giá thấp và gợi ý phù hợp với món vừa xem hoặc giỏ.
3. Chọn **Bữa sáng dưới 50.000đ** hoặc **Thiết yếu dưới 150.000đ** để tạo giỏ đề xuất;
   khách sửa từng món/số lượng trước khi thêm. Ngân sách chưa gồm phí giao.
4. Sản phẩm cận hạn có nhãn **Dùng sớm**, hạn lô/giờ ngừng bán và điều kiện giao.
   Combo dùng sớm hiển thị lô, số lượt còn, hạn và giá trước khi thêm.
5. Khi một món hết, khách chọn **Gọi trước khi thay**, **Bỏ món hết** hoặc **Liên hệ lại**.
   Nếu tiệm cần thay đổi đơn, trạng thái chuyển sang **Cần bạn duyệt thay đổi**;
   tiệm chưa giữ hàng hoặc giao khi khách chưa đồng ý.
6. Đăng nhập ở bước đặt: họ tên, số điện thoại, địa chỉ, lựa chọn xử lý hết món,
   COD hoặc QR. Điểm có thể giữ để đổi, nhưng điểm mới chỉ cộng theo hàng nhận thật.
7. Với QR: bấm **Xác nhận đặt hàng** → mã QR hiện ngay trên trang theo dõi, kèm
   danh sách món, số tiền, mã đơn và ngân hàng đã cấu hình. Hàng được giữ theo FEFO
   30 phút. Có nút phóng to/tải PNG để quét hoặc chọn ảnh từ thư viện app ngân hàng.
   Sau khi chuyển, bấm **Xác nhận đã thanh toán** → trạng thái **Chờ cửa hàng duyệt**.
   Đây là khai báo của khách, chưa ghi nhận thu tiền thực tế. Thu ngân/chủ tiệm
   đối chiếu giao dịch, duyệt tiền/đơn; hệ thống ghi thu và xuất hóa đơn nội bộ,
   sau đó người soạn đánh dấu đủ từng món và điều phối nhân viên giao.
   Với COD, tiệm xác nhận/giữ hàng trước, tiền ghi nhận lúc giao. Liên kết theo dõi
   riêng không cần đăng nhập để xem tiến độ; QR và hóa đơn cần đúng tài khoản chủ đơn.
8. Khi giao, khách kiểm đếm/chất lượng trước khi nhận. COD thu đúng tiền của phần
   nhận + phí giao; QR trả trước tạo khoản hoàn nếu khách không nhận một phần. Thu ngân
   hoặc chủ tiệm xác nhận hoàn bằng mã giao dịch/biên nhận. Điểm bị trừ/hoàn theo
   hàng thực nhận, không tính món bị từ chối.

## Giao hàng, hoàn và tồn

- Đơn QR mới (`PREPAY`) giữ tồn ngay khi tạo, chưa ghi thu tiền. Hết 30 phút chưa
  báo chuyển sẽ `EXPIRED`, hoàn tồn/điểm. Đã báo chuyển (`PAYMENT_REVIEW`) được giữ
  để nhân viên đối chiếu, không tự hết hạn gây mất dấu khoản khách đã chuyển. Khai
  báo chuyển muộn ở đơn hủy/hết hạn được đưa vào đối chiếu và hoàn, không tự giao.
  Đơn COD giữ tồn lúc cửa hàng xác nhận. Đơn QR cũ được giữ luồng cũ để đối soát.
- Xác nhận hàng tươi/đông lạnh/mát bị từ chối tạo tồn `HOLD` để kiểm tra; không tự
  trả lại hàng bán được. Hàng khô nguyên vẹn có thể chọn trả kho; hàng hỏng chọn loại
  bỏ. Nhân viên phải ghi lý do khi khách từ chối.
- Hàng có `sell_until` không bán sau giờ ngừng bán dù chưa hết hạn. Lô đã hết hạn,
  sale đã đóng hoặc sale hết giới hạn bị chặn ở cả POS và online.
- Sale theo giờ do chủ tiệm tạo với sản phẩm/lô, giá, số lượng và khung giờ. Giá sale
  được kiểm tra lại khi POS/online đặt; mỗi đơn không cộng combo dùng sớm với sale giờ.
- Giờ cuối ngày: vào **Cửa hàng online → Hàng cuối ngày**, kiểm hàng thực tế, đặt
  `sell_until`, lên sale nếu đủ điều kiện hoặc chuyển `HOLD`/`DISPOSED`. Không tự kéo
  dài hạn dùng; rau/thịt/cá bị từ chối luôn cách ly trước khi quyết định.

## Quản trị cửa hàng online

Mục **Cửa hàng online** có các tab:

- **Đơn online:** duyệt/giữ hàng, gửi đề nghị thay, xác nhận QR, phân công shipper,
  kiểm nhận khi giao, xác nhận COD và hoàn tiền.
- **Ảnh & danh mục:** bật/tắt bán online, danh mục, loại bảo quản, mô tả/quy cách và
  ảnh sản phẩm. Ảnh tải lên giới hạn 4 MB, JPG/PNG/WebP, lưu local trong `.local/shop-media`.
- **Hàng cuối ngày:** xem lô tươi/lạnh, giờ ngừng bán, trạng thái chất lượng và tạo sale
  cuối ngày.
- **Giờ sale vàng:** lên lịch giá sale theo giờ và giới hạn đơn vị; tránh khung trùng.
- **Quảng cáo:** tạo banner nền xanh/cam/xanh nhạt hoặc ảnh của tiệm, danh mục đích,
  thời gian bắt đầu/kết thúc và thứ tự. Banner chỉ là nội dung đã được chủ tiệm duyệt;
  không tự tạo quảng cáo từ văn bản khách gửi.
- **Giao hàng & QR:** khai báo vùng, phí, đơn tối thiểu, ETA và ngân hàng. QR VietQR
  được sinh cục bộ theo BIN, tài khoản, số tiền và mã đơn; không gọi cổng ngân hàng.

## API và quyền

- Công khai: `GET /api/shop/catalog`, `GET /api/shop/budget`.
- Khách đã đăng nhập: `POST /api/shop/quote`, `POST /api/shop/orders`,
  `GET /api/shop/orders`, `GET /api/shop/orders/{id}`, `GET /api/shop/track/{token}`,
  `GET /api/shop/orders/{id}/qr` (SVG) hoặc thêm `?format=png` để tải ảnh PNG.
- Khách duyệt sửa: `POST /api/shop/orders/{id}/approve` với `version` hiện tại.
- Nhân viên: `GET /api/v1/shop/overview`; xác nhận bằng `/confirm`, đề nghị sửa bằng
  `/propose`, phân công `/ship`, đối chiếu QR `/paid`, kiểm nhận `/deliver`, hủy `/cancel`.
  Chủ tiệm/thu ngân xác nhận COD/hoàn; nhân viên giao chỉ kiểm nhận đơn được phân công.

Mọi giá, tồn, sale, phí giao, điểm và tổng tiền do server tính lại trong transaction.
Đơn dùng `Idempotency-Key`; refresh/gửi lại không tạo trùng. API staff dùng cookie + CSRF;
API khách dùng cookie riêng + CSRF. Không lưu ảnh khách hay số thẻ; không tích hợp cổng
thanh toán tự động trong bản này.


## Điều phối, hóa đơn và người quản lý thu chi

Mở **Đơn & thu chi online** tại `/online`. Có lối tắt từ khu chủ tiệm, thu ngân và
kiểm kho. Bảng đơn có tìm kiếm/lọc theo chờ khách, cần đối chiếu, đang soạn, đang giao,
hoàn tiền và hoàn tất; hiện người soạn/người giao của từng đơn. Bảng tự tải lại khi
không mở biểu mẫu. Trang theo dõi của khách cũng tự cập nhật kết quả duyệt.

Chủ tiệm dùng **Phân công người phụ trách online** để chọn thu ngân phụ trách thu chi
và nhân viên điều phối. Chưa phân công thì chủ tiệm/nhóm vai trò hiện tại phụ trách;
chủ tiệm luôn có quyền xử lý. Người điều phối chỉ phân công, soạn/giao; việc duyệt
nhận tiền và hoàn cần thu ngân phụ trách hoặc chủ tiệm. Người được giao soạn có thể
đánh dấu từng món. Shipper chỉ kiểm nhận đơn được phân công.

Tab **Thu – chi online** chỉ tính QR đã đối chiếu, COD đã thu, hoàn đã xác nhận và
chi phí thực ghi. Khách báo chuyển chưa vào tổng thu. Có xuất CSV, chi phí đóng gói/
giao hàng, người ghi, mã giao dịch, tiền COD từng người còn giữ và biên nhận bàn giao.
Bàn giao không tạo thu tiền lần hai. Khoản chi và biên nhận có chống gửi trùng.

Duyệt QR tạo một hóa đơn nội bộ có số riêng, snapshot món/giá/điểm/phí. Hóa đơn mở/in
được trước khi giao; sau kiểm nhận sẽ có thêm phần số nhận thực tế và hoàn tiền.
Đây là hóa đơn bán hàng nội bộ, chưa tích hợp hóa đơn điện tử thuế. Không đổi tiền
hoặc tạo chứng từ giả trong dữ liệu cửa hàng khi nâng cấp; kiểm thử dùng DB riêng.

Schema 9 thêm trạng thái báo/duyệt tiền, snapshot tài khoản nhận, người soạn,
`online_invoices`, liên kết khoản tiền với đơn online, biên nhận bàn giao và chống
trùng khoản chi. Có backup `before-v9-*.db` trước nâng cấp. Các khoản/đơn cũ giữ số
liệu gốc và luồng legacy. Số tiền, tiền hoàn và tình trạng đã nhận luôn do server
kiểm tra trong transaction; không có kết nối ngân hàng tự xác nhận giao dịch.
