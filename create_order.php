<?php
header("Content-Type: application/json; charset=UTF-8");
require_once 'db.php';

// Nhận JSON từ App Android gửi lên
$input = json_decode(file_get_contents('php://input'), true);

if (!$input || empty($input['items'])) {
    echo json_encode(["success" => false, "message" => "Dữ liệu đơn hàng không hợp lệ"]);
    exit;
}

$orderCode = 'DH-' . date('Ymd-His');
$createdBy = $input['created_by'] ?? 'Thu ngân';
$totalAmount = $input['total_amount'] ?? 0;
$paymentMethod = $input['payment_method'] ?? 'Tiền mặt';

// 1. Thêm vào bảng orders
$stmt = $conn->prepare("INSERT INTO orders (order_code, created_by, total_amount, payment_method) VALUES (?, ?, ?, ?)");
$stmt->bind_param("ssds", $orderCode, $createdBy, $totalAmount, $paymentMethod);

if ($stmt->execute()) {
    $orderId = $stmt->insert_id;
    
    // 2. Thêm danh sách chi tiết mặt hàng
    $stmtItem = $conn->prepare("INSERT INTO order_items (order_id, product_name, quantity, price, subtotal) VALUES (?, ?, ?, ?, ?)");
    foreach ($input['items'] as $item) {
        $name = $item['name'];
        $qty = $item['quantity'];
        $price = $item['price'];
        $subtotal = $qty * $price;
        $stmtItem->bind_param("isddd", $orderId, $name, $qty, $price, $subtotal);
        $stmtItem->execute();
    }
    
    echo json_encode([
        "success" => true,
        "message" => "Tạo đơn thành công",
        "order_code" => $orderCode,
        "order_id" => $orderId
    ]);
} else {
    echo json_encode(["success" => false, "message" => "Lỗi khi lưu đơn hàng"]);
}
?>