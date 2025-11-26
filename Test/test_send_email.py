# test_send_email.py
import os
from dotenv import load_dotenv
from flask_mail import Mail, Message
from flask import Flask

load_dotenv()

app = Flask(__name__)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT') or 587)
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

mail = Mail(app)

def send_test_email():
    try:
        with app.app_context():
            msg = Message(
                subject="🎉 TEST - Hệ thống Quản lý Học tập",
                recipients=[os.environ.get('MAIL_USERNAME')],  # Gửi cho chính bạn
                html="""
                <h2>✅ Email Test Thành Công!</h2>
                <p>Hệ thống Quản lý Học tập đã được cấu hình email thành công.</p>
                <p><strong>Thông báo điểm kém</strong> sẽ được gửi tự động khi có sinh viên điểm dưới 5.0.</p>
                <hr>
                <p><em>Email được gửi tự động từ hệ thống</em></p>
                """
            )
            mail.send(msg)
            print("✅ Email test đã được gửi thành công!")
            print("📧 Kiểm tra hộp thư đến của bạn")
            return True
    except Exception as e:
        print(f"❌ Lỗi gửi email: {e}")
        return False

if __name__ == "__main__":
    send_test_email()