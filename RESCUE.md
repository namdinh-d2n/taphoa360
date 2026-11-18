# Giải cứu hàng cận hạn

Tính năng nằm trong **Đề xuất thông minh → Giải cứu hàng cận hạn**. Phân tích
chạy trong ứng dụng từ dữ liệu SQLite, không dùng API trả phí hay tải mô hình.

## Quy trình

1. Nhập kho theo lô, khai báo đúng giá vốn và hạn dùng. Chọn khoảng cần theo dõi
   đến 7, 14 hoặc 30 ngày nữa.
2. Xem số lượng còn, mục tiêu bán mỗi ngày và lượng có thể còn khi hết hạn nếu
   tốc độ bán gần đây giữ nguyên. Mục tiêu tính cả hôm nay và ngày hết hạn;
   với lô nằm sau, tính cả lượng các lô cần bán trước theo FEFO.
3. Bấm **Xem phương án combo**, chọn hàng ghép, mức giảm đề nghị và số combo tối đa.
   Bấm **Tính phương án** để xem giá, doanh thu và lãi gộp nếu bán hết số đã chọn.
4. Chủ tiệm bấm **Bật combo tại POS**. Kiểm kho được xem và tính thử, không được
   bật/dừng giá bán. Mỗi lô chỉ có một combo đang bật; dừng combo cũ để đổi phương án.
5. Thu ngân chọn combo trong **Bán hàng**, nhập số combo và bấm **Thêm combo vào giỏ**.
   Mỗi combo gồm 1 đơn vị của hàng cận hạn và 1 đơn vị của hàng ghép. Hàng thêm ngoài
   combo vẫn tính giá thông thường. Hóa đơn lưu tên combo, số lượt và tiền giảm.
6. Theo dõi số lượt đã dùng/khả dụng trong trang phân tích; chủ tiệm có thể dừng combo.

## Cơ sở đề xuất

- Tốc độ bán sử dụng tối đa 28 ngày gần đây, chỉ lấy đơn `managed=1` đã hoàn tất
  hoặc trả một phần, trừ số hàng đã trả. Đơn hủy, đơn giao chưa hoàn tất và dữ liệu
  đơn cũ thiếu phân bổ không dùng để dự báo.
- Cần ít nhất 7 ngày lịch sử cửa hàng và 3 đơn có bán mặt hàng để hiện ước tính.
  Nếu thiếu dữ liệu, chỉ hiện mục tiêu bán theo tồn và hạn, không giả lập tốc độ bán.
- Mô phỏng xuất theo FEFO từng ngày. Lô hết hạn được bỏ khỏi lượng có thể bán kể
  từ ngày tiếp theo; lô sau không bị coi là luôn đứng sau phần hàng đã hết hạn.
- Hàng mua chung từ ít nhất 3 đơn trong 28 ngày được ưu tiên ghép. Khi chưa đủ
  lịch sử, có gợi ý thử từ nhóm tên hàng như bánh/sữa; giao diện ghi rõ cơ sở này.
  Người dùng cũng có thể chọn hàng ghép thủ công. Không khẳng định combo sẽ làm
  nhu cầu tăng; doanh thu/lãi trong bản xem trước là tình huống **nếu bán hết**.

## Giá, tồn và giới hạn

- Combo giữ lãi gộp tối thiểu 10%, trước chi phí vận hành. Giá vốn theo lô xuất
  trước; giá được chặn theo giá vốn cao nhất của các lô hàng ghép có thể dùng trong
  giới hạn đã chọn. Mức giảm thực tế có thể thấp hơn mức đề nghị để giữ ngưỡng lãi.
- Giá vốn bằng 0 được coi là chưa khai báo; cần bổ sung trước khi tính combo.
  Nếu giá bán hiện tại không đủ khoảng giảm, ứng dụng yêu cầu xem lại giá bán/giá vốn.
- Combo chỉ dùng lô còn đủ đơn vị nguyên, đang bán và đứng đầu thứ tự FEFO. Lô
  hết hạn hoặc hết hàng không được đưa vào combo. Tồn lẻ cũ không tự làm tròn lên.
- Mở combo không trừ/reserve tồn. Khi tạo đơn, server kiểm tra lại trạng thái,
  hạn lô, tồn, giá hiện tại, giá vốn, số mặt hàng trong giỏ và giới hạn lượt trong
  cùng transaction. Không lấy giá do trình duyệt tự tính làm giá quyết định.
- Mỗi đơn áp dụng một combo, không cộng giảm giá thủ công hoặc đổi điểm. Tiền
  giảm chỉ phân bổ cho hai sản phẩm thuộc combo; các hàng khác giữ giá thường.
- Gửi lại cùng đơn dùng Idempotency-Key không trừ lượt lần nữa. Hủy đơn giao hợp lệ
  hoàn tồn và trả lại giới hạn lượt; trả hàng dùng giá net đã lưu, không tự cộng lại
  lượt ưu đãi để tránh tái sử dụng. Các điều kiện tiền mặt/chốt ca vẫn áp dụng như cũ.
- Khi lô hết hạn/hết hàng hoặc giá vốn thay đổi khiến không giữ được ngưỡng lãi,
  combo không xuất hiện trong danh sách khả dụng tại POS. Server kiểm tra lại khi
  thanh toán, kể cả giỏ đã mở từ trước.

## Dữ liệu và kiểm thử

Schema 6 thêm `rescue_campaigns` và thông tin combo trong `orders`; tự tạo snapshot
`before-v6-*.db` trước nâng cấp. Không viết lại giá, phân bổ lô hoặc đơn cũ.
Khôi phục qua giao diện yêu cầu cùng schema hiện tại; bản trước nâng cấp được giữ
để phục hồi thủ công.

API phân tích: `GET /api/v1/rescue?days=7`, `POST /api/v1/rescue/quote`.
Chủ tiệm tạo/dừng tại `POST /api/v1/rescue/campaigns` và
`POST /api/v1/rescue/campaigns/{id}/stop`. POS đọc các combo còn dùng được qua
`GET /api/v1/rescue/campaigns`, gửi `rescue_campaign_id` và `rescue_sets` khi tạo đơn.
API cookie cần CSRF; server kiểm tra quyền theo vai trò.

Kiểm thử bao gồm FEFO qua ngày hết hạn, lịch sử thiếu dữ liệu, mua chung sau hủy/trả,
ngưỡng lãi, giá thay đổi, quyền/CSRF, giới hạn bán đồng thời, chống gửi trùng, hoàn
tiền và nâng cấp không đổi dữ liệu cũ. Database kiểm thử riêng, không ghi vào cửa hàng.
