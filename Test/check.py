from app import create_app
from models import db, Student, CourseRegistration

app = create_app()
with app.app_context():
    # Kiểm tra quan hệ
    registrations = CourseRegistration.query.options(
        db.joinedload(CourseRegistration.student).joinedload(Student.classes)
    ).limit(2).all()
    
    for reg in registrations:
        print(f"Registration {reg.id}: {reg.student.student_id}")
        print(f"Classes: {[cls.class_name for cls in reg.student.classes]}")
        print("---")