import subprocess
import os
from dotenv import load_dotenv

load_dotenv()

# --- 1. Thông tin Kết nối Database ---
DB_HOST = '127.0.0.1' 
DB_PORT = '3306'      
DB_USER = 'root'
DB_PASSWORD = '12345678'
DB_NAME = 'student_management'

# Tạo thư mục xuất file nếu chưa tồn tại
OUTPUT_DIR = 'exported_db'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# *** DÒNG CODE ĐÃ ĐƯỢC CHỈNH SỬA ***
SQL_DUMP_FILE = os.path.join(OUTPUT_DIR, "student_managemen.sql")
# Thay vì dùng f"{DB_NAME}_dump.sql", ta dùng tên file cố định theo yêu cầu.

def create_mysql_dump():
    """Tạo SQL dump file bằng lệnh mysqldump, sử dụng kết nối TCP/IP."""
    try:
        command = [
            'mysqldump',
            f'--host={DB_HOST}',
            f'--port={DB_PORT}',
            f'--user={DB_USER}',
            f'--password={DB_PASSWORD}',
            '--single-transaction',
            DB_NAME
        ]
        
        # Chạy lệnh và chuyển hướng output ra file SQL
        print(f"Bắt đầu xuất database '{DB_NAME}'...")
        with open(SQL_DUMP_FILE, 'w', encoding='utf-8') as f:
            # `check=True` sẽ raise exception nếu mysqldump trả về mã lỗi
            result = subprocess.run(command, stdout=f, stderr=subprocess.PIPE, check=True)
            
        print(f"✅ Đã tạo SQL Dump thành công tại: {SQL_DUMP_FILE}")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Lỗi khi chạy mysqldump: Lệnh thất bại với mã lỗi {e.returncode}")
        print(f"Lỗi chi tiết: {e.stderr.decode()}")
        print("💡 Vui lòng kiểm tra: 1) MySQL Server đã khởi động. 2) User/Password chính xác.")
    except FileNotFoundError:
        print("❌ Lỗi: Không tìm thấy lệnh 'mysqldump'. Vui lòng cài đặt MySQL Client Tools và thêm vào PATH.")

create_mysql_dump()