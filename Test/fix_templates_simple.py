from app import create_app, db

app = create_app()
with app.app_context():
    # Test các API components
    from models import StudentCourseCart, Course, CourseRegistration
    print("✅ StudentCourseCart:", StudentCourseCart.query.count())
    print("✅ Course:", Course.query.count()) 
    print("✅ CourseRegistration:", CourseRegistration.query.count())
    print("🎉 APIs ready to use!")