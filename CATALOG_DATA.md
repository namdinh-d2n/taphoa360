# Danh mục, giá tham khảo và địa chỉ Việt Nam

Bộ dữ liệu bổ sung gồm **520 mặt hàng có ảnh**, thuộc **57 danh mục có sản phẩm**.
Khung phân loại đầy đủ có **17 nhóm / 102 danh mục con**; các danh mục chưa nhập
hàng vẫn chọn được và hiển thị trạng thái chưa có mặt hàng phù hợp. Đây là bộ hàng
tạp hóa khởi đầu, không phải toàn bộ SKU đang bán tại Việt Nam.

## Nguồn và giá

- `data/catalog-reference.json` lưu từng tên hàng, đúng quy cách, giá bán quan sát,
  URL nguồn, URL ảnh, ảnh local và checksum. Nguồn là các thẻ sản phẩm công khai
  trên [Bách Hóa Xanh](https://www.bachhoaxanh.com/), được đọc ngày 13/11/2026.
  Giá có thể là ưu đãi tại thời điểm đọc và thay đổi theo khu vực/thời gian; giá
  tham khảo không tự trở thành chương trình sale của tiệm.
- Giá nhập **mẫu** = khoảng 80% giá tham khảo, làm tròn xuống 500đ. Đây không phải
  báo giá bán buôn. Nhà cung cấp được tạo với tên **NCC mẫu — [nhóm hàng]**, không
  dùng thông tin của nhà sản xuất để giả làm đối tác thật. Không điền số điện thoại
  hoặc địa chỉ giả cho các nhà cung cấp này.
- Mỗi mặt hàng mẫu liên kết với nhà cung cấp mẫu cùng nhóm. Màn hình quản trị và
  danh mục nhà cung cấp ghi rõ dữ liệu mẫu. Nhập giá thực tế khi tạo phiếu nhập;
  giá nhập trên liên kết sẽ được đánh dấu lại sau khi lưu báo giá thực tế.
- Khi chủ tiệm sửa giá bán, sản phẩm chuyển sang nguồn giá `STORE`; nhập lại bộ
  tham khảo không ghi đè giá đã sửa. Các giá nhập/bán và tồn của 6 SKU đã có được
  giữ nguyên. Chỉ bổ sung phân loại và ảnh khi trước đó chưa khai báo.

## Ảnh và nhập dữ liệu

520 ảnh sản phẩm theo đúng SKU/quy cách được lưu WebP 480×480 tại
`static/catalog-images`, có link nguồn trong manifest. 6 SKU cũ chưa đủ thông tin
định danh đúng ảnh/quy cách được dùng hình minh họa có nhãn rõ; chủ tiệm có thể
thay bằng ảnh chụp bao bì thực tế tại **Cửa hàng online → Ảnh & danh mục**.

Lệnh xem trước và nhập lại có thể chạy nhiều lần:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/import_catalog_reference.py
.\.venv\Scripts\python.exe -X utf8 scripts/import_catalog_reference.py --apply
```

Script sao lưu trước khi áp dụng; SKU `REF-BHX-*` là khóa chống trùng. Không tạo tồn,
lô, phiếu nhập, đơn mua, công nợ hoặc thanh toán. Hàng mới có tồn 0 và chưa đặt mua
được; nhập hàng qua phiếu nhập thực tế để bán. Không tự sửa các phiếu nhập cũ nhằm
khớp dữ liệu tham khảo. Báo cáo đối chiếu lần nhập nằm tại
`.local/catalog-import-report.json`; snapshot trước nâng cấp/nhập nằm trong
`.local/backups/`.

## Danh mục và chọn địa chỉ

- Shop có bộ chọn **Nhóm hàng**, sau đó là các nút danh mục con. Nhóm bánh kẹo gồm
  snack/bim bim, bánh quy/gạo/xốp/quế/que, Chocopie, bánh bông lan/tươi, kẹo cứng/dẻo,
  kẹo cao su, socola, hạt, trái cây sấy, rau câu và đồ ăn vặt khác.
- Khung phân loại tiếp tục bao phủ sữa, đồ uống, cà phê/trà, mì/gạo/bột, gia vị,
  đồ hộp, rau củ, trái cây, thịt/cá/trứng, đông lạnh, hàng mát, vệ sinh, cá nhân,
  mẹ/bé, gia đình và thú cưng. Loại bảo quản được lưu riêng với danh mục hàng hóa.
- Nhân viên chọn cùng khung phân loại khi thêm/sửa sản phẩm. Nhãn và danh mục
  tùy chỉnh của tiệm vẫn được giữ trong nhóm riêng.

`data/vietnam-addresses.json` là snapshot offline của [Province Open API v2](https://provinces.open-api.vn/),
gồm **34 tỉnh/thành và 3.321 phường/xã/đặc khu**, cấu trúc hai cấp sau sáp nhập
07/2025. File lưu URL nguồn, ngày đọc và SHA-256 của dữ liệu gốc.

Khách bấm **Nhập địa chỉ nhận** ở đầu shop hoặc điền lúc thanh toán. Có hai chế độ:

1. Chọn tỉnh/thành → chọn phường/xã → nhập số nhà/căn hộ/đường/thôn. Server kiểm
   tra phường thuộc đúng tỉnh, tự tạo bản chụp tên địa chỉ để lưu trong đơn.
2. **Tự nhập địa chỉ đầy đủ** để ghi theo cách khách đang sử dụng, kể cả cách gọi
   địa chỉ cũ. Không ép khách phải chọn mã địa giới khi dùng chế độ này.

Địa chỉ toàn quốc không phải phạm vi giao toàn quốc. Vùng/phí giao của tiệm vẫn
khai báo riêng; việc thêm bộ địa giới không tự tạo vùng giao hay phí vận chuyển.
Địa chỉ đang điền được giữ trong phiên trang, không tự lưu thông tin cá nhân vào
localStorage của thiết bị dùng chung.

Làm mới dữ liệu địa giới khi có thay đổi rồi khởi động lại ứng dụng:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/update_vietnam_addresses.py
```

Khi khách dùng shop, các danh sách được đọc từ file local, không gửi địa chỉ của
khách đến API địa giới bên ngoài.
