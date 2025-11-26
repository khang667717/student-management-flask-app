# Script cập nhật dữ liệu
from app import create_app
from models import db, Course

app = create_app()
with app.app_context():
    # Cập nhật tất cả schedule NULL thành chuỗi rỗng
    Course.query.filter(Course.schedule.is_(None)).update({Course.schedule: ''})
    db.session.commit()
    print("Đã cập nhật schedule NULL thành chuỗi rỗng")
