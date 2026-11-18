"""Install optional local invoice OCR and its checksum-verified Latin model."""
import hashlib
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL_URL = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/latin_PP-OCRv5_rec_mobile.onnx'
MODEL_SHA256 = 'b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a'


def main():
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        raise SystemExit('Local invoice OCR requires Python 3.11 or 3.12.')
    subprocess.run([sys.executable, '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check',
                    '-r', str(ROOT / 'requirements-ai.txt')], check=True)
    target = ROOT / '.local' / 'models' / 'latin_PP-OCRv5_rec_mobile.onnx'
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != MODEL_SHA256:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            data = response.read(20 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise SystemExit('Model checksum mismatch. No model was installed.')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.download')
        temporary.write_bytes(data)
        temporary.replace(target)
    print('Local invoice AI is ready. Restart Tap hoa 360. No API key is required.')


if __name__ == '__main__':
    main()
