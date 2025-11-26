from app import create_app
from models import db, Student, Class

def create_test_relationships():
    app = create_app()
    with app.app_context():
        try:
            print("🚀 Bắt đầu tạo quan hệ nhiều-nhiều...")
            
            # Lấy sinh viên và lớp
            students = Student.query.all()
            classes = Class.query.all()
            
            print(f"📊 Tìm thấy {len(students)} sinh viên và {len(classes)} lớp")
            
            if not students or not classes:
                print("❌ Không đủ dữ liệu để tạo quan hệ")
                return
            
            # Tạo quan hệ nhiều-nhiều
            relations_created = 0
            
            # Mỗi sinh viên thuộc 1-2 lớp
            for i, student in enumerate(students):
                # Lấy danh sách lớp hiện tại của sinh viên
                current_classes = []
                try:
                    if hasattr(student.classes, 'all'):
                        current_classes = student.classes.all()
                    else:
                        current_classes = list(student.classes)
                except:
                    current_classes = []
                
                print(f"👤 {student.student_id} hiện có {len(current_classes)} lớp")
                
                if i < 2:  # 2 sinh viên đầu: thuộc cả 2 lớp
                    for class_obj in classes:
                        if class_obj not in current_classes:
                            student.classes.append(class_obj)
                            relations_created += 1
                            print(f"  ✅ Thêm: {class_obj.class_name}")
                else:  # Các sinh viên còn lại: thuộc 1 lớp
                    if classes and len(current_classes) == 0:  # Chỉ thêm nếu chưa có lớp
                        class_obj = classes[0]  # Lớp đầu tiên
                        student.classes.append(class_obj)
                        relations_created += 1
                        print(f"  ✅ Thêm: {class_obj.class_name}")
            
            db.session.commit()
            print(f"\n🎉 Đã tạo {relations_created} quan hệ nhiều-nhiều!")
            
            # Kiểm tra kết quả
            print("\n🔍 Kiểm tra kết quả cuối cùng:")
            for student in students:
                current_classes = []
                try:
                    if hasattr(student.classes, 'all'):
                        current_classes = student.classes.all()
                    else:
                        current_classes = list(student.classes)
                except:
                    current_classes = []
                    
                class_names = [cls.class_name for cls in current_classes]
                print(f"  {student.student_id}: {class_names}")
                
            # Kiểm tra trong database
            from sqlalchemy import text
            result = db.session.execute(text("SELECT COUNT(*) FROM student_class"))
            total_relations = result.scalar()
            print(f"\n📈 Tổng quan hệ trong database: {total_relations}")
                
        except Exception as e:
            db.session.rollback()
            print(f"💥 Lỗi: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    create_test_relationships()