<?php
$host = 'sql204.infinityfree.com';
$user = 'if0_43333923';
$pass = 'taphoa360'; // Mật khẩu XAMPP để trống
$db   = 'if0_43333923_taphoa360_db';

$conn = new mysqli($host, $user, $pass, $db);

// Kiểm tra kết nối
if ($conn->connect_error) {
    die("Lỗi kết nối CSDL: " . $conn->connect_error);
}

$conn->set_charset("utf8mb4");
?>