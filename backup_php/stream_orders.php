<?php
// Tắt buffer để SSE đẩy dữ liệu ngay lập tức
@ini_set('output_buffering', 'off');
@ini_set('zlib.output_compression', false);
while (ob_get_level() > 0) {
    ob_end_flush();
}

header('Content-Type: text/event-stream; charset=utf-8');
header('Cache-Control: no-cache');
header('Connection: keep-alive');
header('X-Accel-Buffering: no'); // Tối ưu cho Nginx (hoặc Apache)

require_once 'db.php';

$lastId = isset($_GET['last_id']) ? intval($_GET['last_id']) : 0;

// Gửi tín hiệu kết nối thành công ban đầu
echo "data: " . json_encode(["status" => "connected"]) . "\n\n";
flush();

while (true) {
    // Nếu người dùng tắt tab trình duyệt, dừng ngay vòng lặp để giải phóng CPU
    if (connection_aborted()) {
        break;
    }

    // Sử dụng Prepared Statement để bảo mật và tối ưu tốc độ truy vấn
    $stmt = $conn->prepare("SELECT * FROM orders WHERE id > ? ORDER BY id ASC");
    $stmt->bind_param("i", $lastId);
    $stmt->execute();
    $result = $stmt->get_result();

    if ($result && $result->num_rows > 0) {
        while ($row = $result->fetch_assoc()) {
            $orderId = (int)$row['id'];
            
            // Lấy chi tiết sản phẩm của đơn hàng
            $itemStmt = $conn->prepare("SELECT product_name, quantity, price FROM order_items WHERE order_id = ?");
            $itemStmt->bind_param("i", $orderId);
            $itemStmt->execute();
            $itemsRes = $itemStmt->get_result();
            
            $items = [];
            while ($item = $itemsRes->fetch_assoc()) {
                $items[] = $item;
            }
            $row['items'] = $items;
            
            // Gửi dữ liệu qua SSE
            echo "data: " . json_encode($row) . "\n\n";
            flush();
            
            $lastId = $orderId;
        }
    }

    // Nghỉ 2 giây trước khi check đơn mới (giảm tải 100% việc nghẽn CPU cho XAMPP)
    sleep(2);
}
?>