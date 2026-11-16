"""Offline neural OCR plus conservative invoice parsing and catalogue matching.

All OCR content is plain untrusted data. No LLM, remote requests, SQL generation,
product creation or stock mutations run here.
"""
from difflib import SequenceMatcher
from io import BytesIO
import importlib.util
import logging
import math
import re
import threading
import unicodedata

import config
from .common import fail

_engine = None
_inference_lock = threading.Lock()
MAX_VALUE = 1_000_000_000_000


def normalize(value):
    value = unicodedata.normalize('NFD', str(value)).lower().replace('đ', 'd')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).split())


def status():
    installed = all(importlib.util.find_spec(name) for name in ['rapidocr_onnxruntime', 'PIL'])
    available = config.AI_INVOICE_ENABLED and installed and config.AI_INVOICE_MODEL_PATH.is_file()
    return {'available': bool(available), 'offline': True, 'max_image_bytes': config.AI_IMAGE_MAX_BYTES,
            'message': 'AI đọc hóa đơn cục bộ đã sẵn sàng.' if available else
            'AI đọc hóa đơn đang tắt.' if not config.AI_INVOICE_ENABLED else 'AI đọc hóa đơn chưa được cài đủ trên máy này.'}


def recognize_image(content):
    if not status()['available']:
        fail(status()['message'], 503)
    if not _inference_lock.acquire(blocking=False):
        fail('AI đang đọc một hóa đơn khác. Vui lòng thử lại sau.', 429)
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        try:
            image = Image.open(BytesIO(content))
            if image.format not in {'JPEG', 'PNG', 'WEBP'}:
                fail('Nội dung file phải là ảnh JPG, PNG hoặc WebP.', 415)
            if image.width * image.height > config.AI_IMAGE_MAX_PIXELS or min(image.size) < 40:
                fail('Ảnh cần ít nhất 40×40 và tối đa 16 triệu điểm ảnh. Hãy thu nhỏ hoặc chụp lại.', 422)
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1800, 1800))
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            fail('Không đọc được ảnh. Hãy chọn ảnh hóa đơn rõ nét khác.', 422)
        global _engine
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR(rec_model_path=str(config.AI_INVOICE_MODEL_PATH),
                               intra_op_num_threads=1, inter_op_num_threads=1,
                               rec_batch_num=1, cls_batch_num=1,
                               det_limit_type='max', det_limit_side_len=1280, max_side_len=1800)
        result, _ = _engine(image)
        return result or []
    except MemoryError:
        fail('Máy chưa đủ RAM trống để đọc ảnh này. Hãy đóng bớt ứng dụng và thử ảnh nhỏ hơn.', 503)
    except Exception as exc:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            raise
        logging.getLogger('taphoa').exception('Local invoice OCR failed')
        fail('AI chưa đọc được ảnh này. Hãy thử ảnh rõ nét hơn hoặc nhập thủ công.', 503)
    finally:
        _inference_lock.release()


def parse_integer(value, quantity=False):
    """Accept VND grouping/zero decimals; never round fractional quantities."""
    text = str(value).strip().replace(' ', '').replace('\u00a0', '')
    text = re.sub(r'(?i)(vnd|đ|₫)$', '', text)
    if re.fullmatch(r'\d+', text):
        result = int(text)
    elif re.fullmatch(r'\d{1,3}([.,])\d{3}(?:\1\d{3})*', text):
        result = int(re.sub(r'[.,]', '', text))
    elif re.fullmatch(r'\d+[.,]0{1,2}', text):
        result = int(re.split(r'[.,]', text)[0])
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+,0{1,2}', text) or re.fullmatch(r'\d{1,3}(?:,\d{3})+\.0{1,2}', text):
        result = int(re.sub(r'[.,]', '', re.sub(r'[.,]0{1,2}$', '', text)))
    else:
        return None
    return result if (1 if quantity else 0) <= result <= MAX_VALUE else None


def grouped_rows(results):
    cells = []
    for box, text, confidence in results[:1000]:
        text = str(text).strip()[:500]
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        score = float(confidence)
        if not text or not all(math.isfinite(n) for n in xs + ys + [score]):
            continue
        cells.append({'x': (min(xs) + max(xs)) / 2, 'y': (min(ys) + max(ys)) / 2,
                      'height': max(ys) - min(ys), 'text': text, 'confidence': score})
    groups = []
    for cell in sorted(cells, key=lambda c: (c['y'], c['x'])):
        if groups and abs(cell['y'] - groups[-1][0]['y']) <= max(cell['height'], groups[-1][0]['height']) * .55:
            groups[-1].append(cell)
        else:
            groups.append([cell])
    return [sorted(group, key=lambda c: c['x']) for group in groups]


HEADERS = {
    'quantity': {'sl', 'so luong', 'qty', 'quantity'},
    'cost_price': {'don gia', 'gia nhap', 'unit price', 'price'},
    'amount': {'thanh tien', 'amount', 'line total'},
    'unit': {'dvt', 'don vi', 'unit'},
    'name': {'ten hang', 'ten san pham', 'hang hoa', 'mat hang', 'san pham', 'description', 'item'},
}
SKIP = re.compile(r'^(tong\b|cong tien\b|thanh toan\b|tien hang\b|thue\b|vat\b|giam gia\b|total\b|subtotal\b|dia chi\b|dien thoai\b|hotline\b|mst\b|ngay\b|hoa don\b|phieu\b)')


def parse_lines(results):
    groups = grouped_rows(results)
    raw_text = '\n'.join('\t'.join(c['text'] for c in group) for group in groups)[:50000]
    headers, items, invoice_total = {}, [], None
    for group in groups:
        joined = ' '.join(c['text'] for c in group)
        normalized = normalize(joined)
        found = {key: cell['x'] for cell in group for key, words in HEADERS.items() if normalize(cell['text']) in words}
        if 'quantity' in found and ('cost_price' in found or 'amount' in found):
            headers = found
            continue
        if SKIP.match(normalized):
            if normalized.startswith(('tong ', 'total')) and not normalized.startswith('tong dai'):
                numbers = [parse_integer(c['text']) for c in group]
                invoice_total = next((n for n in reversed(numbers) if n is not None), invoice_total)
            continue
        values = {}
        if headers:
            for cell in group:
                column = min(headers, key=lambda key: abs(headers[key] - cell['x']))
                values[column] = (values.get(column, '') + ' ' + cell['text']).strip()
        # Fall back to distinct OCR cells: name / optional unit / quantity / price / amount.
        if not headers or not values.get('name'):
            chunks = [cell['text'] for cell in group]
            if len(chunks) == 1:
                chunks = chunks[0].split()
            if len(chunks) >= 4 and all(parse_integer(c) is not None for c in chunks[-3:]):
                values = {'name': ' '.join(chunks[:-3]), 'quantity': chunks[-3], 'cost_price': chunks[-2], 'amount': chunks[-1]}
            elif not headers:
                continue
        name = values.get('name', '').strip()
        if not re.search(r'[^\W\d_]', name, re.UNICODE) or not any(k in values for k in ['quantity', 'cost_price', 'amount']):
            continue
        # A paragraph or instruction has no numeric table cells and is not a product.
        qty = parse_integer(values.get('quantity', ''), quantity=True)
        cost, amount = parse_integer(values.get('cost_price', '')), parse_integer(values.get('amount', ''))
        if qty is None and cost is None and amount is None:
            continue
        warnings = []
        if qty is None: warnings.append('Cần kiểm tra số lượng nguyên.')
        if cost is None and qty and amount is not None and amount % qty == 0:
            cost = amount // qty
            warnings.append('Đơn giá được tính từ thành tiền / số lượng; cần kiểm tra.')
        if cost is None: warnings.append('Chưa đọc rõ đơn giá.')
        if qty and cost is not None and amount is not None and qty * cost != amount:
            warnings.append('Số lượng × đơn giá chưa khớp thành tiền trên ảnh.')
        confidence = min(cell['confidence'] for cell in group)
        if confidence < .85: warnings.append('Có chữ/số nhận dạng chưa rõ; đối chiếu ảnh gốc.')
        items.append({'name': name[:150], 'unit': values.get('unit', '')[:30], 'quantity': qty,
                      'cost_price': cost, 'amount': amount, 'warnings': warnings,
                      'ocr_confidence': round(confidence, 3)})
        if len(items) == 100: break
    return items, raw_text, invoice_total


def match_product(name, products):
    term = normalize(name)
    exact = [p for p in products if p['active'] and term in {
        normalize(p['product_name']), normalize(p['sku']), normalize(p.get('barcode') or ''), normalize(p.get('supplier_sku') or '')}]
    if len(exact) == 1:
        return exact[0]['id'], 'exact'
    candidates = sorted([(SequenceMatcher(None, term, normalize(p['product_name'])).ratio(), p)
                         for p in products if p['active']], key=lambda pair: pair[0], reverse=True)
    if candidates:
        score, product = candidates[0]
        same_numbers = re.findall(r'\d+', term) == re.findall(r'\d+', normalize(product['product_name']))
        if score >= .92 and same_numbers and (len(candidates) == 1 or score - candidates[1][0] >= .08):
            return product['id'], 'similar'
    return None, 'unmatched'


def build_draft(results, products, suppliers, supplier_id):
    items, raw_text, invoice_total = parse_lines(results)
    warnings = ['AI chỉ tạo bản nháp. Hãy đối chiếu tên hàng, đơn vị, số lượng và giá với ảnh trước khi ghi nhận.']
    for item in items:
        item['product_id'], item['match_kind'] = match_product(item['name'], products)
        matched = next((p for p in products if p['id'] == item['product_id']), None)
        if matched and item['unit'] and normalize(item['unit']) != normalize(matched['unit']):
            item['product_id'], item['match_kind'] = None, 'unit_mismatch'
            item['warnings'].append('Tên khớp nhưng đơn vị khác danh mục; cần chọn đúng sản phẩm và quy đổi số lượng.')
        if item['product_id'] is None:
            item['warnings'].append('Chưa khớp sản phẩm trong danh mục nhà cung cấp.')
        elif item['match_kind'] == 'similar':
            item['warnings'].append('Tên gần giống; cần xác nhận đúng sản phẩm/quy cách.')
    if not items:
        warnings.append('Chưa tách được dòng hàng. Thử ảnh có bảng tên hàng, số lượng, đơn giá rõ ràng hoặc nhập thủ công.')
    total = sum(item['quantity'] * item['cost_price'] for item in items if item['quantity'] and item['cost_price'] is not None)
    if invoice_total is not None and total != invoice_total:
        warnings.append('Tổng các dòng đọc được khác tổng hóa đơn; kiểm tra dòng bị thiếu, thuế, phí hoặc giảm giá.')
    header = normalize('\n'.join(raw_text.splitlines()[:6]))
    suggested = [s for s in suppliers if len(normalize(s['name'])) >= 5 and normalize(s['name']) in header]
    supplier_hint = suggested[0] if len(suggested) == 1 else None
    if supplier_hint and supplier_hint['id'] != supplier_id:
        warnings.append('Tên nhà cung cấp trên ảnh có thể khác nhà cung cấp đang chọn. Hãy kiểm tra trước khi nhập.')
    return {'offline': True, 'supplier_id': supplier_id, 'supplier_hint': supplier_hint, 'items': items,
            'raw_text': raw_text, 'invoice_total': invoice_total, 'draft_total': total, 'warnings': warnings}
