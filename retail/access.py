"""Role workspaces and page permissions; account roles remain authoritative."""
ROLE_PORTALS = {
    'owner': {'name': 'Chủ tiệm', 'home': '/owner', 'icon': '◈', 'description': 'Quản lý toàn bộ cửa hàng, nhân viên, hàng hóa và doanh thu.'},
    'cashier': {'name': 'Thu ngân', 'home': '/cashier', 'icon': '▦', 'description': 'Bán hàng, thanh toán, khách hàng và chốt ca.'},
    'inventory': {'name': 'Kiểm kho', 'home': '/inventory', 'icon': '▣', 'description': 'Nhập hàng, kiểm kê, quản lý lô và chuẩn bị đơn giao.'},
    'shipper': {'name': 'Giao hàng', 'home': '/shipper', 'icon': '⇢', 'description': 'Xem đơn được phân công và xác nhận giao hàng.'},
}

PAGE_ROLES = {
    'owner_portal': (), 'cashier_portal': ('cashier',),
    'inventory_portal': ('inventory',), 'shipper_portal': ('shipper',),
    'dashboard': (), 'pos': ('cashier',), 'orders': ('cashier', 'inventory', 'shipper'),
    'inventory': ('inventory',), 'map': ('inventory', 'cashier'),
    'products': ('inventory', 'cashier'), 'customers': ('cashier',),
    'suppliers': ('inventory',), 'cash': ('cashier', 'inventory'),
    'hr': ('cashier', 'inventory', 'shipper'), 'reports': (),
    'suggestions': ('inventory',), 'settings': (),
}


def home_for(role):
    return ROLE_PORTALS[role]['home']


def may_open(role, page):
    return role == 'owner' or role in PAGE_ROLES.get(page, ())
