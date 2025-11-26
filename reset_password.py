import os
import sys
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

# Thêm thư mục hiện tại vào path
sys.path.append(os.path.dirname(__file__))

# Import từ models.py thay vì app.py
from models import db, User

# Tạo app instance với config từ config.py
app = Flask(__name__)
app.config.from_object('config.DevelopmentConfig')  # Sử dụng config từ config.py

# Khởi tạo db với app
db.init_app(app)

def reset_multiple_passwords():
    with app.app_context():
        try:
            print("🔄 Đang kết nối database...")
            
            # Danh sách user cần reset
            users_to_reset = [
                {'id': 7, 'name': 'Phạm Xuân Anh', 'new_password': '123456'}
                
            ]
            
            success_count = 0
            
            for user_info in users_to_reset:
                user_id = user_info['id']
                user_name = user_info['name']
                new_password = user_info['new_password']
                
                # Tìm user theo ID
                user = db.session.get(User, user_id)
                
                if user:
                    # Reset mật khẩu
                    user.set_password(new_password)
                    db.session.commit()
                    
                    print(f"✅ RESET MẬT KHẨU THÀNH CÔNG!")
                    print(f"👤 User: {user.full_name}")
                    print(f"📧 Email: {user.email}")
                    print(f"🔑 Mật khẩu mới: {new_password}")
                    print(f"👥 Role: {user.role.value}")
                    print("─" * 40)
                    
                    success_count += 1
                else:
                    print(f"❌ User ID {user_id} ({user_name}) không tồn tại")
                    print("─" * 40)
            
            print(f"🎯 Tổng kết: Đã reset thành công {success_count}/{len(users_to_reset)} user")
            return True
                
        except Exception as e:
            print(f"❌ Lỗi khi reset mật khẩu: {str(e)}")
            db.session.rollback()
            return False

# Chạy hàm reset
if __name__ == "__main__":
    reset_multiple_passwords()