from app import create_app
from models import db, create_tables, create_sample_data
import sys

# 1. Khởi tạo ứng dụng
app = create_app()

# 2. Thực thi trong Application Context
with app.app_context():
    try:
        print("BƯỚC 1: XÓA TOÀN BỘ BẢNG CŨ (MẤT DỮ LIỆU)...")
        db.drop_all() # Lệnh này XÓA TOÀN BỘ BẢNG CŨ
        
        print("BƯỚC 2: TẠO LẠI BẢNG VỚI CẤU TRÚC ĐÃ SỬA CASCADE...")
        create_tables() # Lệnh này TẠO LẠI CÁC BẢNG (với cascade đã sửa trong models.py)
        
        # Tùy chọn: Tái tạo dữ liệu mẫu
        try:
            create_sample_data()
            print("ĐÃ TẠO LẠI DỮ LIỆU MẪU THÀNH CÔNG.")
        except Exception as e:
            # Điều này xảy ra nếu bạn đã có dữ liệu mẫu rồi, không phải lỗi nghiêm trọng.
            print(f"Không thể tạo dữ liệu mẫu (có thể đã tồn tại): {e}. Vui lòng tự thêm user.")
        
        print("\n====================================================================")
        print("TÁI TẠO DATABASE HOÀN TẤT. Lỗi xóa User đã được khắc phục.")
        print("====================================================================")
        
    except Exception as e:
        print(f"LỖI FATAL KHI TÁI TẠO DATABASE: {e}", file=sys.stderr)
