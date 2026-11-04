@echo off
chcp 65001 > nul
title Tạp hóa 360 - Python Server
echo ============================================================
echo        KHỞI ĐỘNG HỆ THỐNG TẠP HÓA 360 (PYTHON FASTAPI)
echo ============================================================
echo Đang kiểm tra thư viện...
python -m pip install -r requirements.txt
echo Khởi động Server...
python app.py
pause
