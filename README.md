# Tạp hóa 360 - Quản trị Bán lẻ Thông minh (Python Backend)

Hệ thống quản lý bán lẻ, kho hàng, trợ lý AI và API phục vụ cho Mobile App Android. Dự án đã được chuyển đổi hoàn toàn từ PHP sang Python (FastAPI + Jinja2 + PyMySQL / SQLite).

---

## 🚀 Hướng dẫn khởi chạy

### Cách 1: Sử dụng file chạy nhanh (Windows)
Chỉ cần nhấp đúp chuột vào file:
```
run.bat
```

### Cách 2: Khởi chạy bằng dòng lệnh
1. Cài đặt các thư viện cần thiết:
   ```bash
   pip install -r requirements.txt
   ```
2. Khởi chạy server:
   ```bash
   python app.py
   ```
Server sẽ chạy mặc định tại: **`http://127.0.0.1:8000`**

---

## 🌐 Danh sách các trang Web Dashboard & API

### 1. Giao diện Web (Dashboard)
- **Trang Tổng quan**: `http://127.0.0.1:8000/` hoặc `http://127.0.0.1:8000/index.php`
- **Quản lý Đơn hàng**: `http://127.0.0.1:8000/orders.php` hoặc `/orders`
- **Quản lý Kho & Trợ lý AI**: `http://127.0.0.1:8000/warehouse.php` hoặc `/warehouse`
- **Bản đồ Cửa hàng 360°**: `http://127.0.0.1:8000/store_map.php` hoặc `/store_map`

### 2. API Endpoints cho Mobile App Android
Hệ thống hỗ trợ cả URL chuẩn và alias đuôi `.php` để tương thích 100% với App Android sẵn có mà không cần sửa code app:
- **Tạo đơn hàng mới (POST JSON)**:
  - `POST /create_order.php` hoặc `POST /api/create_order`
- **Lấy đơn cần xử lý & danh sách nhặt hàng (GET)**:
  - `GET /get_merchant_orders.php` hoặc `GET /api/get_merchant_orders`
- **Tìm kiếm tồn kho (GET)**:
  - `GET /search_inventory.php?keyword={tu_khoa}` hoặc `GET /api/search_inventory`
- **Realtime Server-Sent Events (GET Stream)**:
  - `GET /stream_orders.php` hoặc `GET /api/stream_orders`
- **Tài liệu API tương tác tự động (Swagger UI)**:
  - `GET /docs`

---

## 🗄️ Cơ sở dữ liệu (Database)
- Module [db.py](file:///c:/xampp/htdocs/taphoa360/db.py) tự động kết nối thông minh:
  1. Thử kết nối MySQL Remote (`sql204.infinityfree.com`) hoặc MySQL Local (`127.0.0.1:3306`).
  2. Nếu không có kết nối MySQL, tự động chuyển sang cơ sở dữ liệu **SQLite** (`taphoa360.db`) có sẵn dữ liệu mẫu thực tế, giúp hệ thống luôn hoạt động ổn định và sẵn sàng chạy thử nghiệm ngay lập tức.