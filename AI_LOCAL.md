# AI đọc hóa đơn cục bộ

Tính năng dùng mô hình OCR chạy bằng CPU để nhận dạng chữ, sau đó tách bảng hàng
và đối chiếu danh mục của nhà cung cấp. Không dùng dịch vụ LLM, tài khoản AI,
API key hoặc API trả phí. Khi đọc ảnh, ứng dụng không gọi dịch vụ Internet.

## Sử dụng

1. Vào **Kho hàng → + Nhập hàng**, chọn đúng nhà cung cấp.
2. Bấm **AI đọc ảnh hóa đơn**, chọn ảnh JPG, PNG hoặc WebP, tối đa 8 MB.
3. Bấm **Đọc ảnh và tạo bản nháp**. Đối chiếu ảnh với tên hàng, đơn vị, số lượng,
   đơn giá và sản phẩm được ghép. Sửa các ô hoặc bỏ chọn dòng không cần dùng.
4. Bấm **Đưa các dòng đã chọn vào phiếu nháp**. Các dòng đang nhập và ghi chú
   được giữ; dòng trống mặc định được thay bằng các dòng AI. Với hàng chưa khớp,
   chọn sản phẩm từ danh mục hoặc dùng nút thêm hàng có sẵn / tạo sản phẩm mới.
5. Kiểm tra lại đơn vị, giá vốn, mã lô, hạn dùng và tiền đã trả. Bấm **Ghi nhận
   phiếu nhập** mới tăng tồn, ghi thanh toán và công nợ.

Đọc ảnh và đưa vào nháp không tạo sản phẩm, nhà cung cấp, phiếu nhập hoặc công nợ.
Hủy bản nháp không phát sinh nghiệp vụ kho. Ảnh/chữ nhận dạng không được lưu vào
database; file upload tạm được đóng sau khi xử lý.

## Cài trên máy khác

Dùng Python 3.11 hoặc 3.12 và môi trường `.venv` của dự án. Cài lần đầu cần Internet:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/setup_local_ai.py
```

Script cài `requirements-ai.txt`, tải mô hình Latin từ kho RapidAI chính thức và
kiểm tra SHA-256 trước khi ghi file. Khởi động lại ứng dụng sau khi cài. Những lần
đọc ảnh tiếp theo chỉ dùng file trong máy, không tự tải thêm mô hình. Bộ chạy nhanh
`BAT_TAPHOA360.bat` vẫn dùng được như trước.

`.env` có `AI_INVOICE_ENABLED=true`; đặt `false` để tắt đọc ảnh. Mô hình lưu ở
`.local/models/latin_PP-OCRv5_rec_mobile.onnx`, không đưa vào Git. Dữ liệu cửa hàng
không cần migration cho tính năng này. Thư viện AI là tùy chọn, không bắt buộc cho
runtime POS hoặc các bản triển khai thiếu tài nguyên như PythonAnywhere Free.

## Phạm vi nhận dạng

- Tối ưu ảnh hóa đơn in có bảng tên hàng, số lượng và đơn giá rõ, chụp thẳng,
  đủ sáng. Hỗ trợ số tiền nguyên VND và phân cách hàng nghìn dấu chấm/phẩy.
- Dấu tiếng Việt, ảnh mờ/nghiêng, chữ viết tay và bảng phức tạp có thể đọc sai.
  Giao diện hiển thị phần chưa rõ và chữ gốc để đối chiếu, không tự ghi kho.
- Không tự quy đổi hộp/thùng/lốc. Nếu đơn vị khác danh mục, không tự chọn sản phẩm.
  Không làm tròn số lượng lẻ; người dùng cần kiểm tra trước khi xác nhận.
- Không tự lấy giá bán, hạn dùng, mã lô, thuế hay giảm giá từ hóa đơn. Tổng dòng
  khác tổng hóa đơn được đánh dấu để kiểm tra; số tiền trên ảnh không tự thay
  trường tiền đã trả. Hiện hỗ trợ một ảnh mỗi lượt, chưa đọc PDF.
- Mỗi tiến trình chỉ đọc một ảnh tại một thời điểm, dùng một luồng CPU cho từng
  mô hình. Thời gian đọc tùy ảnh và tài nguyên trống trên máy.

## API và kiểm thử

`GET /api/v1/ai/invoices/status` báo khả năng sử dụng. `POST
/api/v1/ai/invoices/preview` nhận multipart `image` và `supplier_id`, trả bản nháp,
kết quả ghép hàng và các điểm cần kiểm tra. Chỉ chủ tiệm/kiểm kho có quyền; yêu cầu
dùng cookie cần CSRF token. Endpoint không ghi dữ liệu nghiệp vụ. Giới hạn upload
8 MB, ảnh tối đa 16 triệu điểm ảnh; giới hạn JSON 1 MB của các API khác giữ nguyên.

```powershell
$env:RUN_LOCAL_OCR_TESTS = '1'
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

Không đặt biến này thì bài smoke test chạy mô hình thật được bỏ qua, các kiểm thử
tách dòng, phân quyền, upload và bản nháp vẫn chạy. Mô hình/thư viện không được
tải tự động trong kiểm thử. Các kiểm thử dùng database riêng.

Nguồn mô hình và thư viện:

- [RapidOCR](https://github.com/RapidAI/RapidOCR),
  [cấu hình và checksum mô hình](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml).
- [RapidOCR ONNX Runtime trên PyPI](https://pypi.org/project/rapidocr-onnxruntime/1.4.4/).
- [Mô hình Latin PP-OCRv5](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/latin_PP-OCRv5_rec_mobile.onnx).
- SHA-256: `b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a`.
