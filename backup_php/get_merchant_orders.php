<?php
header('Content-Type: application/json; charset=utf-8');
require_once 'db.php'; // Sử dụng kết nối $conn (mysqli) từ file db.php của bạn

// 1. Lấy đơn hàng mới nhất đang cần xử lý (Trạng thái PENDING hoặc PROCESSING)
$orderQuery = "SELECT id, order_code, apartment, total_amount, payment_method, status, customer_note, created_at 
               FROM orders 
               WHERE status IN ('PENDING', 'PROCESSING') 
               ORDER BY id DESC LIMIT 1";

$orderResult = $conn->query($orderQuery);
$activeOrder = ($orderResult && $orderResult->num_rows > 0) ? $orderResult->fetch_assoc() : null;

$pickList = [];
if ($activeOrder) {
    $orderId = $activeOrder['id'];
    
    // 2. Lấy danh sách sản phẩm thuộc đơn hàng đó kèm theo vị trí kệ
    $itemsQuery = "SELECT id, product_name AS name, shelf_location AS shelfLocation, quantity, price, subtotal, is_picked AS isDone 
                   FROM order_items 
                   WHERE order_id = $orderId";
                   
    $itemsResult = $conn->query($itemsQuery);
    if ($itemsResult) {
        while ($row = $itemsResult->fetch_assoc()) {
            // Định dạng chuỗi số lượng hiển thị (Ví dụ: "2 sp")
            $qtyVal = floatval($row['quantity']);
            $row['qty'] = ($qtyVal == intval($qtyVal)) ? intval($qtyVal) . " sp" : $qtyVal . " sp";
            $row['isDone'] = (bool)$row['isDone'];
            $pickList[] = $row;
        }
    }
}

// 3. Lấy danh sách nhân viên giao hàng (Shipper nội khu)
$shippers = [];
$shippersQuery = "SELECT name, status, note FROM shippers";
$shippersResult = $conn->query($shippersQuery);
if ($shippersResult) {
    while ($row = $shippersResult->fetch_assoc()) {
        $shippers[] = $row;
    }
} else {
    // Dữ liệu dự phòng nếu bảng shippers chưa được tạo
    $shippers = [
        ["name" => "Anh Khoa", "status" => "ĐANG GIAO", "note" => "Đang giao: A2-1508"],
        ["name" => "Chị Mai", "status" => "PHÂN CÔNG", "note" => "Sẵn sàng nhận đơn"]
    ];
}

// 4. Trả về kết dạng JSON cho ứng dụng Android
echo json_encode([
    'success' => true,
    'order' => $activeOrder,
    'pick_list' => $pickList,
    'shippers' => $shippers
], JSON_UNESCAPED_UNICODE);

$conn->close();
?>