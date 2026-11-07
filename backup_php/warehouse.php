<?php
require_once 'db.php';

// 1. Lọc sản phẩm theo Kệ (Mặc định Zone B1)
$selectedZone = $_GET['zone'] ?? 'B1';
$stmtProducts = $conn->prepare("SELECT * FROM products WHERE zone_code = ?");
$stmtProducts->bind_param("s", $selectedZone);
$stmtProducts->execute();
$products = $stmtProducts->get_result();

// 2. Lấy dữ liệu gợi ý của Trợ lý ảo AI từ CSDL
$aiSuggestions = $conn->query("SELECT * FROM ai_suggestions WHERE status = 'PENDING'");

// 3. Xử lý tìm kiếm định vị sản phẩm thực tế trên bản đồ 360 độ từ CSDL
$searchKeyword = trim($_GET['q'] ?? '');
$productInfo = null;

if ($searchKeyword !== '') {
    $stmt = $conn->prepare("SELECT * FROM products WHERE product_name LIKE ? OR sku LIKE ? LIMIT 1");
    $searchTerm = "%" . $searchKeyword . "%";
    $stmt->bind_param("ss", $searchTerm, $searchTerm);
    $stmt->execute();
    $res = $stmt->get_result();
    if ($res && $res->num_rows > 0) {
        $productInfo = $res->fetch_assoc();
    }
}

// Nếu chưa tìm kiếm hoặc không tìm thấy, lấy ngẫu nhiên sản phẩm đầu tiên từ CSDL để hiển thị mặc định
if (!$productInfo) {
    $defaultRes = $conn->query("SELECT * FROM products LIMIT 1");
    if ($defaultRes && $defaultRes->num_rows > 0) {
        $productInfo = $defaultRes->fetch_assoc();
    } else {
        // Trường hợp bảng products hoàn toàn trống
        $productInfo = [
            'product_name' => 'Chưa có sản phẩm trong kho',
            'shelf_location' => 'Chưa xác định',
            'zone_code' => 'B1',
            'stock' => 0,
            'unit' => ''
        ];
    }
}
?>
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tạp hóa 360 - Quản lý Kho & Trợ lý AI</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body class="bg-[#F4F6F8] font-sans text-slate-800">

    <div class="flex h-screen overflow-hidden">
        
        <!-- SIDEBAR -->
        <aside class="w-64 bg-[#0F3A2E] text-white flex flex-col justify-between p-4 shadow-xl shrink-0">
            <div>
                <div class="flex items-center gap-3 px-2 py-3 border-b border-emerald-800/50 mb-6">
                    <div class="bg-emerald-500 p-2 rounded-xl text-white font-bold text-xl flex items-center justify-center w-10 h-10">A</div>
                    <div>
                        <h1 class="font-bold text-base leading-tight">TẠP HÓA 360</h1>
                        <span class="text-[9px] text-emerald-300 font-medium">QUẢN TRỊ BÁN LẺ THÔNG MINH</span>
                    </div>
                </div>

                <nav class="space-y-1.5 text-xs font-medium">
                    <a href="index.php" class="flex items-center gap-3 px-3.5 py-3 rounded-xl text-emerald-100/70 hover:bg-emerald-800/40 hover:text-white transition">
                        <i data-lucide="layout-dashboard" class="w-4 h-4"></i>
                        <span>Trang Tổng quan</span>
                    </a>
                    <a href="orders.php" class="flex items-center gap-3 px-3.5 py-3 rounded-xl text-emerald-100/70 hover:bg-emerald-800/40 hover:text-white transition">
                        <i data-lucide="shopping-bag" class="w-4 h-4"></i>
                        <span>Quản lý Đơn hàng</span>
                    </a>
                    <a href="warehouse.php" class="flex items-center gap-3 px-3.5 py-3 rounded-xl bg-emerald-700/70 text-white font-bold shadow-inner">
                        <i data-lucide="package" class="w-4 h-4"></i>
                        <span>Quản lý Kho (AI & Bản đồ)</span>
                    </a>
                </nav>
            </div>
        </aside>

        <!-- MAIN CONTENT -->
        <main class="flex-1 overflow-y-auto p-6 space-y-6">
            
            <header class="flex justify-between items-center">
                <div>
                    <h2 class="text-2xl font-bold text-slate-900">Quản lý kho hàng & Trợ lý AI</h2>
                    <p class="text-xs text-slate-500 mt-1">Quản lý vị trí hàng hóa trên kệ, tương tác AI bán hàng và xem bản đồ chỉ đường</p>
                </div>
            </header>

            <!-- PHẦN 1: TRỢ LÝ AI BÁN HÀNG THÔNG MINH -->
            <div class="bg-gradient-to-br from-emerald-900 to-slate-900 text-white p-6 rounded-2xl shadow-md">
                <div class="flex items-center gap-3 mb-4">
                    <div class="bg-amber-400 text-slate-900 p-2 rounded-xl font-bold"><i data-lucide="sparkles" class="w-5 h-5"></i></div>
                    <div>
                        <h3 class="font-bold text-base">Trợ lý AI Bán hàng Thông minh</h3>
                        <p class="text-xs text-emerald-300">Đề xuất chương trình bán hàng dựa trên tồn kho và hạn sử dụng FEFO từ cơ sở dữ liệu</p>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <?php if ($aiSuggestions && $aiSuggestions->num_rows > 0): ?>
                        <?php while ($ai = $aiSuggestions->fetch_assoc()): ?>
                            <div class="bg-white/10 border border-white/10 p-4 rounded-xl backdrop-blur-sm space-y-2">
                                <span class="bg-amber-400/20 text-amber-300 px-2 py-0.5 rounded text-[10px] font-bold">
                                    <?php echo $ai['suggestion_type'] === 'COMBO' ? 'GỢI Ý COMBO LỄ' : 'XẢ HÀNG CẬN HẠN'; ?>
                                </span>
                                <h4 class="font-bold text-sm text-white"><?php echo htmlspecialchars($ai['title']); ?></h4>
                                <p class="text-xs text-slate-300"><?php echo htmlspecialchars($ai['description']); ?></p>
                                <button onclick="alert('Đã áp dụng chương trình khuyến mãi!')" class="bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-bold px-3 py-1.5 rounded-lg transition mt-2">
                                    ✓ Áp dụng ngay
                                </button>
                            </div>
                        <?php endwhile; ?>
                    <?php else: ?>
                        <p class="text-xs text-slate-300 col-span-2">Chưa có đề xuất nào từ trợ lý AI.</p>
                    <?php endif; ?>
                </div>
            </div>

            <!-- PHẦN 2: BẢN ĐỒ VỊ TRÍ CỬA HÀNG 360° (DỮ LIỆU TỪ DB) -->
            <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                <div class="flex justify-between items-center">
                    <div>
                        <h3 class="font-bold text-slate-900 text-sm">Bản đồ vị trí & Chỉ đường kho 360°</h3>
                        <p class="text-[11px] text-slate-400">Tìm kiếm sản phẩm thực tế từ Database để định vị vị trí kệ hàng</p>
                    </div>
                    <form method="GET" action="warehouse.php" class="flex gap-2">
                        <input type="text" name="q" value="<?php echo htmlspecialchars($searchKeyword); ?>" placeholder="Tìm tên sản phẩm..." class="bg-slate-50 border px-3 py-1.5 rounded-xl text-xs outline-none">
                        <button type="submit" class="bg-emerald-700 text-white text-xs font-bold px-3 py-1.5 rounded-xl">Định vị</button>
                    </form>
                </div>

                <div class="border-2 border-dashed border-slate-200 rounded-2xl p-6 bg-slate-50/50 min-h-[250px] flex items-center justify-center">
                    <div class="w-full max-w-2xl bg-white border rounded-2xl p-4 grid grid-cols-5 gap-3 text-center text-xs">
                        <div class="bg-amber-50 border p-3 rounded-xl"><span class="text-[9px] font-bold text-amber-800">KHU A</span><p class="font-bold text-slate-800">ĐỒ KHÔ</p></div>
                        <div class="bg-slate-50 border p-3 rounded-xl"><p class="font-bold text-slate-700">DÃY A1</p></div>
                        
                        <!-- Vùng hiển thị động dựa trên Zone của sản phẩm tìm được từ DB -->
                        <div class="bg-emerald-50 border-2 border-emerald-500 p-3 rounded-xl relative shadow-sm">
                            <span class="text-[10px] font-bold text-emerald-800">ZONE: <?php echo htmlspecialchars($productInfo['zone_code']); ?></span>
                            <div class="absolute -top-3 left-1/2 -translate-x-1/2 bg-emerald-600 text-white text-[9px] px-2 py-0.5 rounded-full font-bold truncate max-w-[140px]">
                                📍 <?php echo htmlspecialchars($productInfo['product_name']); ?>
                            </div>
                            <div class="bg-emerald-100 py-1 rounded font-bold text-[10px] mt-2 text-emerald-900 truncate">
                                <?php echo htmlspecialchars($productInfo['shelf_location']); ?>
                            </div>
                        </div>

                        <div class="bg-slate-50 border p-3 rounded-xl"><p class="font-bold text-slate-700">DÃY C1</p></div>
                        <div class="bg-blue-50 border p-3 rounded-xl"><span class="text-[9px] font-bold text-blue-800">KHU E</span><p class="font-bold text-slate-800">ĐỒ MÁT</p></div>
                    </div>
                </div>
            </div>

            <!-- PHẦN 3: SƠ ĐỒ KỆ & DANH SÁCH SẢN PHẨM TỪ DATABASE -->
            <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="font-bold text-slate-800 text-sm">Danh mục tồn kho theo Kệ (Đang chọn: Zone <?php echo htmlspecialchars($selectedZone); ?>)</h3>
                    <div class="flex gap-2">
                        <a href="?zone=A1" class="px-3 py-1 text-xs rounded-lg border <?php echo $selectedZone === 'A1' ? 'bg-emerald-800 text-white font-bold' : 'bg-slate-50'; ?>">Kệ A1</a>
                        <a href="?zone=B1" class="px-3 py-1 text-xs rounded-lg border <?php echo $selectedZone === 'B1' ? 'bg-emerald-800 text-white font-bold' : 'bg-slate-50'; ?>">Kệ B1</a>
                        <a href="?zone=B2" class="px-3 py-1 text-xs rounded-lg border <?php echo $selectedZone === 'B2' ? 'bg-emerald-800 text-white font-bold' : 'bg-slate-50'; ?>">Kệ B2</a>
                    </div>
                </div>

                <table class="w-full text-left text-xs">
                    <thead>
                        <tr class="border-b text-slate-400 pb-2">
                            <th class="pb-2">TÊN SẢN PHẨM</th>
                            <th class="pb-2">MÃ SKU</th>
                            <th class="pb-2">TỒN KHO</th>
                            <th class="pb-2">VỊ TRÍ CHI TIẾT TRÊN KỆ</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y text-slate-700">
                        <?php if ($products && $products->num_rows > 0): ?>
                            <?php while ($p = $products->fetch_assoc()): ?>
                                <tr class="hover:bg-slate-50">
                                    <td class="py-3 font-bold text-slate-900"><?php echo htmlspecialchars($p['product_name']); ?></td>
                                    <td><span class="bg-slate-100 px-2 py-1 rounded text-slate-600"><?php echo htmlspecialchars($p['sku']); ?></span></td>
                                    <td class="font-bold text-emerald-700"><?php echo $p['stock'] . ' ' . $p['unit']; ?></td>
                                    <td><span class="text-blue-600 font-semibold flex items-center gap-1"><i data-lucide="map-pin" class="w-3.5 h-3.5"></i> <?php echo htmlspecialchars($p['shelf_location']); ?></span></td>
                                </tr>
                            <?php endwhile; ?>
                        <?php else: ?>
                            <tr>
                                <td colspan="4" class="py-4 text-center text-slate-400">Không có sản phẩm nào trong khu vực này.</td>
                            </tr>
                        <?php endif; ?>
                    </tbody>
                </table>
            </div>

        </main>
    </div>

    <script>lucide.createIcons();</script>
</body>
</html>