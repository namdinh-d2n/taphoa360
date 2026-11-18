"""Local invoice OCR creates a reviewable draft and never writes business data."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
import config
from .auth import require
from .common import fail
from .database import reading, rows
from .inventory import supplier_products
from . import invoice_ai

router = APIRouter(prefix='/api/v1/ai/invoices')


@router.get('/status')
def status(user=Depends(require('inventory'))):
    return invoice_ai.status()


@router.post('/preview')
def preview(image: UploadFile = File(...), supplier_id: int = Form(...),
            user=Depends(require('inventory'))):
    try:
        if image.content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
            fail('Chọn ảnh JPG, PNG hoặc WebP; chưa hỗ trợ PDF.', 415)
        content = image.file.read(config.AI_IMAGE_MAX_BYTES + 1)
        if len(content) > config.AI_IMAGE_MAX_BYTES:
            fail('Ảnh hóa đơn quá lớn (tối đa 8 MB)', 413)
        with reading() as conn:
            products = supplier_products(conn, supplier_id)
            suppliers = rows(conn, 'SELECT id,name FROM suppliers')
        results = invoice_ai.recognize_image(content)
        return invoice_ai.build_draft(results, products, suppliers, supplier_id)
    finally:
        image.file.close()
