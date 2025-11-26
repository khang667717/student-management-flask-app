from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import validates  # THÊM DÒNG NÀY

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import enum
import logging
import re  # THÊM CHO VALIDATION EMAIL


db = SQLAlchemy()
logger = logging.getLogger(__name__)

class UserRole(enum.Enum):
    ADMIN = 'admin'
    TEACHER = 'teacher'
    STUDENT = 'student'

#BẢNG TRUNG GIAN (Quan hệ Database)
teacher_subject = db.Table('teacher_subject',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teachers.id'), primary_key=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subjects.id'), primary_key=True),
    db.Column('assigned_at', db.DateTime, default=datetime.utcnow)
)

student_class = db.Table('student_class',
    db.Column('student_id', db.Integer, db.ForeignKey('students.id'), primary_key=True),
    db.Column('class_id', db.Integer, db.ForeignKey('classes.id'), primary_key=True),
    db.Column('joined_at', db.DateTime, default=datetime.utcnow),
    db.Column('is_active', db.Boolean, default=True)
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    student_profile = db.relationship('Student', backref='user', uselist=False, lazy=True, cascade='all, delete-orphan')
    teacher_profile = db.relationship('Teacher', backref='user', uselist=False, lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        return str(self.id)
    
    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN
    
    @property
    def is_teacher(self):
        return self.role == UserRole.TEACHER
    
    @property
    def is_student(self):
        return self.role == UserRole.STUDENT

class Student(db.Model):
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    student_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    course = db.Column(db.String(10), nullable=False)
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(10))
    enrollment_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(20), default='active')
    
    classes = db.relationship('Class', 
                            secondary=student_class,
                            backref=db.backref('class_students', lazy='select'),
                            lazy='select')
    

    @property
    def class_(self):
        """Property tương thích - trả về lớp đầu tiên (nếu có)"""
        class_list = self.classes.all() if hasattr(self.classes, 'all') else list(self.classes)
        return class_list[0] if class_list else None

    # Academic info
    gpa = db.Column(db.Float, default=0.0)
    total_credits = db.Column(db.Integer, default=0)
    completed_credits = db.Column(db.Integer, default=0)
    
    # Relationships
    scores = db.relationship('Score', backref='student', lazy=True)
    registrations = db.relationship('CourseRegistration', backref='student', lazy=True)
    attendances = db.relationship('Attendance', backref='student', lazy=True)

    

    def update_gpa(self):
        """Cập nhật GPA tự động dựa trên điểm số"""
        try:
            scores = Score.query.filter_by(student_id=self.id).all()
            total_credits = 0
            weighted_sum = 0.0
            
            for score in scores:
                if score.final_score and score.course and score.course.subject:
                    credits = score.course.subject.credits
                    total_credits += credits
                    weighted_sum += score.final_score * credits
            
            if total_credits > 0:
                self.gpa = round(weighted_sum / total_credits, 2)
                self.completed_credits = total_credits
            else:
                self.gpa = 0.0
                self.completed_credits = 0
                
            db.session.commit()
            return self.gpa
            
        except Exception as e:
            logger.error(f"Error updating GPA for student {self.id}: {str(e)}")
            return 0.0
        
    

class Teacher(db.Model):
    __tablename__ = 'teachers'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    teacher_code = db.Column(db.String(20), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(50))
    qualification = db.Column(db.String(100))
    expertise = db.Column(db.Text)
    join_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(20), default='active')
    
    # Relationships
    courses = db.relationship('Course', backref='teacher', lazy=True)
    classes = db.relationship('Class', backref='teacher', lazy=True, overlaps="managed_classes,head_teacher")
    managed_classes = db.relationship('Class', backref='head_teacher', lazy=True, 
                                        overlaps="classes,teacher")


    # ✅ QUAN HỆ MANY-TO-MANY ĐÃ SỬA
    assigned_subjects = db.relationship('Subject', 
                                      secondary=teacher_subject,
                                      backref=db.backref('assigned_teachers', lazy=True),
                                      lazy=True)

    @property
    def teaching_subjects(self):
        """Danh sách môn học đang dạy"""
        return self.assigned_subjects

    @property 
    def department_display(self):
        """Trả về tên hiển thị đầy đủ của department"""
        dept_map = {
            'cntt': 'Công nghệ thông tin',
            'csdl': 'Cơ sở dữ liệu',
            'nmhm': 'Nhập môn học máy',
            'ptdll': 'Phân tích dữ liệu lớn',
            'anh': 'Ngôn ngữ anh',
            'kt': 'Kế Toán',
            'qtkd': 'Quản trị kinh doanh', 
            'dl': 'Du lịch'
        }
        return dept_map.get(self.department, self.department)
    
    @property
    def full_name(self):
        return self.user.full_name if self.user else "N/A"

    @property
    def email(self):
        return self.user.email if self.user else "N/A"

    @property
    def avatar(self):
        return self.user.avatar if self.user else None
    
    @property
    def teaching_classes(self):
        """Lấy tất cả lớp mà giáo viên dạy"""
        classes = []
        for course in self.courses:
            for class_course in course.class_courses:
                if class_course.class_ not in classes:
                    classes.append(class_course.class_)
        return classes
    
    @property
    def subject_count(self):
        """Số lượng môn học được phân công"""
        return len(self.assigned_subjects)
    
    @property 
    def active_courses_count(self):
        """Số khóa học đang dạy"""
        return len([c for c in self.courses if c.status in ['active', 'upcoming']])
    
    @property
    def total_students(self):
        """Tổng số sinh viên đang dạy"""
        total = 0
        for course in self.courses:
            if course.status in ['active', 'upcoming']:
                total += course.approved_students
        return total
    
    def update_subject_count(self):
        """Cập nhật số lượng môn học (nếu cần cache)"""
        # Nếu muốn cache vào database thay vì tính toán mỗi lần
        self._subject_count = len(self.assigned_subjects)
        db.session.add(self)

class Class(db.Model):
    __tablename__ = 'classes'
    
    id = db.Column(db.Integer, primary_key=True)
    class_code = db.Column(db.String(20), unique=True, nullable=False)
    class_name = db.Column(db.String(100), nullable=False)
    course = db.Column(db.String(10), nullable=False)
    faculty = db.Column(db.String(100), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    max_students = db.Column(db.Integer, default=50)
    current_students = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    db.CheckConstraint('max_students >= current_students', name='check_capacity'),
    db.CheckConstraint('current_students >= 0', name='check_non_negative_students')

    
    # Relationships
    class_courses = db.relationship('ClassCourse', back_populates='class_', cascade='all, delete-orphan')

    # Property để lấy courses trực tiếp
    @property
    def courses(self):
        """Lấy danh sách khóa học của lớp"""
        return [cc.course for cc in self.class_courses]
    

    @property
    def students(self):
        """Property tương thích - trả về danh sách sinh viên"""
        # Sử dụng class_students từ backref
        if hasattr(self, 'class_students'):
            student_list = self.class_students.all() if hasattr(self.class_students, 'all') else list(self.class_students)
            return student_list
        return []
    
    @property
    def subject_count(self):
        """Số lượng môn học được phân công"""
        return len(self.assigned_subjects)
    
    @property
    def avg_gpa(self):
        """Tính GPA trung bình của lớp"""
        student_list = self.students
        if not student_list:
            return 0.0
        
        total_gpa = sum(student.gpa or 0 for student in student_list)
        return round(total_gpa / len(student_list), 2)

    
    @property
    def current_semester_courses(self):
        """Lấy khóa học của học kỳ hiện tại"""
        current_semester = "HK1-2024"  # Có thể lấy từ hệ thống
        return [cc.course for cc in self.class_courses if cc.semester == current_semester]
    
    @property
    def current_students_count(self):
        """Số lượng sinh viên hiện tại - ĐÃ SỬA"""
        return len(self.students)

    @property
    def completed_courses_count(self):
        """Số lượng khóa học đã hoàn thành (đã chấm điểm)"""
        count = 0
        for class_course in self.class_courses:
            course = class_course.course
            if course.status == 'completed':
            # Đếm số sinh viên đã có điểm
                scores_count = Score.query.filter_by(course_id=course.id).count()
                if scores_count > 0:
                   count += 1
        return count

    @property
    def current_courses(self):
       """Danh sách khóa học hiện tại của lớp"""
       return [cc.course for cc in self.class_courses if cc.course.status in ['active', 'upcoming']]
    
class Subject(db.Model):
    __tablename__ = 'subjects'
    
    id = db.Column(db.Integer, primary_key=True)
    subject_code = db.Column(db.String(20), unique=True, nullable=False)
    subject_name = db.Column(db.String(100), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # general, major, elective
    semester = db.Column(db.Integer, nullable=False)
    theory_hours = db.Column(db.Integer, default=30)
    practice_hours = db.Column(db.Integer, default=15)
    description = db.Column(db.Text)
    prerequisites = db.Column(db.Text)  # JSON string of prerequisite subject IDs
    
    
    # Relationships
    courses = db.relationship('Course', backref='subject', lazy=True)

    @property
    def teacher_count(self):
        """Số lượng giáo viên dạy môn này"""
        return len(self.teachers)  

    
    @property 
    def student_count(self):
        """Số lượng sinh viên đăng ký môn này"""
        total = 0
        for course in self.courses:
            total += course.registered_students
        return total

    @property
    def department_name(self):
        """Tên đầy đủ của department"""
        dept_map = {
            'cntt': 'Công nghệ thông tin',
            'csdl': 'Cơ sở dữ liệu', 
            'dstt': 'Đại số tuyến tính',
            'nmhm': 'Nhập môn học máy ',
            'anh': 'Tiếng Anh',
            'kt': 'Kế Toán',
            'qtkd': 'Quản trị kinh doanh',
            'ptdll': 'Phân tích dữ liệu lớn',
            'dl': 'Du lịch'
    
        }
        return dept_map.get(self.department, self.department)

    @property
    def icon(self):
        icons = {
        'cntt': 'laptop-code',     # Công nghệ thông tin
        'csdl': 'database',        # Cơ sở dữ liệu
        'dstt': 'square-root-variable',  # Đại số tuyến tính
        'nmhm': 'brain',           # Nhập môn học máy
        'anh': 'language'          # Tiếng Anh
        }
        return icons.get(self.department, 'book')


    @property
    def prerequisites_list(self):
        """Parse prerequisites JSON thành list"""
        import json
        if self.prerequisites:
            try:
                prereq_ids = json.loads(self.prerequisites)
                # Lấy tên môn học từ database
                subjects = Subject.query.filter(Subject.id.in_(prereq_ids)).all()
                return [s.subject_name for s in subjects]
            except:
                return []
        return []
    
    def update_teacher_count(self):
        """Cập nhật số lượng giáo viên dạy môn này"""
        self.teacher_count = len(self.assigned_teachers)
        db.session.add(self)
    
# ======== THÊM CLASSCOURSE Ở ĐÂY ========
class ClassCourse(db.Model):
    __tablename__ = 'class_courses'
    
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    semester = db.Column(db.String(20), nullable=False)  # Format: "HK1-2024"
    academic_year = db.Column(db.String(20), nullable=False)  # Format: "2024-2025"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    class_ = db.relationship('Class', back_populates='class_courses')
    course = db.relationship('Course', back_populates='class_courses')
    
    __table_args__ = (
        db.UniqueConstraint('class_id', 'course_id', 'semester', name='unique_class_course_semester'),
    )

    def __repr__(self):
        return f'<ClassCourse class_id:{self.class_id} course_id:{self.course_id}>'

class Course(db.Model):
    __tablename__ = 'courses'
    
    id = db.Column(db.Integer, primary_key=True)
    course_code = db.Column(db.String(20), unique=True, nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    year = db.Column(db.String(10), nullable=False)  # 2023-2024
    max_students = db.Column(db.Integer, default=50)
    current_students = db.Column(db.Integer, default=0)
    room = db.Column(db.String(50))
    schedule = db.Column(db.Text, default='')
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='upcoming')  # upcoming, active, completed, cancelled
    grading_components = db.Column(db.Text)  # JSON string of grading components
    description = db.Column(db.Text)  # THÊM DÒNG NÀY

    db.UniqueConstraint('course_code', 'semester', 'year', name='unique_course_semester'),
    db.CheckConstraint('max_students > 0', name='check_max_students_positive'),
    db.CheckConstraint('end_date IS NULL OR start_date IS NULL OR end_date >= start_date', 
                          name='check_dates_valid')

    
    # THÊM: Field để cache số lượng
    total_registrations_count = db.Column(db.Integer, default=0)
    approved_registrations_count = db.Column(db.Integer, default=0)
    
    # Relationships
    registrations = db.relationship('CourseRegistration', backref='course', lazy=True)
    scores = db.relationship('Score', backref='course', lazy=True)

    # THÊM quan hệ mới với ClassCourse
    class_courses = db.relationship('ClassCourse', back_populates='course', cascade='all, delete-orphan')

    def update_registration_counts(self):
        """Cập nhật số lượng đăng ký - HIỆU SUẤT CAO"""
        from sqlalchemy import func, case
    
        # CHỈ 1 QUERY thay vì 2 queries - ĐÃ SỬA LỖI INDENTATION
        result = db.session.query(
            func.count(CourseRegistration.id),
            func.count(case((CourseRegistration.status == 'approved', 1)))
        ).filter(
            CourseRegistration.course_id == self.id
        ).first()
    
        self.total_registrations_count = result[0] or 0
        self.approved_registrations_count = result[1] or 0
    
        db.session.add(self)  # Chỉ add, không commit

    def auto_register_class_students(self):
        """Tự động đăng ký sinh viên từ các lớp được gán vào khóa học"""
        try:
            registered_count = 0
            
            # Lấy tất cả lớp học có khóa học này
            for class_course in self.class_courses:
                class_obj = class_course.class_
                
                # Đăng ký tất cả sinh viên trong lớp
                for student in class_obj.students:
                    # Kiểm tra xem đã đăng ký chưa
                    existing_reg = CourseRegistration.query.filter_by(
                        student_id=student.id,
                        course_id=self.id
                    ).first()
                    
                    if not existing_reg:
                        # Tạo đăng ký mới với trạng thái "approved" (admin duyệt)
                        registration = CourseRegistration(
                            student_id=student.id,
                            course_id=self.id,
                            status='approved',  # ✅ ADMIN DUYỆT NGAY
                            registration_date=datetime.utcnow(),
                            notes=f'Tự động đăng ký từ lớp {class_obj.class_name}'
                        )
                        db.session.add(registration)
                        registered_count += 1
            
            # Cập nhật số lượng
            if registered_count > 0:
                self.current_students += registered_count
                self.registered_students = registered_count
                self.update_registration_counts()
                db.session.commit()
                
            return registered_count
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error auto-registering students: {str(e)}")
            return 0

    # THÊM: Phương thức gọi sau khi tạo khóa học
    @classmethod
    def create_course_with_auto_registration(cls, **kwargs):
        """Tạo khóa học và tự động đăng ký sinh viên"""
        course = cls(**kwargs)
        db.session.add(course)
        db.session.flush()  # Lấy ID
        
        # Tự động đăng ký sinh viên
        course.auto_register_class_students()
        
        db.session.commit()
        return course

    @classmethod
    def batch_update_registration_counts(cls):
        """Batch update cho tất cả courses - TỐI ƯU KHI SYNC SYSTEM"""
        from sqlalchemy import func, case
    
        # 1 QUERY cho tất cả counts - ĐÃ SỬA LỖI INDENTATION
        count_query = db.session.query(
            CourseRegistration.course_id,
            func.count(CourseRegistration.id).label('total'),
            func.count(case((CourseRegistration.status == 'approved', 1))).label('approved')
        ).group_by(CourseRegistration.course_id)
    
        count_data = {row.course_id: row for row in count_query}
    
        # Update tất cả courses
        courses = cls.query.all()
        for course in courses:
            if course.id in count_data:
                data = count_data[course.id]
                course.total_registrations_count = data.total
                course.approved_registrations_count = data.approved
            else:
                course.total_registrations_count = 0
                course.approved_registrations_count = 0
        
            db.session.add(course)
    
        db.session.commit()

    @classmethod
    def get_teacher_courses(cls, teacher_id):
        """Lấy danh sách khóa học của giáo viên"""
        return cls.query.filter_by(teacher_id=teacher_id).all()

    @classmethod
    def get_course_with_students(cls, course_id, teacher_id=None):
        """Lấy thông tin khóa học kèm danh sách sinh viên"""
        query = cls.query.filter_by(id=course_id)
    
        if teacher_id:
            query = query.filter_by(teacher_id=teacher_id)
    
        course = query.first()
        if not course:
            return None
    
    # Lấy danh sách sinh viên đã đăng ký
        registrations = CourseRegistration.query.filter_by(
        course_id=course_id, 
        status='approved'
    ).all()
    
        students_data = []
        for reg in registrations:
            student = reg.student
            score = Score.query.filter_by(
            student_id=student.id, 
            course_id=course_id
        ).first()
        
            students_data.append({
            'id': student.id,
            'student_id': student.student_id,
            'full_name': student.user.full_name,
            'email': student.user.email,
            'class_name': student.classes[0].class_name if student.classes else 'N/A',
            'process_score': score.process_score if score else None,
            'exam_score': score.exam_score if score else None,
            'final_score': score.final_score if score else None,
            'grade': score.grade if score else None,
            'status': score.status if score else 'draft',
            'notes': score.notes if score else ''
        })
    
        return {
        'course': course,
        'students': students_data
    }

    @classmethod
    def get_available_courses_for_student(cls, student_id, semester, year):
        """Lấy danh sách khóa học sinh viên có thể đăng ký"""
        from sqlalchemy import and_, or_
        
        student = Student.query.get(student_id)
        if not student:
            return []
        
        # Lấy lớp của sinh viên
        student_classes = student.classes
        if not student_classes:
            return []

        class_ids = [class_obj.id for class_obj in student_classes]

        # Lấy các khóa học đã đăng ký (tránh trùng lặp)
        registered_course_ids = [reg.course_id for reg in student.registrations 
                               if reg.status in ['pending', 'approved']]
        
        # Lấy các khóa học có thể đăng ký
        available_courses = cls.query.filter(
            cls.semester == semester,
            cls.year == year,
            cls.status.in_(['upcoming', 'active']),
            cls.id.notin_(registered_course_ids),
            cls.current_students < cls.max_students
        ).all()
        
        return available_courses

    @staticmethod
    def check_schedule_conflicts(student_id, course_ids):
        """Kiểm tra xung đột lịch học"""
        conflicts = []
        
        # Lấy lịch học của các khóa học muốn đăng ký
        target_courses = Course.query.filter(Course.id.in_(course_ids)).all()
        
        # Lấy lịch học các khóa học đã đăng ký
        registered_registrations = CourseRegistration.query.filter(
            CourseRegistration.student_id == student_id,
            CourseRegistration.status.in_(['pending', 'approved'])
        ).all()
        
        registered_courses = [reg.course for reg in registered_registrations if reg.course]
        
        # Kiểm tra xung đột
        for target_course in target_courses:
            for registered_course in registered_courses:
                if Course.has_schedule_conflict(target_course.schedule, registered_course.schedule):
                    conflicts.append({
                        'course1': target_course.course_code,
                        'course2': registered_course.course_code,
                        'schedule1': target_course.schedule,
                        'schedule2': registered_course.schedule
                    })
        
        return conflicts

    @staticmethod
    def has_schedule_conflict(schedule1, schedule2):
        """Kiểm tra xung đột giữa 2 lịch học"""
        # Logic đơn giản: nếu cùng ngày và cùng khung giờ -> xung đột
        if schedule1 and schedule2:
            days1 = Course.extract_days(schedule1)
            days2 = Course.extract_days(schedule2)
            times1 = Course.extract_times(schedule1)
            times2 = Course.extract_times(schedule2)
            
            # Kiểm tra xem có ngày trùng nhau không
            common_days = set(days1) & set(days2)
            if common_days:
                # Kiểm tra xem có khung giờ trùng nhau không
                for time1 in times1:
                    for time2 in times2:
                        if Course.time_overlap(time1, time2):
                            return True
        return False

    @staticmethod
    def extract_days(schedule):
        """Trích xuất các ngày học từ schedule string"""
        days = []
        schedule_lower = schedule.lower()
        if 'thứ 2' in schedule_lower or 'thứ hai' in schedule_lower: 
            days.append('mon')
        if 'thứ 3' in schedule_lower or 'thứ ba' in schedule_lower: 
            days.append('tue')
        if 'thứ 4' in schedule_lower or 'thứ tư' in schedule_lower: 
            days.append('wed')
        if 'thứ 5' in schedule_lower or 'thứ năm' in schedule_lower: 
            days.append('thu')
        if 'thứ 6' in schedule_lower or 'thứ sáu' in schedule_lower: 
            days.append('fri')
        if 'thứ 7' in schedule_lower or 'thứ bảy' in schedule_lower: 
            days.append('sat')
        return days

    @staticmethod
    def extract_times(schedule):
        """Trích xuất khung giờ từ schedule string"""
        times = []
        sessions = schedule.split(',')
        for session in sessions:
            if 'tiết' in session.lower():
                # Trích xuất tiết học - ví dụ: "Thứ 2 - Tiết 1-3"
                import re
                # Tìm pattern "Tiết X-Y" hoặc "Tiết X"
                match = re.search(r'tiết\s*(\d+)(?:\s*-\s*(\d+))?', session.lower())
                if match:
                    start_session = int(match.group(1))
                    end_session = int(match.group(2)) if match.group(2) else start_session
                    times.append((start_session, end_session))
        return times

    @staticmethod
    def time_overlap(time1, time2):
        """Kiểm tra 2 khung giờ có trùng nhau không"""
        start1, end1 = time1
        start2, end2 = time2
        
        # Kiểm tra overlap: (start1 <= end2) and (start2 <= end1)
        return max(start1, start2) < min(end1, end2)


    @property
    def teacher_name(self):
        """Tên giáo viên - Property mới"""
        if self.teacher and self.teacher.user:
            return self.teacher.user.full_name
        return "Chưa phân công"
    
    @property
    def classes(self):
        """Lấy danh sách lớp học có khóa học này"""
        return [cc.class_ for cc in self.class_courses]
    
    @property
    def registered_students(self):
        """Số sinh viên đã đăng ký (tất cả trạng thái) - ĐỒNG BỘ"""
        return self.total_registrations_count
    
    @property
    def approved_students(self):
        """Số sinh viên đã được duyệt - ĐỒNG BỘ"""
        return self.approved_registrations_count
    
    @property
    def registration_progress(self):
        """Tiến độ đăng ký (%)"""
        if self.max_students == 0:
            return 0
        # SỬA: Sử dụng approved_students thay vì registered_students
        return round((self.approved_students / self.max_students) * 100, 1)
    
    @property
    def subject_name(self):
        """Tên môn học từ Subject"""
        return self.subject.subject_name if self.subject else "N/A"
    
    @property
    def icon(self):
        """Icon từ Subject"""
        return self.subject.icon if self.subject else 'book'
    
    @property
    def available_slots(self):
        """Số chỗ trống có sẵn"""
        return self.max_students - self.current_students
    
    @property
    def has_conflict(self):
        """Kiểm tra xung đột lịch học (tạm thời trả về False)"""
        # TODO: Implement logic kiểm tra xung đột lịch học thực tế
        return False
    
    @property
    def is_selected(self):
        """Kiểm tra môn đã được chọn chưa (tạm thời trả về False)"""
        # TODO: Implement logic kiểm tra sinh viên đã chọn môn này chưa
        return False
    
    @property
    def recommended_semester(self):
        """Học kỳ khuyến nghị - lấy từ subject"""
        return self.subject.semester if self.subject else self.semester
    
    @property
    def course_name(self):
        """Tên môn học - alias cho subject_name để tương thích template"""
        return self.subject_name
    
    
    
    @property
    def prerequisites(self):
        """Điều kiện tiên quyết - lấy từ subject"""
        return self.subject.prerequisites_list if self.subject else []
    
    @property
    def type(self):
        """Loại môn học - lấy từ subject"""
        return self.subject.type if self.subject else "major"
    
    @property
    def credits(self):
        """Số tín chỉ - lấy từ subject"""
        return self.subject.credits if self.subject else 3
    
    @property
    def registered_students_count(self):
        """Số sinh viên đã đăng ký - alias cho registered_students"""
        return self.registered_students
    
    @validates('teacher_id', 'subject_id')
    def validate_teacher_subject(self, key, value):
        """Validate giáo viên có được phân công môn học này không"""
    # CHỈ validate khi đang trong session và có thay đổi thực sự
        if (key == 'teacher_id' and value and 
            hasattr(self, 'subject_id') and self.subject_id and
            db.session.is_modified(self, include_collections=False)):
        
            teacher = Teacher.query.get(value)
            subject = Subject.query.get(self.subject_id)
        
            if teacher and subject and subject not in teacher.assigned_subjects:
            # TỰ ĐỘNG PHÂN CÔNG THAY VÌ BÁO LỖI
                teacher.assigned_subjects.append(subject)
                db.session.add(teacher)
                logger.info(f"Auto-assigned subject {subject.subject_name} to teacher {teacher.full_name}")
    
        return value

    @validates('semester', 'year')
    def validate_semester_year(self, key, value):
        """Validate học kỳ và năm học"""
        if key == 'semester' and value not in [1, 2, 3]:
            raise ValueError("Học kỳ phải là 1, 2 hoặc 3")
        return value
    
def sync_complete_system():
    """Đồng bộ toàn bộ hệ thống - HIỆU SUẤT CAO"""
    try:
        # 1. Đồng bộ số lượng đăng ký khóa học
        Course.batch_update_registration_counts()
        
        # 2. Đồng bộ GPA cho tất cả students
        students = Student.query.all()
        for student in students:
            student.update_gpa()
            
        # 3. Đồng bộ số lượng môn học của giáo viên
        teachers = Teacher.query.all()
        for teacher in teachers:
            teacher.update_subject_count()
            
        # 4. Đồng bộ số lượng sinh viên trong lớp
        classes = Class.query.all()
        for class_obj in classes:
            actual_count = Student.query.filter_by(class_id=class_obj.id).count()
            if class_obj.current_students != actual_count:
                class_obj.current_students = actual_count
                db.session.add(class_obj)
        
        # 5. Đồng bộ số lượng giáo viên dạy môn học
        subjects = Subject.query.all()
        for subject in subjects:
            subject.update_teacher_count()
        
        db.session.commit()
        logger.info("Complete system synchronization successful")
        return True
        
    except Exception as e:
        logger.error(f"Error in complete system sync: {str(e)}")
        db.session.rollback()
        return False

class CourseRegistration(db.Model):
    __tablename__ = 'course_registrations'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='approved')  # pending, approved, rejected, cancelled
    notes = db.Column(db.Text)
    
    # Unique constraint
    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', name='unique_student_course'),)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Tự động cập nhật count khi tạo mới
        self._update_course_counts()

    def save(self):
        """Lưu và cập nhật counts"""
        db.session.add(self)
        db.session.flush()
        self._update_course_counts()
        db.session.commit()
    
    def get_current_score(self):
        """Lấy điểm số hiện tại của sinh viên trong khóa học"""
        score = Score.query.filter_by(
            student_id=self.student_id,
            course_id=self.course_id
        ).first()
        return score.final_score if score else None
    
    def get_score_object(self):
        """Lấy đối tượng Score nếu có"""
        return Score.query.filter_by(
            student_id=self.student_id,
            course_id=self.course_id
        ).first()

    
    def _update_course_counts(self):
        """Cập nhật số lượng đăng ký cho course"""
        if self.course:
            self.course.update_registration_counts()

class Score(db.Model):
    __tablename__ = 'scores'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    process_score = db.Column(db.Float)
    exam_score = db.Column(db.Float)
    final_score = db.Column(db.Float)
    grade = db.Column(db.String(2))  # A, B+, B, C+, C, D+, D, F
    status = db.Column(db.String(20), default='draft')  # draft, published
    components = db.Column(db.Text)  # JSON string of component scores
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', name='unique_student_course_score'),)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Tính toán điểm cuối cùng ngay khi khởi tạo
        self._calculate_final_score()

    def save(self):
        """Lưu điểm và cập nhật GPA"""
        db.session.add(self)
        db.session.flush()
        
        # Cập nhật GPA cho student
        if self.student:
            self.student.update_gpa()
            
        db.session.commit()

    def _calculate_final_score(self):
        """Tính điểm cuối cùng tự động - ĐỒNG BỘ"""
        if self.process_score is not None and self.exam_score is not None:
            # Sử dụng công thức chuẩn: 40% quá trình + 60% thi
            self.final_score = round((self.process_score * 0.4) + (self.exam_score * 0.6), 2)
            self.grade = self._calculate_grade(self.final_score)
            self.status = 'published'

    def _calculate_grade(self, score):
        """Tính grade từ điểm số - ĐỒNG BỘ với app.py"""
        if score >= 8.5: return 'A'
        elif score >= 8.0: return 'B+'
        elif score >= 7.0: return 'B'
        elif score >= 6.5: return 'C+'
        elif score >= 5.5: return 'C'
        elif score >= 5.0: return 'D+'
        elif score >= 4.0: return 'D'
        else: return 'F'

    @classmethod
    def batch_update_scores(cls, course_id, scores_data):
        """Cập nhật hàng loạt điểm số"""
        try:
            updated_count = 0
        
            for score_data in scores_data:
                student_id = score_data.get('student_id')
                process_score = score_data.get('process_score')
                exam_score = score_data.get('exam_score')
                notes = score_data.get('notes', '')
            
            # Tìm hoặc tạo bản ghi điểm
                score = cls.query.filter_by(
                student_id=student_id,
                course_id=course_id
            ).first()
            
                if not score:
                    score = cls(
                    student_id=student_id,
                    course_id=course_id,
                    process_score=process_score,
                    exam_score=exam_score,
                    notes=notes
                )
                    db.session.add(score)
                else:
                    score.process_score = process_score
                    score.exam_score = exam_score
                    score.notes = notes
            
            # Tính điểm tổng nếu có đủ điểm
                if process_score is not None and exam_score is not None:
                    score.final_score = round((process_score * 0.4) + (exam_score * 0.6), 2)
                    score.grade = score._calculate_grade(score.final_score)
                    score.status = 'published'
            
                updated_count += 1
        
            db.session.commit()
            return {'success': True, 'updated_count': updated_count}
        
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

# THÊM: Hàm đồng bộ toàn hệ thống
def sync_system_data():
    """Đồng bộ tất cả dữ liệu hệ thống - HIỆU SUẤT CAO"""
    try:
        # SỬA: Sử dụng batch update thay vì individual
        Course.batch_update_registration_counts()
        
        # Đồng bộ GPA cho tất cả students
        students = Student.query.all()
        for student in students:
            student.update_gpa()

        db.session.commit()
        logger.info("System data synchronized successfully")
        return True
    except Exception as e:
        logger.error(f"Error syncing system data: {str(e)}")
        db.session.rollback()
        return False
    
class Attendance(db.Model):
    __tablename__ = 'attendances'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    session = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.
    status = db.Column(db.String(20), nullable=False)  # present, absent, late, excused
    notes = db.Column(db.Text)
    
    # Unique constraint
    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', 'date', 'session', name='unique_attendance'),)

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # academic, system, deadline, etc.
    priority = db.Column(db.String(20), default='normal')  # low, normal, high, urgent
    is_read = db.Column(db.Boolean, default=False)
    action_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('notifications', lazy=True))

class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('logs', lazy=True))

def auto_register_students_to_class_courses(class_id, course_id, semester):
    """
    CHỈ tạo ClassCourse (quan hệ lớp-khóa học) 
    KHÔNG tự động đăng ký sinh viên
    """
    class_obj = Class.query.get(class_id)
    course = Course.query.get(course_id)
    
    if not class_obj or not course:
        return 0
    
    # Kiểm tra xem ClassCourse đã tồn tại chưa
    existing_class_course = ClassCourse.query.filter_by(
        class_id=class_id,
        course_id=course_id,
        semester=semester
    ).first()
    
    if existing_class_course:
        return 0  # Đã tồn tại
    
    # CHỈ tạo ClassCourse - quan hệ lớp có khóa học này
    class_course = ClassCourse(
        class_id=class_id,
        course_id=course_id,
        semester=semester,
        academic_year=semester.split('-')[1]  # Tự động extract year từ semester
    )
    db.session.add(class_course)
    
    db.session.commit()
    
    # 🚨 QUAN TRỮNG: KHÔNG auto-register sinh viên
    # Để sinh viên tự đăng ký qua student_course_register
    
    return 1  # Chỉ tạo 1 ClassCourse

def get_available_courses_for_class(class_id, semester):
    """
    Lấy danh sách khóa học có thể gán cho lớp
    """
    # Lấy các khóa học đã được gán
    assigned_course_ids = [cc.course_id for cc in ClassCourse.query.filter_by(
        class_id=class_id, 
        semester=semester
    ).all()]
    
    # Lấy các khóa học chưa được gán
    available_courses = Course.query.filter(
        ~Course.id.in_(assigned_course_ids) if assigned_course_ids else True
    ).all()
    
    return available_courses

# THÊM VÀO CUỐI models.py, TRƯỚC các hàm create_tables, create_sample_data

class StudentSkill(db.Model):
    __tablename__ = 'student_skills'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    skill_name = db.Column(db.String(100), nullable=False)
    proficiency_level = db.Column(db.Integer, default=0)  # 0-100
    category = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('Student', backref=db.backref('skills', lazy=True))

class StudentCertificate(db.Model):
    __tablename__ = 'student_certificates'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    certificate_name = db.Column(db.String(200), nullable=False)
    organization = db.Column(db.String(200))
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    certificate_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('Student', backref=db.backref('certificates', lazy=True))

# THÊM VÀO models.py - sau class Course

class RegistrationPeriod(db.Model):
    """Thời gian đăng ký học phần"""
    __tablename__ = 'registration_periods'
    
    id = db.Column(db.Integer, primary_key=True)
    semester = db.Column(db.Integer, nullable=False)
    year = db.Column(db.String(10), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    max_credits = db.Column(db.Integer, default=24)
    status = db.Column(db.String(20), default='upcoming')  # upcoming, active, ended
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    # registrations = db.relationship('CourseRegistration', lazy=True,foreign_keys='CourseRegistration.registration_period_id')  

class StudentCourseCart(db.Model):
    """Giỏ hàng đăng ký tạm thời của sinh viên"""
    __tablename__ = 'student_course_carts'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    student = db.relationship('Student', backref=db.backref('course_cart', lazy=True))
    course = db.relationship('Course', backref=db.backref('in_carts', lazy=True))
    
    __table_args__ = (
        db.UniqueConstraint('student_id', 'course_id', 'registration_period_id', 
                          name='unique_student_course_period'),
    )

def check_prerequisites(student_id, course_id):
    """Kiểm tra điều kiện tiên quyết"""
    course = Course.query.get(course_id)
    if not course or not course.subject or not course.subject.prerequisites:
        return True, []
    
    # Lấy danh sách môn học đã hoàn thành
    completed_scores = Score.query.filter_by(
        student_id=student_id,
        status='published'
    ).filter(Score.final_score >= 5.0).all()
    
    completed_subject_ids = [score.course.subject_id for score in completed_scores if score.course]
    
    # Kiểm tra prerequisites
    import json
    try:
        required_prereq_ids = json.loads(course.subject.prerequisites)
        missing_prereqs = []
        
        for prereq_id in required_prereq_ids:
            prereq_subject = Subject.query.get(prereq_id)
            if prereq_subject and prereq_id not in completed_subject_ids:
                missing_prereqs.append(prereq_subject.subject_name)
        
        return len(missing_prereqs) == 0, missing_prereqs
        
    except:
        return True, []

# Create all tables
def create_tables():
    db.create_all()

# Sample data for testing
def create_sample_data():
    # Create admin user
    admin_user = User(
        username='admin',
        email='admin@school.edu.vn',
        full_name='System Administrator',
        role=UserRole.ADMIN
    )
    admin_user.set_password('admin123')
    
    # Create teacher user
    teacher_user = User(
        username='teacher1',
        email='teacher1@school.edu.vn',
        full_name='Nguyễn Văn A',
        role=UserRole.TEACHER
    )
    teacher_user.set_password('teacher123')
    
    # Create student user
    student_user = User(
        username='student1',
        email='student1@school.edu.vn',
        full_name='Trần Thị B',
        role=UserRole.STUDENT
    )
    student_user.set_password('student123')
    
    db.session.add_all([admin_user, teacher_user, student_user])
    db.session.commit()
    
    # Create teacher profile
    teacher = Teacher(
        user_id=teacher_user.id,
        teacher_code='GV001',
        department='cntt',
        position='Giảng viên'
    )
    
    # Create student profile
    student = Student(
        user_id=student_user.id,
        student_id='SV001',
        course='K2023',
        class_id=None
    )
    
    db.session.add_all([teacher, student])
    db.session.commit()

    subjects = [
    # Công nghệ thông tin (cntt)
        Subject(
        subject_code='CS101',
        subject_name='Lập trình Python',
        credits=3,
        department='cntt',
        type='major',
        semester=1
        ),
        Subject(
        subject_code='CS102',
        subject_name='Cơ sở dữ liệu',
        credits=3,
        department='cntt',
        type='major',
        semester=1
        ),
        Subject(
        subject_code='CS103',
        subject_name='Cấu trúc dữ liệu và giải thuật',
        credits=4,
        department='cntt',
        type='major',
        semester=2
    ),
        Subject(
        subject_code='CS104',
        subject_name='Lập trình hướng đối tượng',
        credits=3,
        department='cntt',
        type='major',
        semester=2
    ),
        Subject(
        subject_code='CS105',
        subject_name='Mạng máy tính',
        credits=3,
        department='cntt',
        type='major',
        semester=3
    ),
        Subject(
        subject_code='CS106',
        subject_name='Hệ điều hành',
        credits=3,
        department='cntt',
        type='major',
        semester=3
    ),
        Subject(
        subject_code='CS107',
        subject_name='Phát triển ứng dụng web',
        credits=3,
        department='cntt',
        type='major',
        semester=4
    ),
    
    # Cơ sở dữ liệu (csdl)
        Subject(
        subject_code='DB101',
        subject_name='Nhập môn cơ sở dữ liệu',
        credits=3,
        department='csdl',
        type='major',
        semester=1
    ),
        Subject(
        subject_code='DB102',
        subject_name='Thiết kế cơ sở dữ liệu',
        credits=3,
        department='csdl',
        type='major',
        semester=2
    ),
        Subject(
        subject_code='DB103',
        subject_name='Hệ quản trị CSDL',
        credits=3,
        department='csdl',
        type='major',
        semester=3
    ),
    
    # Nhập môn học máy (nmhm)
        Subject(
        subject_code='AI101',
        subject_name='Nhập môn trí tuệ nhân tạo',
        credits=3,
        department='nmhm',
        type='major',
        semester=3
    ),
        Subject(
        subject_code='AI102',
        subject_name='Học máy cơ bản',
        credits=3,
        department='nmhm',
        type='major',
        semester=4
    ),
        Subject(
        subject_code='AI103',
        subject_name='Xử lý ngôn ngữ tự nhiên',
        credits=3,
        department='nmhm',
        type='major',
        semester=5
    ),
    
    # Phân tích dữ liệu lớn (ptdll)
        Subject(
        subject_code='BD101',
        subject_name='Phân tích dữ liệu lớn',
        credits=3,
        department='ptdll',
        type='major',
        semester=4
    ),
        Subject(
        subject_code='BD102',
        subject_name='Hadoop và Spark',
        credits=3,
        department='ptdll',
        type='major',
        semester=5
    ),
        Subject(
        subject_code='BD103',
        subject_name='Kho dữ liệu và OLAP',
        credits=3,
        department='ptdll',
        type='major',
        semester=5
    ),
    
    # Ngôn ngữ Anh (nn)
        Subject(
        subject_code='ENG101',
        subject_name='Tiếng Anh cơ bản',
        credits=2,
        department='nn',
        type='general',
        semester=1
    ),
        Subject(
        subject_code='ENG102',
        subject_name='Tiếng Anh giao tiếp',
        credits=2,
        department='nn',
        type='general',
        semester=2
    ),
        Subject(
        subject_code='ENG103',
        subject_name='Tiếng Anh chuyên ngành CNTT',
        credits=2,
        department='nn',
        type='general',
        semester=3
    ),
    
    # Kế Toán (kt)
        Subject(
        subject_code='ACC101',
        subject_name='Nguyên lý kế toán',
        credits=3,
        department='kt',
        type='major',
        semester=1
    ),
        Subject(
        subject_code='ACC102',
        subject_name='Kế toán tài chính',
        credits=3,
        department='kt',
        type='major',
        semester=2
    ),
        Subject(
        subject_code='ACC103',
        subject_name='Kế toán quản trị',
        credits=3,
        department='kt',
        type='major',
        semester=3
    ),
    
    # Quản trị kinh doanh (qtkd)
        Subject(
        subject_code='BUS101',
        subject_name='Nguyên lý quản trị',
        credits=3,
        department='qtkd',
        type='major',
        semester=1
    ),
        Subject(
        subject_code='BUS102',
        subject_name='Quản trị marketing',
        credits=3,
        department='qtkd',
        type='major',
        semester=2
    ),
        Subject(
        subject_code='BUS103',
        subject_name='Quản trị nhân sự',
        credits=3,
        department='qtkd',
        type='major',
        semester=3
    ),
    
    # Du lịch (dl)
        Subject(
        subject_code='TOU101',
        subject_name='Nhập môn du lịch',
        credits=3,
        department='dl',
        type='major',
        semester=1
    ),
        Subject(
        subject_code='TOU102',
        subject_name='Quản trị lữ hành',
        credits=3,
        department='dl',
        type='major',
        semester=2
    ),
        Subject(
        subject_code='TOU103',
        subject_name='Hướng dẫn du lịch',
        credits=3,
        department='dl',
        type='major',
        semester=3
    ),
    
] 
    db.session.add_all(subjects)
    db.session.commit()

    # ======== THÊM CODE MẪU CLASSCOURSE Ở ĐÂY ========
    
    # Tạo lớp học mẫu
    sample_class = Class(
        class_code='CNTT-K2024A',
        class_name='Lớp Công nghệ Thông tin K2024A',
        course='K2024',
        faculty='cntt',
        teacher_id=teacher.id,
        max_students=50,
        current_students=1,
        description='Lớp Công nghệ Thông tin khóa 2024'
    )
    db.session.add(sample_class)
    db.session.commit()
    
    # Cập nhật student với class_id
    student.class_id = sample_class.id
    db.session.commit()
    
    # Tạo khóa học mẫu
    sample_course = Course(
        course_code='CS101-HK1-2024',
        subject_id=1,  # Lập trình Python - lấy ID từ subject đầu tiên
        teacher_id=teacher.id,
        semester=1,
        year='2024-2025',
        max_students=50,
        current_students=0,
        status='upcoming'
    )
    db.session.add(sample_course)
    db.session.commit()
    
    # Tạo quan hệ lớp - khóa học
    class_course = ClassCourse(
        class_id=sample_class.id,
        course_id=sample_course.id,
        semester='HK1-2024',
        academic_year='2024-2025'
    )
    db.session.add(class_course)
    db.session.commit()
    
    # Tự động đăng ký sinh viên vào khóa học
    auto_register_students_to_class_courses(sample_class.id, sample_course.id, 'HK1-2024')

# THÊM VÀO CUỐI models.py
class SystemSync:
    """Class chứa các phương thức đồng bộ hệ thống"""
    
    @staticmethod
    def update_all_counts():
        """Cập nhật tất cả số lượng trong hệ thống"""
        try:
            # Đồng bộ courses
            Course.batch_update_registration_counts()
            
            # Đồng bộ students count trong classes
            classes = Class.query.all()
            for class_obj in classes:
                count = Student.query.filter_by(class_id=class_obj.id).count()
                if class_obj.current_students != count:
                    class_obj.current_students = count
            
            # Đồng bộ GPA students
            students = Student.query.all()
            for student in students:
                student.update_gpa()
            
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Update counts error: {str(e)}")
            return False

# Schedule auto-sync mỗi 5 phút
def start_auto_sync():
    """Tự động đồng bộ hệ thống định kỳ"""
    import threading
    import time
    
    def sync_worker():
        while True:
            try:
                SystemSync.update_all_counts()
                logger.info("Auto-sync completed")
            except Exception as e:
                logger.error(f"Auto-sync error: {str(e)}")
            time.sleep(300)  # 5 phút
    
    thread = threading.Thread(target=sync_worker, daemon=True)
    thread.start()