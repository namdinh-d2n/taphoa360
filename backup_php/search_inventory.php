<?php
header('Content-Type: application/json; charset=utf-8');
require_once 'db.php'; // Gọi file db.php chứa kết nối $conn (mysqli)

// Lấy từ khóa tìm kiếm từ phương thức GET
$keyword = isset($_GET['keyword']) ? $conn->real_escape_string($_GET['keyword']) : '';

// Truy vấn chuẩn theo các cột thực tế trong hình ảnh bảng products của bạn
$query = "SELECT id, product_name AS name, sku, stock, unit, shelf_location AS location, 150000 AS price 
          FROM products 
          WHERE product_name LIKE '%$keyword%' OR sku LIKE '%$keyword%' 
          LIMIT 10";

$result = $conn->query($query);
$items = [];

if ($result) {
    while ($row = $result->fetch_assoc()) {
        $items[] = [
            'id' => (int)$row['id'],
            'name' => $row['name'],
            'sku' => $row['sku'],
            'stock' => (float)$row['stock'],
            'unit' => $row['unit'],
            'location' => $row['location'],
            'price' => (float)$row['price']
        ];
    }
}

// Trả về kết quả JSON
echo json_encode([
    'success' => true,
    'data' => $items
], JSON_UNESCAPED_UNICODE);

$conn->close();
?>