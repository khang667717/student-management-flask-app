from app import create_app
from models import db, Subject, Teacher

app = create_app()
with app.app_context():
    # Kiểm tra môn học
    subjects = Subject.query.all()
    print("Total subjects:", len(subjects))
    for subject in subjects:
        print(f"- {subject.subject_name} ({subject.department})")
    
    # Kiểm tra giáo viên
    teachers = Teacher.query.all()
    print("Total teachers:", len(teachers))
    for teacher in teachers:
        print(f"- {teacher.full_name} ({teacher.department})")
        print(f"  Department display: {teacher.department_display}")