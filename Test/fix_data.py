# Chạy trong Python shell để kiểm tra
from app import create_app, db
from models import Teacher, Course, Class, ClassCourse

app = create_app()
with app.app_context():
    teacher = Teacher.query.first()
    print(f"Teacher: {teacher.full_name if teacher else 'No teacher'}")
    
    courses = Course.query.filter_by(teacher_id=teacher.id if teacher else 0).all()
    print(f"Courses: {len(courses)}")
    
    for course in courses:
        print(f"Course: {course.course_code}, ClassCourses: {len(course.class_courses)}")
        for cc in course.class_courses:
            print(f"  - Class: {cc.class_.class_name if cc.class_ else 'No class'}")