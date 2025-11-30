
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file,make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect, generate_csrf, validate_csrf
from flask_migrate import Migrate
from config import config
from models import db, User, UserRole, create_tables, create_sample_data, Teacher, Student, Course, CourseRegistration, Subject, Class, Score, Notification,ClassCourse,auto_register_students_to_class_courses, StudentSkill, StudentCertificate,StudentCourseCart,RegistrationPeriod
from decorators import admin_required, teacher_required, student_required, handle_exceptions, log_activity
import os
from datetime import datetime, date, timedelta,timezone  # THÊM timedelta
from werkzeug.exceptions import BadRequest
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from flask_socketio import SocketIO
from notifications.websocket_handler import socketio, NotificationManager, start_notification_scheduler
from notifications import websocket_handler
import logging
from werkzeug.utils import secure_filename
from forms import LoginForm, RegistrationForm, AddUserForm # Giả định bạn đã định nghĩa RegistrationForm trong forms.py
from io import BytesIO
import pandas as pd
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
socketio = SocketIO()


# app.py (Thêm hàm hỗ trợ)

def update_class_student_count(class_id, change):
    """
    Cập nhật trường 'current_students' của một lớp học.
    :param class_id: ID của Class cần cập nhật.
    :param change: +1 để tăng, -1 để giảm.
    """
    if class_id:
        # Dùng .get() để tìm Class theo ID
        class_obj = db.session.get(Class, class_id)
        if class_obj:
            # Đảm bảo số sinh viên không âm
            if class_obj.current_students + change >= 0:
                class_obj.current_students += change
            else:
                class_obj.current_students = 0 # Hoặc log lỗi
            
            # Không cần commit ở đây, commit sẽ do hàm gọi thực hiện
            db.session.add(class_obj)


# ======== SYSTEM SYNCHRONIZATION SERVICE ========
class SystemSynchronizer:
    """Dịch vụ đồng bộ hóa toàn bộ hệ thống"""
    
    @staticmethod
    def sync_all_data():
        """Đồng bộ tất cả dữ liệu hệ thống"""
        try:
            
            # 1. Đồng bộ số lượng đăng ký khóa học
            Course.batch_update_registration_counts()
            
            # 2. Đồng bộ GPA sinh viên
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
            return True
            
        except Exception as e:
            logger.error(f"System sync error: {str(e)}")
            db.session.rollback()
            return False
    
    @staticmethod
    def validate_course_creation(subject_id, teacher_id, class_ids):
        """Validate trước khi tạo khóa học mới"""
        try:
            errors = []
            
            # Kiểm tra giáo viên có được phân công môn học không
            teacher = Teacher.query.get(teacher_id)
            subject = Subject.query.get(subject_id)
            
            if teacher and subject and subject not in teacher.assigned_subjects:
                errors.append(f"Giáo viên {teacher.full_name} chưa được phân công môn {subject.subject_name}")
            
            # Kiểm tra xung đột lịch học
            if class_ids:
                conflicts = SystemSynchronizer.check_schedule_conflicts(subject_id, class_ids)
                if conflicts:
                    errors.extend(conflicts)
            
            return {
                'valid': len(errors) == 0,
                'errors': errors
            }
            
        except Exception as e:
            return {
                'valid': False,
                'errors': [f'Lỗi validation: {str(e)}']
            }
    
    @staticmethod
    def check_schedule_conflicts(subject_id, class_ids):
        """Kiểm tra xung đột lịch học"""
        # Implementation chi tiết cho kiểm tra lịch học
        conflicts = []
        try:
            subject = Subject.query.get(subject_id)
            
            # Lấy tất cả khóa học hiện có của các lớp được chọn
            for class_id in class_ids:
                class_obj = Class.query.get(class_id)
                for class_course in class_obj.class_courses:
                    existing_course = class_course.course
                    # Kiểm tra nếu môn học đã tồn tại trong lớp
                    if existing_course.subject_id == subject_id:
                        conflicts.append(
                            f"Lớp {class_obj.class_name} đã có môn {subject.subject_name}"
                        )
        
        except Exception as e:
            logger.error(f"Schedule conflict check error: {str(e)}")
            
        return conflicts



def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Vui lòng đăng nhập để truy cập trang này.'
    login_manager.login_message_category = 'warning'
    
    mail = Mail(app)
    csrf = CSRFProtect(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet')
    migrate = Migrate(app, db)
    app.extensions['socketio'] = socketio


    with app.app_context():
        if app.config.get('MAIL_SERVER') and app.config.get('MAIL_USERNAME'):
            logger.info("✅ Email configuration loaded successfully")
            logger.info(f"📧 Mail server: {app.config.get('MAIL_SERVER')}:{app.config.get('MAIL_PORT')}")
            # Test thử kết nối email
            try:
                # Test kết nối email đơn giản
                logger.info("📧 Testing email connection...")
                # Có thể test bằng cách tạo Message nhưng không gửi
            except Exception as e:
                logger.error(f"❌ Email connection test failed: {e}")
        else:
            logger.warning("⚠️ Email configuration missing - email notifications will be disabled")

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    
    @app.after_request
    def set_csrf_cookie(response):
        if response.status_code == 200:
           response.set_cookie('csrf_token', generate_csrf())
        return response

    
    # Utility functions
    def allowed_file(filename):
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

    def sync_class_student_counts():
        """Đồng bộ số lượng sinh viên trong tất cả các lớp"""
        try:
            classes = Class.query.all()
            for class_obj in classes:
                actual_count = len(class_obj.students)
                if class_obj.current_students != actual_count:
                    class_obj.current_students = actual_count
                    db.session.add(class_obj)
                    logger.info(f"Updated class {class_obj.class_name}: {class_obj.current_students} -> {actual_count}")
            db.session.commit()
            logger.info("Class student counts synchronized successfully")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error syncing class student counts: {str(e)}")
            return False

    # Routes
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.is_admin:
                return redirect(url_for('admin_dashboard'))
            elif current_user.is_teacher:
                return redirect(url_for('teacher_dashboard'))
            elif current_user.is_student:
                return redirect(url_for('student_dashboard'))
        return render_template('index.html')
    
    @app.route('/test-all-low-scores')
    @login_required
    @teacher_required
    def test_all_low_scores():
        """Test gửi thông báo cho TẤT CẢ sinh viên điểm kém"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Lấy tất cả khóa học của giáo viên
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
        
            total_sent = 0
            for course in teacher_courses:
            # Gửi thông báo cho tất cả sinh viên điểm kém trong khóa học
                sent_count = NotificationManager.send_bulk_low_score_notifications(course.id)
                total_sent += sent_count
        
            return jsonify({
            'success': True,
            'message': f'Đã gửi thông báo cho {total_sent} sinh viên điểm kém'
        })
        
        except Exception as e:
            logger.error(f"Test all low scores error: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'}), 500
    
    @app.route('/test-email-detailed')
    def test_email_detailed():
        """Test email functionality với log chi tiết"""
        try:
            from flask_mail import Message
        
        # Kiểm tra cấu hình
            logger.info(f"📧 Mail config - Server: {app.config.get('MAIL_SERVER')}")
            logger.info(f"📧 Mail config - Port: {app.config.get('MAIL_PORT')}")
            logger.info(f"📧 Mail config - Username: {app.config.get('MAIL_USERNAME')}")
            logger.info(f"📧 Mail config - Use TLS: {app.config.get('MAIL_USE_TLS')}")
        
        # Kiểm tra xem mail extension đã được khởi tạo chưa
            if not hasattr(app, 'extensions') or 'mail' not in app.extensions:
                return jsonify({
                'success': False,
                'message': '❌ Mail extension chưa được khởi tạo'
            }), 500
        
            msg = Message(
            subject='📧 Test Email từ Hệ thống - ' + datetime.now().strftime('%H:%M:%S'),
            recipients=['leduykhang25012005@gmail.com'],  # Dùng chính email của bạn
            sender=app.config.get('MAIL_DEFAULT_SENDER'),
            body='''
Đây là email test từ hệ thống quản lý học tập.

Thời gian: {time}

Nếu bạn nhận được email này, cấu hình email đang hoạt động tốt!
            '''.format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            html='''
            <h2>✅ Test Email Thành Công!</h2>
            <p>Đây là email test từ hệ thống quản lý học tập.</p>
            <p><strong>Thời gian:</strong> {time}</p>
            <p>Nếu bạn nhận được email này, cấu hình email đang hoạt động tốt!</p>
            <hr>
            <p><strong>Hệ thống Quản lý Học tập</strong></p>
            '''.format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        
            logger.info("🔄 Đang gửi email...")
            mail.send(msg)
            logger.info("✅ Email đã được gửi thành công!")
        
            return jsonify({
            'success': True,
            'message': '✅ Email test đã được gửi thành công! Vui lòng kiểm tra hộp thư.'
        })
        
        except Exception as e:
            logger.error(f"❌ Lỗi gửi email: {str(e)}")
            import traceback
            logger.error(f"❌ Chi tiết lỗi: {traceback.format_exc()}")
        
            return jsonify({
            'success': False,
            'message': f'❌ Lỗi gửi email: {str(e)}'
        }), 500

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        form = LoginForm()

        if form.validate_on_submit():
            username = form.username.data
            password = form.password.data
            remember_me = form.remember_me.data
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password) and user.is_active:
                login_user(user, remember=remember_me)
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()
                flash('Đăng nhập thanh cong!', 'success')
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('index'))
            else:
                flash('Ten dang nhap hoac mat khau khong dung.', 'error ')

        return render_template('login.html', form=form)
    
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        # KHỞI TẠO FORM
        form = RegistrationForm() 
        
        # SỬ DỤNG form.validate_on_submit() để xử lý POST
        if form.validate_on_submit():
            # Registration logic here (Sử dụng form.field.data)
            username = form.username.data
            email = form.email.data
            password = form.password.data
            full_name = form.full_name.data
            student_id = form.student_id.data
            
            # (Bạn vẫn giữ các kiểm tra trùng lặp khác nếu cần, nhưng 
            
            if User.query.filter_by(username=username).first():
                flash('Tên đăng nhập đã tồn tại.', 'error')
                # Truyền form lại để giữ lỗi validation
                return render_template('register.html', form=form) 
            
            if User.query.filter_by(email=email).first():
                flash('Email đã được sử dụng.', 'error')
                # Truyền form lại để giữ lỗi validation
                return render_template('register.html', form=form)
            
            # Create user
            user = User(
                username=username,
                email=email,
                full_name=full_name,
                role=UserRole.STUDENT
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            # Create student profile
            student = Student(
                user_id=user.id,
                student_id=student_id,
                course='K2024'  # Default course
            )
            db.session.add(student)
            db.session.commit()
            
            flash('Đăng ký thành công! Vui lòng đăng nhập.', 'success')
            return redirect(url_for('login'))
        
        # TRUYỀN form vào template khi là GET request hoặc POST thất bại
        return render_template('register.html', form=form)
    
    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Đã đăng xuất thành công.', 'info')
        return redirect(url_for('index'))
    
    

     # API đồng bộ hệ thống
    @app.route('/api/system/sync', methods=['POST'])
    @login_required
    @admin_required
    def api_system_sync():
        """API đồng bộ toàn bộ hệ thống"""
        try:
            if SystemSynchronizer.sync_all_data():
                return jsonify({
                'success': True,
                'message': 'Đồng bộ hệ thống thành công!'
            })
            else:
               return jsonify({
                'success': False,
                'message': 'Lỗi khi đồng bộ hệ thống'
            }), 500
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

# ======== ADDITIONAL SYNC APIs ========

    @app.route('/api/sync/validate-course', methods=['POST'])
    @login_required
    @admin_required
    def api_validate_course():
        """API validate trước khi tạo khóa học"""
        try:
            data = request.get_json()
            subject_id = data.get('subject_id')
            teacher_id = data.get('teacher_id')
            class_ids = data.get('class_ids', [])
        
            validation_result = SystemSynchronizer.validate_course_creation(
            subject_id, teacher_id, class_ids
        )
        
            return jsonify(validation_result)
        
        except Exception as e:
            return jsonify({
            'valid': False,
            'errors': [f'Lỗi validation: {str(e)}']
        }), 500
   
    # Admin Routes
    @app.route('/admin/dashboard')
    @login_required
    @admin_required
    def admin_dashboard():
        stats = {
            'total_students': Student.query.count(),
            'total_teachers': Teacher.query.count(),
            'total_classes': Class.query.count(),
            'total_subjects': Subject.query.count()
        }
        
        recent_activities = []  
        
        return render_template('admin/admin_dashboard.html', 
                             stats=stats, 
                             recent_activities=recent_activities)
    

    
    @app.route('/admin/manage-courses-register')
    @login_required
    @admin_required
    def manage_courses_register():
    
    # ✅ SỬA: Thêm eager loading để tránh N+1 query
        registrations = CourseRegistration.query.options(
        db.joinedload(CourseRegistration.student).joinedload(Student.user),
        db.joinedload(CourseRegistration.student).joinedload(Student.classes),
        db.joinedload(CourseRegistration.course).joinedload(Course.subject)
    ).all()
    
        all_courses = Course.query.options(db.joinedload(Course.subject)).all()


        stats = {
        'total_registrations': len(registrations),
        'approved_registrations': len([r for r in registrations if r.status == 'approved']),
        'pending_registrations': len([r for r in registrations if r.status == 'pending']),
        'rejected_registrations': len([r for r in registrations if r.status == 'rejected']),
        'cancelled_registrations': len([r for r in registrations if r.status == 'cancelled'])
    }
    
        return render_template('admin/manage_course_register.html',
                         registrations=registrations, 
                         courses=all_courses,
                         stats=stats)

    
    @app.route('/admin/manage-users')
    @login_required
    @admin_required
    def manage_users():
        users = User.query.all()
        form = AddUserForm()
        return render_template('admin/manage_users.html', users=users, form = form)
    

    
    @app.route('/delete_user/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required # Sử dụng decorator bạn đã định nghĩa
    def delete_user(user_id):
        user = User.query.get_or_404(user_id)
        if user.id == current_user.id:
            flash('Bạn không thể tự xóa tài khoản của mình.', 'error')
            return redirect(url_for('manage_users'))
        try:
            db.session.delete(user)
            db.session.commit()
            flash(f'User {user.username} đã được xóa thành công.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi xóa user: {str(e)}', 'error')
        return redirect(url_for('manage_users'))
    
    @app.route('/edit_user/<int:user_id>', methods=['GET'])
    @login_required
    @admin_required
    def get_user(user_id):
        user = User.query.get_or_404(user_id)
        user_data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'full_name': user.full_name,
        'role': user.role.value,
        'is_active': user.is_active,
        'phone': user.phone or '',
        'address': user.address or '',
        'avatar': user.avatar or ''
    }
    
        if user.is_teacher and user.teacher_profile:
            user_data.update({
            'department': user.teacher_profile.department,
            'position': user.teacher_profile.position or ''
        })
        elif user.is_student and user.student_profile:
            user_data.update({
            'course': user.student_profile.course,
            'student_id': user.student_profile.student_id
        })

        return jsonify(user_data)

    @app.route('/edit_user/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def update_user(user_id):
        user = User.query.get_or_404(user_id)
    
        try:
            data = request.get_json()
            user.full_name = data.get('full_name', user.full_name)
            user.email = data.get('email', user.email)
            user.phone = data.get('phone', user.phone)
            user.address = data.get('address', user.address)
            user.is_active = data.get('is_active', user.is_active)

            if user.is_teacher and user.teacher_profile:
                user.teacher_profile.department = data.get('department', user.teacher_profile.department)
                user.teacher_profile.position = data.get('position', user.teacher_profile.position)
            elif user.is_student and user.student_profile:
                user.student_profile.course = data.get('course', user.student_profile.course)
        
            db.session.commit()
            return jsonify({'success': True, 'message': 'Cập nhật thông tin thành công!'})
    
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
        
    
    
    @app.route('/view_user/<int:user_id>')
    @login_required
    @admin_required
    def view_user(user_id):
        user = User.query.get_or_404(user_id)

        # Hàm mapping department
        def get_department_display(department_code):
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
            return dept_map.get(department_code, department_code)
    
        user_data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'full_name': user.full_name,
        'role': user.role.value,
        'is_active': user.is_active,
        'created_at': user.created_at.strftime('%d/%m/%Y'),
        'last_login': user.last_login.strftime('%d/%m/%Y %H:%M') if user.last_login else 'Chưa đăng nhập',
        'phone': user.phone or 'Chưa cập nhật',
        'address': user.address or 'Chưa cập nhật',
        'avatar': user.avatar or url_for('static', filename='images/default-avatar.png')
       }
    
    # Thêm thông tin profile dựa trên role
        if user.is_teacher and user.teacher_profile:
            user_data.update({
            'teacher_code': user.teacher_profile.teacher_code,
            'department': get_department_display(user.teacher_profile.department),
            'position': user.teacher_profile.position,
            'join_date': user.teacher_profile.join_date.strftime('%d/%m/%Y') 
            if user.teacher_profile.join_date else 'N/A'
          })
        elif user.is_student and user.student_profile:
            class_names = [cls.class_name for cls in user.student_profile.classes] if user.student_profile.classes else []
            user_data.update({
            'student_id': user.student_profile.student_id,
            'course': user.student_profile.course,
            'class_names': class_names,  # Danh sách lớp
            'class_name': ', '.join(class_names) if class_names else 'Chưa phân lớp',
            'gpa': user.student_profile.gpa,
            'status': user.student_profile.status
        })

        return jsonify(user_data)
     

    @app.route('/admin/manage-students')
    @login_required
    @admin_required
    def manage_students():
        students = Student.query.all()
        student_data = []
        for student in students:
            class_names = [cls.class_name for cls in student.classes]
            student_data.append({
            'id': student.id,
            'student_id': student.student_id,
            'full_name': student.user.full_name,  # Lấy từ User
            'email': student.user.email,  
            'classes': student.classes,  # 🚨 QUAN TRỌNG: trả về danh sách classes
            'class_names': class_names,  # Danh sách tên lớp để hiển thị
            'course': student.course,
            'gpa': student.gpa,
            'status': student.status,
            'phone': student.user.phone,          # Lấy từ User
            'avatar': student.user.avatar         # Lấy từ User
        })
    
        stats = {
        'total_students': len(students),
        'active_students': len([s for s in students if s.status == 'active'])
    }
    
        return render_template('admin/manage_students.html', 
                         students=student_data, 
                         stats=stats)

    


    # THÊM ROUTE QUẢN LÝ GIÁO VIÊN
    @app.route('/admin/manage-teachers')
    @login_required
    @admin_required
    def manage_teachers():
        teachers = Teacher.query.all()
        stats = {
        'total_teachers': len(teachers),
        'active_teachers': len([t for t in teachers if t.status == 'active']),
        'total_subjects': Subject.query.count(),
        'total_classes': Class.query.count()
    }
        return render_template('admin/manage_teachers.html', 
                         teachers=teachers, 
                         stats=stats,
                         all_subjects=Subject.query.all())
    
    @app.route('/admin/add-teacher', methods=['POST'])
    @login_required
    @admin_required
    def add_teacher():
        # Xử lý thêm giáo viên
        try:
            teacher_code = request.form.get('teacher_code')
            full_name = request.form.get('full_name')
            email   = request.form.get('email')
            department = request.form.get('department')

            user = User(
                username=teacher_code,
                full_name=full_name,
                email=email,
                role=UserRole.TEACHER
            )
            user.set_password('123456')
            
            db.session.add(user)
            db.session.flush()
            
            # Create teacher profile
            teacher = Teacher(
                user_id=user.id,
                teacher_code=teacher_code,
                department=department,
                position=request.form.get('position')
            )
            db.session.add(teacher)
            db.session.commit()
            
            flash('Đã thêm giáo viên thành công.', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm giáo viên: {str(e)}', 'error')
        return redirect(url_for('manage_teachers'))
    
    @app.route('/admin/reset-password/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def reset_password(user_id):
        """Reset mật khẩu user về mặc định"""
        try:
            user = User.query.get_or_404(user_id)
            new_password = '123456'  # Mật khẩu mặc định
            user.set_password(new_password)
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã reset mật khẩu cho user {user.full_name}. Mật khẩu mới: 123456'
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
            }), 500
        
    @app.route('/admin/export-students-excel')
    @login_required
    @admin_required
    def export_students_excel():
        try:
        # Lấy danh sách sinh viên
            students = Student.query.all()
         
        # Tạo DataFrame
            data = []
            for student in students:
                class_names = ', '.join([cls.class_name for cls in student.classes]) if student.classes else 'N/A'
                data.append({
                'Mã SV': student.student_id,
                'Họ tên': student.user.full_name,
                'Lớp': class_names,
                'Khóa': student.course,
                'GPA': student.gpa or 'Chưa có',
                'Trạng thái': student.status,
                'Số điện thoại': student.user.phone or 'N/A',
                'Email': student.user.email
            })
        
            df = pd.DataFrame(data)
        
        # Tạo file trong memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Danh sách sinh viên', index=False)
        
            output.seek(0)
        
            filename = f"danh_sach_sinh_vien_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('manage_students'))
        
    @app.route('/admin/export-registrations-excel')
    @login_required
    @admin_required
    def export_registrations_excel():
        try:
        # Lấy danh sách đăng ký
            registrations = CourseRegistration.query.all()
        
        # Tạo DataFrame
            data = []
            for idx, reg in enumerate(registrations, 1):
                student = reg.student
                class_names = ', '.join([cls.class_name for cls in student.classes]) if student.classes else 'N/A'
                data.append({
                'STT': idx,
                'Mã SV': student.student_id,
                'Họ tên': student.user.full_name,
                'Lớp': class_names,
                'Ngày đăng ký': reg.registration_date.strftime('%d/%m/%Y %H:%M') if reg.registration_date else 'N/A',
                'Trạng thái': reg.status,
                'Ghi chú': reg.notes or '--'
            })
        
            df = pd.DataFrame(data)
        
        # Tạo file trong memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Danh sách đăng ký', index=False)
        
            output.seek(0)
        
            filename = f"danh_sach_dang_ky_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('manage_courses_register'))
        
    @app.route('/admin/export-users-excel')
    @login_required
    @admin_required
    def export_users_excel():
        try:
        # Lấy danh sách người dùng
            users = User.query.all()
        
        # Tạo DataFrame
            data = []
            for idx, user in enumerate(users, 1):
                role_text = ''
                if user.role.value == 'admin':
                    role_text = 'Admin'
                elif user.role.value == 'teacher':
                    role_text = 'Giáo viên'
                elif user.role.value == 'student':
                    role_text = 'Sinh viên'
                
                status_text = 'Đang hoạt động' if user.is_active else 'Không hoạt động'
            
                data.append({
                'STT': idx,
                'Họ tên': user.full_name,
                'Email': user.email,
                'Vai trò': role_text,
                'Trạng thái': status_text,
                'Ngày tạo': user.created_at.strftime('%d/%m/%Y')
            })
        
            df = pd.DataFrame(data)
        
        # Tạo file trong memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Danh sách người dùng', index=False)
        
            output.seek(0)
        
            filename = f"danh_sach_nguoi_dung_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('manage_users'))
    
    @app.route('/admin/add-user', methods=['GET','POST'])
    @login_required
    @admin_required
    def add_user():
        form = AddUserForm()
        if form.validate_on_submit():
            try :
                validate_csrf(request.form.get('csrf_token'))
                username = form.username.data
                email = form.email.data
                password = form.password.data
                full_name = form.full_name.data
                role_str = form.role.data 
                is_active = form.is_active.data
                department = form.department.data  # Lấy từ form thay vì request.form
                course_year = form.course_year.data  # Lấy từ form


                if User.query.filter_by(username=username).first():
                    flash('Tài khoản đã toàn tại.', 'error')
                    return render_template('admin/manage_users.html', form=form, users=User.query.all())
                
                if User.query.filter_by(email=email).first():
                    flash('Email đã toàn tại.', 'error')
                    return render_template('admin/manage_users.html', form=form, users=User.query.all())
                
                role_enum = UserRole(role_str)

                user = User(
                    username=username,
                    full_name=full_name,
                    email=email,
                    role=role_enum,
                    is_active=is_active
                )
                user.set_password(password)
                db.session.add(user)
                db.session.flush()

                if role_str == 'teacher':
                    if not department:
                        flash('Vui lòng chọn chuyên ngành cho giáo viên.', 'error')
                        db.session.rollback()
                        return render_template('admin/manage_users.html', form=form, users=User.query.all())
                    

                    teacher = Teacher(
                        user_id=user.id,
                        teacher_code=username,
                        department=department,
                        position='Giảng viên'
                    )
                    db.session.add(teacher)
                    flash(f'Đã thêm giáo viên {full_name} thành công - Chuyên ngành: {department}.', 'success')
                


                elif role_str =='student':
                    if not course_year:
                        flash('Vui lòng chọn năm học cho học viên.', 'error')
                        db.session.rollback()
                        return render_template('admin/manage_users.html', form=form, users=User.query.all())
                    

                    student = Student(
                        user_id=user.id,
                        student_id = username,
                        course = course_year,
                        
                    )
                    db.session.add(student)
                    flash(f'Đã thêm học viên {full_name} thành công - Khóa: {course_year}.', 'success')


                else:
                    flash(f'Đã thêm admin {full_name} thành công.', 'success')

                db.session.commit()
                return redirect(url_for('manage_users'))
            except Exception as e:
                db.session.rollback()
                flash(f'Lỗi khi thêm tài khoản: {str(e)}', 'error')
        users = User.query.all()
        return render_template('admin/manage_users.html', users=users, form=form)
        
    
    @app.route('/api/teacher/<int:teacher_id>/assign-subjects', methods=['POST'])
    @login_required
    @admin_required
    def api_assign_subjects(teacher_id):
        try:
            data = request.get_json()
            subject_ids = data.get('subjects', [])
    
            print(f"Teacher ID: {teacher_id}")
            print(f"Subject IDs: {subject_ids}")
    
            teacher = Teacher.query.get_or_404(teacher_id)
    
        # Lấy các subject từ database
            subjects = Subject.query.filter(Subject.id.in_(subject_ids)).all()
            print(f"Tìm kiếm {len(subjects)} subjects")
    
        # 🔧 SỬA: XÓA CÁC PHÂN CÔNG CŨ TRƯỚC KHI THÊM MỚI
        # Đảm bảo đồng bộ với relationship many-to-many
            teacher.assigned_subjects.clear()  # XÓA TẤT CẢ QUAN HỆ CŨ
        
        # THÊM CÁC MÔN HỌC MỚI
            teacher.update_subject_count()
            for subject in subjects:
                teacher.assigned_subjects.append(subject)
                # subject.update_teacher_count()
    
            db.session.commit()
    
            print("Subjects assigned successfully")
            return jsonify({
        'success': True,
        'message': 'Phân công môn học thành công!'
        })
    
        except Exception as e:
            db.session.rollback()
            print(f"Error assigning subjects: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
        'success': False,
        'message': f'Lỗi khi phân công môn học: {str(e)}'
    }), 500
        
    @app.route('/api/teacher/<int:teacher_id>/validate-subjects', methods=['POST'])
    @login_required
    @admin_required
    def validate_teacher_subjects(teacher_id):
        """Validate xem giáo viên có thể dạy các môn học được phân công không"""
        try:
            data = request.get_json()
            subject_ids = data.get('subject_ids', [])
        
            teacher = Teacher.query.get_or_404(teacher_id)
            subjects = Subject.query.filter(Subject.id.in_(subject_ids)).all()
        
            invalid_subjects = []
            for subject in subjects:
                if subject.department != teacher.department:
                   invalid_subjects.append({
                    'subject_name': subject.subject_name,
                    'subject_department': subject.department_name,
                    'teacher_department': teacher.department_display
                })
        
            return jsonify({
            'valid': len(invalid_subjects) == 0,
            'invalid_subjects': invalid_subjects,
            'message': f'Phát hiện {len(invalid_subjects)} môn không cùng bộ môn' if invalid_subjects else 'Hợp lệ'
        })
        
        except Exception as e:
            return jsonify({'valid': False, 'message': f'Lỗi: {str(e)}'}), 500
        
    @app.route('/test-low-score')
    @login_required
    @teacher_required
    def test_low_score():
        """Tạo dữ liệu test cho thông báo điểm kém"""
        try:
        # Tìm một sinh viên và khóa học của giáo viên hiện tại
            teacher_id = current_user.teacher_profile.id
            course = Course.query.filter_by(teacher_id=teacher_id).first()
        
            if not course:
                return jsonify({'success': False, 'message': 'Giáo viên chưa có khóa học'})
        
        # Tìm sinh viên đã đăng ký khóa học
            registration = CourseRegistration.query.filter_by(
            course_id=course.id, 
            status='approved'
        ).first()
        
            if not registration:
                return jsonify({'success': False, 'message': 'Khóa học chưa có sinh viên'})
        
            student = registration.student
        
        # Tạo hoặc cập nhật điểm kém
            score = Score.query.filter_by(
            student_id=student.id,
            course_id=course.id
        ).first()
        
            if not score:
                score = Score(
                student_id=student.id,
                course_id=course.id,
                process_score=3.0,
                exam_score=2.0,
                final_score=2.5,  # Điểm kém
                status='published'
            )
                db.session.add(score)
            else:
                score.final_score = 2.5  # Đặt điểm kém
                score.status = 'published'
        
            db.session.commit()
        
        # Kích hoạt thông báo điểm kém
            from notifications.websocket_handler import trigger_low_score_notifications
            trigger_low_score_notifications(score)
        
            return jsonify({
            'success': True,
            'message': f'Đã tạo điểm kém cho sinh viên {student.user.full_name}'
        })
        
        except Exception as e:
            logger.error(f"Test low score error: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'}), 500
    

    @app.route('/api/teacher/low-scores')
    @login_required 
    @teacher_required
    def api_get_low_scores():
        """API lấy danh sách sinh viên điểm kém của giáo viên"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Lấy tất cả khóa học của giáo viên
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            course_ids = [course.id for course in teacher_courses]
        
        # Lấy sinh viên điểm kém (< 5.0)
            low_scores = Score.query.filter(
            Score.course_id.in_(course_ids),
            Score.final_score < 5.0,
            Score.status == 'published'
        ).options(
            db.joinedload(Score.student).joinedload(Student.user),
            db.joinedload(Score.course).joinedload(Course.subject),
            db.joinedload(Score.student).joinedload(Student.classes)
        ).all()
        
            low_score_data = []
            for score in low_scores:
                student = score.student
                course = score.course

                notification_sent = Notification.query.filter_by(
                user_id=student.user_id,
                category='academic'
                ).filter(
                Notification.title.like(f"%{course.subject.subject_name}%"),
                Notification.created_at >= datetime.now(timezone.utc) - timedelta(days=7)
                ).first() is not None

            
                low_score_data.append({
                'id': score.id, 
                'student_id': student.id,
                'student_name': student.user.full_name,
                'student_code': student.student_id,
                'course_name': course.subject.subject_name,
                'course_code': course.course_code,
                'process_score': score.process_score,
                'exam_score': score.exam_score,
                'final_score': score.final_score,
                'grade': score.grade,
                'class_name': student.classes[0].class_name if student.classes else 'N/A',
                'notification_sent': notification_sent,
                'contact_email': student.user.email,
                'contact_phone': student.user.phone,
                'avatar': student.user.avatar or url_for('static', filename='images/default-avatar.png'),  
                'last_contact':None
            })
        
            return jsonify({
            'success': True,
            'low_scores': low_score_data,
            'total': len(low_score_data)
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
    

    @app.route('/api/teacher/send-lowscore-notification', methods=['POST'])
    @login_required
    @teacher_required
    def api_send_lowscore_notification():
        """API gửi thông báo điểm kém"""
        try:
            data = request.get_json()
            score_ids = data.get('score_ids', [])
        
            if not score_ids:
                return jsonify({
                'success': False,
                'message': 'Không có điểm nào được chọn'
            }), 400
        
            sent_count = 0
            for score_id in score_ids:
                score = Score.query.get(score_id)
                if score and score.final_score < 5.0:
                # Kiểm tra quyền truy cập
                    course = Course.query.get(score.course_id)
                    if course.teacher_id != current_user.teacher_profile.id:
                        continue
                    
                    from notifications.websocket_handler import trigger_low_score_notifications
                    trigger_low_score_notifications(score)
                    sent_count += 1
        
            return jsonify({
            'success': True,
            'message': f'Đã gửi thông báo cho {sent_count} sinh viên',
            'sent_count': sent_count
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/teacher/send-all-lowscore-notifications')
    @login_required
    @teacher_required
    def api_send_all_lowscore_notifications():
        """API gửi thông báo cho tất cả sinh viên điểm kém"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Lấy tất cả khóa học của giáo viên
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            course_ids = [course.id for course in teacher_courses]
        
        # Lấy sinh viên điểm kém
            low_scores = Score.query.filter(
            Score.course_id.in_(course_ids),
            Score.final_score < 5.0,
            Score.status == 'published'
        ).all()
        
            sent_count = 0
            for score in low_scores:
                from notifications.websocket_handler import trigger_low_score_notifications
                trigger_low_score_notifications(score)
                sent_count += 1
        
            return jsonify({
            'success': True,
            'message': f'Đã gửi thông báo cho {sent_count} sinh viên điểm kém',
            'sent_count': sent_count
        })
        
        except Exception as e:
            logger.error(f"Error sending all low score notifications: {str(e)}")
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
    
    @app.route('/api/teacher/send-bulk-lowscore-notifications', methods=['POST'])
    @login_required
    @teacher_required
    def api_send_bulk_lowscore_notifications():
        """API gửi hàng loạt thông báo điểm kém"""
        try:
            data = request.get_json()
            score_ids = data.get('score_ids', [])
            custom_message = data.get('message')
            include_advice = data.get('include_advice', True)
            notify_parents = data.get('notify_parents', False)
        
            if not score_ids:
                return jsonify({
                'success': False,
                'message': 'Không có điểm nào được chọn'
            }), 400
        
            sent_count = 0
            for score_id in score_ids:
                score = Score.query.get(score_id)
                if score and score.final_score < 5.0:
                    from notifications.websocket_handler import trigger_low_score_notifications
                    trigger_low_score_notifications(score)
                    sent_count += 1
        
            return jsonify({
            'success': True,
            'message': f'Đã gửi thông báo cho {sent_count} sinh viên',
            'sent_count': sent_count
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
    
        
    @app.route('/api/teacher/submit-low-score-report', methods=['POST'])
    @login_required
    @teacher_required
    def api_submit_low_score_report():
        """API gửi báo cáo điểm kém"""
        try:
            validate_csrf(request.form.get('csrf_token'))
            data = request.get_json()
            selected_students = data.get('selected_students', [])
            title = data.get('title', '')
            content = data.get('content', '')
            send_email = data.get('send_email', True)
            send_web_notification = data.get('send_web_notification', True)
        
            teacher_id = current_user.teacher_profile.id
            teacher_name = current_user.full_name
        
            reported_count = 0
        
            for student_data in selected_students:
                student_id = student_data.get('student_id')
                course_code = student_data.get('course_code')
            
            # Tìm sinh viên và khóa học
                student = Student.query.get(student_id)
                if not student:
                    continue
                
            # Tìm khóa học theo course_code và teacher_id
                course = Course.query.filter_by(
                course_code=course_code,
                teacher_id=teacher_id
            ).first()
            
                if not course:
                    continue
            
            # Tìm điểm của sinh viên trong khóa học này
                score = Score.query.filter_by(
                student_id=student_id,
                course_id=course.id
            ).first()
            
                if not score:
                    continue
            
            # Tạo nội dung thông báo chi tiết
                notification_message = f"""
{content}

📊 Thông tin điểm:
• Môn học: {course.subject.subject_name}
• Điểm quá trình: {score.process_score or 'Chưa có'}
• Điểm thi: {score.exam_score or 'Chưa có'}  
• Điểm tổng: {score.final_score:.1f}
• Xếp loại: {score.grade}

👨‍🏫 Giáo viên báo cáo: {teacher_name}
📅 Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}
            """.strip()
            
            # Gửi thông báo web
                if send_web_notification:
                    NotificationManager.send_notification(
                    student.user_id,
                    title,
                    notification_message,
                    category='academic',
                    priority='high',
                    action_url='/student/scores'
                )
            
            # Gửi email
                if send_email:
                    try:
                        from flask_mail import Message
                        from flask import current_app
                    
                        mail = current_app.extensions.get('mail')
                        if mail:
                           email_body = f"""
                        <h2>{title}</h2>
                        <p>{content.replace(chr(10), '<br>')}</p>
                        
                        <h3>📊 Thông tin điểm chi tiết:</h3>
                        <ul>
                            <li><strong>Môn học:</strong> {course.subject.subject_name}</li>
                            <li><strong>Điểm quá trình:</strong> {score.process_score or 'Chưa có'}</li>
                            <li><strong>Điểm thi:</strong> {score.exam_score or 'Chưa có'}</li>
                            <li><strong>Điểm tổng:</strong> {score.final_score:.1f}</li>
                            <li><strong>Xếp loại:</strong> {score.grade}</li>
                        </ul>
                        
                        <p><strong>Giáo viên báo cáo:</strong> {teacher_name}</p>
                        <p><strong>Thời gian:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                        
                        <hr>
                        <p><em>Đây là thông báo tự động từ hệ thống Quản lý Học tập</em></p>
                        """
                        
                        msg = Message(
                            subject=f"📋 {title}",
                            recipients=[student.user.email],
                            html=email_body,
                            sender=current_app.config.get('MAIL_DEFAULT_SENDER')
                        )
                        mail.send(msg)
                        logger.info(f"✅ Low score report email sent to {student.user.email}")
                    except Exception as e:
                        logger.error(f"Error sending report email: {str(e)}")
            
                reported_count += 1
        
            return jsonify({
            'success': True,
            'message': f'Đã gửi báo cáo cho {reported_count} sinh viên',
            'reported_count': reported_count
        })
        
        except Exception as e:
            logger.error(f"Error submitting low score report: {str(e)}")
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/teacher/student/<int:student_id>/details')
    @login_required
    @teacher_required
    def api_get_student_details(student_id):
        """API lấy chi tiết thông tin sinh viên"""
        try:
            student = Student.query.get_or_404(student_id)
            teacher_id = current_user.teacher_profile.id
        
        # Kiểm tra giáo viên có dạy sinh viên này không
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            teacher_course_ids = [course.id for course in teacher_courses]
        
            student_scores = Score.query.filter(
            Score.student_id == student_id,
            Score.course_id.in_(teacher_course_ids)
        ).options(
            db.joinedload(Score.course).joinedload(Course.subject)
        ).all()
        
            recent_scores = []
            for score in student_scores[-5:]:  # Lấy 5 điểm gần nhất
                recent_scores.append({
                'course_name': score.course.subject.subject_name,
                'final_score': score.final_score,
                'grade': score.grade
            })
        
            student_data = {
            'id': student.id,
            'student_id': student.student_id,
            'full_name': student.user.full_name,
            'email': student.user.email,
            'phone': student.user.phone,
            'avatar': student.user.avatar,
            'class_name': student.classes[0].class_name if student.classes else 'N/A',
            'course': student.classes[0].course if student.classes else 'N/A',
            'gpa': student.gpa,
            'status': student.status,
            'address': student.user.address,
            'recent_scores': recent_scores
        }
        
            return jsonify({
            'success': True,
            'student': student_data
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/teacher/notifications/stats')
    @login_required
    @teacher_required
    def api_get_notification_stats():
        """API lấy thống kê thông báo"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Lấy tất cả khóa học của giáo viên
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            course_ids = [course.id for course in teacher_courses]
        
        # Đếm sinh viên điểm kém
            low_scores_count = Score.query.filter(
            Score.course_id.in_(course_ids),
            Score.final_score < 5.0,
            Score.status == 'published'
        ).count()
        
        # Đếm sinh viên cần liên hệ (điểm < 3.0)
            need_contact_count = Score.query.filter(
            Score.course_id.in_(course_ids),
            Score.final_score < 3.0,
            Score.status == 'published'
        ).count()
        
        # Đếm sinh viên đã được thông báo (trong 7 ngày qua)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            notified_count = db.session.query(Notification).join(
            Student, Notification.user_id == Student.user_id
        ).filter(
                Student.id.in_(
                    db.session.query(Score.student_id).filter(
                    Score.course_id.in_(course_ids),
                    Score.final_score < 5.0
                )
            ),
            Notification.category == 'academic',
            Notification.created_at >= seven_days_ago
        ).count()
        
            stats = {
            'low_score_count': low_scores_count,
            'need_contact_count': need_contact_count,
            'notified_count': notified_count,
            'total_low_scores': low_scores_count
        }
        
            return jsonify({
            'success': True,
            'stats': stats
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/teacher/export-low-scores')
    @login_required
    @teacher_required
    def api_export_low_scores():
        """API export danh sách điểm kém"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Lấy dữ liệu điểm kém
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            course_ids = [course.id for course in teacher_courses]
        
            low_scores = Score.query.filter(
            Score.course_id.in_(course_ids),
            Score.final_score < 5.0,
            Score.status == 'published'
        ).options(
            db.joinedload(Score.student).joinedload(Student.user),
            db.joinedload(Score.course).joinedload(Course.subject)
        ).all()
        
        # Tạo file Excel
            import pandas as pd
            from io import BytesIO
        
            data = []
            for score in low_scores:
                student = score.student
                course = score.course
            
                data.append({
                'Mã SV': student.student_id,
                'Họ tên': student.user.full_name,
                'Lớp': student.classes[0].class_name if student.classes else 'N/A',
                'Môn học': course.subject.subject_name,
                'Mã môn': course.course_code,
                'Điểm QT': score.process_score,
                'Điểm thi': score.exam_score,
                'Điểm tổng': score.final_score,
                'Xếp loại': score.grade,
                'Email': student.user.email,
                'SĐT': student.user.phone or 'N/A'
            })
        
            df = pd.DataFrame(data)
        
        # Tạo file trong memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Sinh viên điểm kém', index=False)
        
            output.seek(0)
        
            filename = f"sinh_vien_diem_kem_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi khi export: {str(e)}'
        }), 500

    @app.route('/api/subject/<int:subject_id>/available-teachers')
    @login_required
    @admin_required
    def get_available_teachers_for_subject(subject_id):
        """Lấy danh sách giáo viên có thể dạy môn học (cùng department)"""
        try:
            subject = Subject.query.get_or_404(subject_id)
        
        # Lấy giáo viên cùng department và đã được phân công môn này
            teachers = Teacher.query.filter_by(department=subject.department).all()
        
            teacher_data = []
            for teacher in teachers:
                teacher_data.append({
                'id': teacher.id,
                'full_name': teacher.full_name,
                'department_display': teacher.department_display,
                'is_assigned': subject in teacher.assigned_subjects
            })
        
            return jsonify({
            'success': True,
            'teachers': teacher_data
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
        
    @app.route('/admin/manage-classes')
    @login_required
    @admin_required
    def manage_classes():
        classes = Class.query.all()
        teachers = Teacher.query.all()
        stats = {
            'total_classes': len(classes),
            'total_students': sum(c.current_students for c in classes),
            'avg_students_per_class': sum(c.current_students for c in classes) / len(classes) if classes else 0,
            'new_classes_this_month': 0  # Would be calculated
        }
        return render_template('admin/manage_classes.html', 
                             classes=classes, 
                             stats=stats,
                             teachers=teachers)
    

    def register_vietnamese_fonts():
        """Cách đơn giản nhất - sử dụng font mặc định và encoding UTF-8"""
        try:
        # ĐĂNG KÝ FONT TIẾNG VIỆT TỐT NHẤT
            font_paths = [
            # Font macOS mới (Apple đã hỗ trợ Unicode rất tốt)
            '/System/Library/Fonts/Arial.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            '/System/Library/Fonts/SFNS.ttf',  # San Francisco - font hệ thống macOS
        ]
        
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        pdfmetrics.registerFont(TTFont('VietnameseFont', font_path))
                        pdfmetrics.registerFont(TTFont('VietnameseFont-Bold', font_path))
                        print(f"✅ Đã đăng ký font: {os.path.basename(font_path)}")
                        return True
                    except:
                        continue
        
        # Nếu không tìm thấy font nào, sử dụng HELVETICA (có sẵn trong ReportLab)
            print("⚠️  Sử dụng font Helvetica mặc định")
            return True
        
        except Exception as e:
            print(f"❌ Lỗi đăng ký font: {e}")
            return True  # VẪN trả về True để tiếp tục với font mặc định



    @app.route('/admin/teachers/export-pdf')
    @login_required
    @admin_required
    def export_teachers_pdf():
        try:

            register_vietnamese_fonts()

        # Lấy tham số bộ lọc
            search = request.args.get('search', '')
            department = request.args.get('department', '')
            status_filter = request.args.get('status', '')
        
        # Lọc giáo viên
            query = Teacher.query
        
            if search:
                query = query.join(User).filter(
                    db.or_(
                    User.full_name.ilike(f'%{search}%'),
                    Teacher.teacher_code.ilike(f'%{search}%'),
                    User.email.ilike(f'%{search}%')
                )
            )
        
            if department:
                query = query.filter(Teacher.department == department)
            
            if status_filter:
                query = query.filter(Teacher.status == status_filter)
        
            teachers = query.all()
        
        # Tạo PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30,encoding='utf-8')
            elements = []
        
        # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,
            encoding='utf-8',  # Center
            textColor=colors.HexColor('#2c3e50')
        )
        
        # Tiêu đề
            title = Paragraph("DANH SÁCH GIÁO VIÊN", title_style)
            elements.append(title)
        
        # Thông tin xuất
            info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.gray,
            alignment=1
        )
            export_info = Paragraph(
            f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')} | "
            f"Tổng số: {len(teachers)} giáo viên",
            info_style
        )
            elements.append(export_info)
            elements.append(Spacer(1, 20))
        
        # Dữ liệu bảng
            data = [['STT', 'Mã GV', 'Họ tên', 'Bộ môn', 'Môn phụ trách', 'Trạng thái', 'Email']]
        
            for i, teacher in enumerate(teachers, 1):
                subjects = ", ".join([subj.subject_name for subj in teacher.assigned_subjects[:3]])
                if len(teacher.assigned_subjects) > 3:
                    subjects += f" (+{len(teacher.assigned_subjects) - 3})"
                
                status_map = {
                'active': 'Đang làm việc',
                'busy': 'Bận',
                'inactive': 'Nghỉ việc'
            }
            
                data.append([
                str(i),
                teacher.teacher_code,
                teacher.full_name,
                teacher.department_display,
                subjects or 'Chưa phân công',
                status_map.get(teacher.status, teacher.status),
                teacher.user.email
            ])
        
        # Tạo bảng
            table = Table(data, colWidths=[30, 60, 100, 80, 120, 70, 120])
            table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        
            elements.append(table)
        
        # Tạo PDF
            doc.build(elements)
            buffer.seek(0)
        
        # Trả về file PDF
            response = make_response(buffer.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename=danh_sach_giao_vien_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'
        
            return response
        
        except Exception as e:
            logger.error(f"Error exporting teachers PDF: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi khi xuất PDF: {str(e)}'}), 500

# Thêm route export PDF cho môn học
    @app.route('/admin/subjects/export-pdf')
    @login_required
    @admin_required
    def export_subjects_pdf():
        try:
            register_vietnamese_fonts()
        # Lấy tham số bộ lọc
            search = request.args.get('search', '')
            department = request.args.get('department', '')
            type_filter = request.args.get('type', '')
            semester = request.args.get('semester', '')
        
        # Lọc môn học
            query = Subject.query.options(db.joinedload(Subject.courses).joinedload(Course.teacher))
        
            if search:
                query = query.filter(
                    db.or_(
                    Subject.subject_name.ilike(f'%{search}%'),
                    Subject.subject_code.ilike(f'%{search}%')
                )
            )
        
            if department:
                query = query.filter(Subject.department == department)
            
            if type_filter:
                query = query.filter(Subject.type == type_filter)
            
            if semester:
                query = query.filter(Subject.semester == int(semester))
        
            subjects = query.all()
        
        # Tạo PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30,encoding='utf-8')
            elements = []
        
        # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,
            textColor=colors.HexColor('#2c3e50'),
            encoding='utf-8'
        )
        
        # Tiêu đề
            title = Paragraph("DANH SÁCH MÔN HỌC", title_style)
            elements.append(title)
        
        # Thông tin xuất
            info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.gray,
            alignment=1
        )
            export_info = Paragraph(
            f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')} | "
            f"Tổng số: {len(subjects)} môn học",
            info_style
        )
            elements.append(export_info)
            elements.append(Spacer(1, 20))
        
        # Dữ liệu bảng
            data = [['STT', 'Mã MH', 'Tên môn học', 'Tín chỉ', 'Bộ môn', 'Loại', 'HK', 'Số GV']]
        
            for i, subject in enumerate(subjects, 1):
                type_map = {
                'general': 'Đại cương',
                'major': 'Chuyên ngành',
                'elective': 'Tự chọn'
            }
                
                teacher_count = 0
                if subject.courses:
                    teacher_ids = set()
                    for course in subject.courses:
                        if course.teacher_id:
                            teacher_ids.add(course.teacher_id)
                    teacher_count = len(teacher_ids)
                
                
                data.append([
                str(i),
                subject.subject_code,
                subject.subject_name,
                str(subject.credits),
                subject.department_name,
                type_map.get(subject.type, subject.type),
                str(subject.semester),
                str(teacher_count)  # SỬA: dùng teacher_count thay vì subject.teachers
            ])
            
                
        # Tạo bảng
            table = Table(data, colWidths=[30, 60, 150, 40, 80, 70, 30, 40])
            table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        
            elements.append(table)
        
        # Tạo PDF
            doc.build(elements)
            buffer.seek(0)
        
        # Trả về file PDF
            response = make_response(buffer.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename=danh_sach_mon_hoc_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'

        
            return response
        
        except Exception as e:
            logger.error(f"Error exporting subjects PDF: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi khi xuất PDF: {str(e)}'}), 500
        
    # Thêm vào app.py - sau các route hiện có

    @app.route('/admin/export/classes/excel')
    @login_required
    @admin_required
    def export_classes_excel():
        """Export danh sách lớp học ra Excel"""
        try:
      
        
            classes = Class.query.all()
        
            data = []
            for class_obj in classes:
                data.append({
                'Mã lớp': class_obj.class_code,
                'Tên lớp': class_obj.class_name,
                'Khóa': class_obj.course,
                'Khoa/Viện': class_obj.faculty,
                'Số SV hiện tại': class_obj.current_students,
                'Số SV tối đa': class_obj.max_students,
                'GVCN': class_obj.teacher.user.full_name if class_obj.teacher else 'Chưa phân công',
                'Trạng thái': 'Đang học' if class_obj.status == 'active' else 'Đã tốt nghiệp'
            })
        
            df = pd.DataFrame(data)
        
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Danh sách lớp học', index=False)
        
            output.seek(0)
        
            filename = f"danh_sach_lop_hoc_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('manage_classes'))

    @app.route('/admin/export/courses/excel')
    @login_required
    @admin_required
    def export_courses_excel():
        """Export danh sách khóa học ra Excel"""
        try:
        
        
            courses = Course.query.all()
        
            data = []
            for course in courses:
                data.append({
                'Mã khóa học': course.course_code,
                'Tên môn': course.subject.subject_name if course.subject else 'N/A',
                'Mã môn': course.subject.subject_code if course.subject else 'N/A',
                'Học kỳ': course.semester,
                'Năm học': course.year,
                'Giảng viên': course.teacher.user.full_name if course.teacher else 'N/A',
                'Số SV hiện tại': course.current_students,
                'Số SV tối đa': course.max_students,
                'Phòng học': course.room or 'Chưa có',
                'Trạng thái': course.status,
                'Ngày bắt đầu': course.start_date.strftime('%d/%m/%Y') if course.start_date else 'N/A',
                'Ngày kết thúc': course.end_date.strftime('%d/%m/%Y') if course.end_date else 'N/A'
            })
        
            df = pd.DataFrame(data)
        
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Danh sách khóa học', index=False)
        
            output.seek(0)
        
            filename = f"danh_sach_khoa_hoc_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('manage_courses'))
    
    @app.route('/admin/fix-student-counts', methods=['POST'])
    @login_required
    @admin_required
    def fix_student_counts():
        """Sửa số lượng sinh viên trong các lớp"""
        try:
            if sync_class_student_counts():
                flash('Đã đồng bộ số lượng sinh viên thành công!', 'success')
            else:
                flash('Lỗi khi đồng bộ số lượng sinh viên', 'error')
        except Exception as e:
            flash(f'Lỗi: {str(e)}', 'error')
    
        return redirect(url_for('manage_classes'))

    # Thêm route xóa lớp học
    @app.route('/admin/classes/delete/<int:class_id>', methods=['POST'])
    @login_required
    @admin_required 
    def delete_class(class_id):
        try:
            class_obj = Class.query.get_or_404(class_id)
        
        # Kiểm tra nếu lớp có sinh viên
            if class_obj.students:
                return jsonify({
                'success': False, 
                'message': 'Không thể xóa lớp đang có sinh viên. Vui lòng chuyển sinh viên sang lớp khác trước.'
            })
        
            db.session.delete(class_obj)
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã xóa lớp "{class_obj.class_name}" thành công!'
        })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi khi xóa lớp: {str(e)}'
        }), 500

# Thêm route sửa lớp học
    @app.route('/admin/classes/edit/<int:class_id>', methods=['POST'])
    @login_required
    @admin_required
    def edit_class(class_id):
        try:
            class_obj = Class.query.get_or_404(class_id)
        
            class_obj.class_name = request.form.get('class_name', class_obj.class_name)
            class_obj.class_code = request.form.get('class_code', class_obj.class_code)
            class_obj.course = request.form.get('course', class_obj.course)
            class_obj.faculty = request.form.get('faculty', class_obj.faculty)
            class_obj.teacher_id = request.form.get('teacher_id', class_obj.teacher_id)
            class_obj.max_students = int(request.form.get('max_students', class_obj.max_students))
            class_obj.description = request.form.get('description', class_obj.description)
        
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã cập nhật lớp "{class_obj.class_name}" thành công!'
            })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi khi cập nhật lớp: {str(e)}'
        }), 500

# Thêm route xóa môn học
    @app.route('/admin/subjects/delete/<int:subject_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_subject(subject_id):
        try:
            subject = Subject.query.get_or_404(subject_id)
        
        # Kiểm tra nếu môn học có khóa học
            if subject.courses:
                return jsonify({
                'success': False, 
                'message': 'Không thể xóa môn học đang có khóa học. Vui lòng xóa các khóa học liên quan trước.'
            })
        
            subject_name = subject.subject_name
            db.session.delete(subject)
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã xóa môn học "{subject_name}" thành công!'
        })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi khi xóa môn học: {str(e)}'
        }), 500

    

# Thêm route sửa môn học
    @app.route('/admin/subjects/edit/<int:subject_id>', methods=['POST'])
    @login_required
    @admin_required
    def edit_subject(subject_id):
        try:
            subject = Subject.query.get_or_404(subject_id)
        
            subject.subject_name = request.form.get('subject_name', subject.subject_name)
            subject.subject_code = request.form.get('subject_code', subject.subject_code)
            subject.credits = int(request.form.get('credits', subject.credits))
            subject.department = request.form.get('department', subject.department)
            subject.type = request.form.get('type', subject.type)
            subject.semester = int(request.form.get('semester', subject.semester))
            subject.theory_hours = int(request.form.get('theory_hours', subject.theory_hours))
            subject.practice_hours = int(request.form.get('practice_hours', subject.practice_hours))
            subject.description = request.form.get('description', subject.description)
        
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã cập nhật môn học "{subject.subject_name}" thành công!'
        })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi khi cập nhật môn học: {str(e)}'
        }), 500

    # Thêm route lấy thông tin lớp học
    @app.route('/admin/classes/edit/<int:class_id>', methods=['GET'])
    @login_required
    @admin_required
    def get_class(class_id):
        try:
            class_obj = Class.query.get_or_404(class_id)
        
            return jsonify({
            'class_code': class_obj.class_code,
            'class_name': class_obj.class_name,
            'course': class_obj.course,
            'faculty': class_obj.faculty,
            'teacher_id': class_obj.teacher_id,
            'max_students': class_obj.max_students,
            'description': class_obj.description
        })
        
        except Exception as e:
            return jsonify({
            'error': f'Lỗi khi lấy thông tin lớp: {str(e)}'
        }), 500

# Thêm route lấy thông tin môn học
    @app.route('/admin/subjects/edit/<int:subject_id>', methods=['GET'])
    @login_required
    @admin_required
    def get_subject(subject_id):
        try:
            subject = Subject.query.get_or_404(subject_id)
        
            return jsonify({
            'subject_code': subject.subject_code,
            'subject_name': subject.subject_name,
            'credits': subject.credits,
            'department': subject.department,
            'type': subject.type,
            'semester': subject.semester,
            'theory_hours': subject.theory_hours,
            'practice_hours': subject.practice_hours,
            'description': subject.description
        })
        
        except Exception as e:
            return jsonify({
            'error': f'Lỗi khi lấy thông tin môn học: {str(e)}'
        }), 500

    @app.route('/admin/manage-subjects')
    @login_required
    @admin_required
    def manage_subjects():
        subjects = Subject.query.all()
        stats = {
            'total_subjects': len(subjects),
            'general_subjects': len([s for s in subjects if s.type == 'general']),
            'major_subjects': len([s for s in subjects if s.type == 'major']),
            'avg_credits': sum(s.credits for s in subjects) / len(subjects) if subjects else 0
        }
        return render_template('admin/manage_subjects.html', 
                             subjects=subjects, 
                             stats=stats,
                             all_subjects=subjects)
    
    @app.route('/admin/subjects/add', methods=['POST'])
    @login_required
    @admin_required
    def add_subject():
        if request.method == 'POST':
            try:
                try:
                    validate_csrf(request.form.get('csrf_token'))
                except BadRequest:
                    flash('CSRF token không hợp lệ. Vui lòng thử lại.', 'error')
                    return redirect(url_for('manage_subjects'))
            
            # Lấy dữ liệu từ form
                subject_code = request.form.get('subject_code')
                subject_name = request.form.get('subject_name')
                credits = request.form.get('credits')
                semester = request.form.get('semester')
                department = request.form.get('department')
                subject_type = request.form.get('type')
                theory_hours = request.form.get('theory_hours')
                practice_hours = request.form.get('practice_hours')
                description = request.form.get('description')
            
            # Kiểm tra mã môn học đã tồn tại chưa
                existing_subject = Subject.query.filter_by(subject_code=subject_code).first()
                if existing_subject:
                    flash('Mã môn học đã tồn tại. Vui lòng chọn mã khác.', 'error')
                    return redirect(url_for('manage_subjects'))
            
            # Tạo môn học mới
                new_subject = Subject(
                subject_code=subject_code,
                subject_name=subject_name,
                credits=int(credits) if credits else 3,
                semester=int(semester) if semester else 1,
                department=department,
                type=subject_type,
                theory_hours=int(theory_hours) if theory_hours else 30,
                practice_hours=int(practice_hours) if practice_hours else 15,
                description=description
            )
            
                db.session.add(new_subject)
                db.session.commit()
            
                flash(f'Đã thêm môn học "{subject_name}" thành công!', 'success')
            
            except Exception as e:
                db.session.rollback()
                flash(f'Lỗi khi thêm môn học: {str(e)}', 'error')
    
        return redirect(url_for('manage_subjects'))

    
    # TÌM VÀ SỬA route manage_courses (khoảng dòng 800)
    @app.route('/admin/manage-courses')
    @login_required
    @admin_required
    def manage_courses():
        try:
            from sqlalchemy.orm import joinedload

            courses = Course.query.options(
               db.joinedload(Course.subject),
               db.joinedload(Course.teacher).joinedload(Teacher.user),
               db.joinedload(Course.class_courses).joinedload(ClassCourse.class_),
            ).all()

            classes = Class.query.all()

            stats ={
            'total_courses': len(courses),
            'active_courses': len([c for c in courses if c.status == 'active']),
            'upcoming_courses': len([c for c in courses if c.status == 'upcoming']),
            'completed_courses': len([c for c in courses if c.status == 'completed'])
        }
    
            return render_template('admin/manage_courses.html',
                         courses=courses,
                         classes=classes,
                         subjects=Subject.query.all(),
                         teachers=Teacher.query.all(),
                         stats=stats)
                             
        except Exception as e:
            flash(f'Lỗi khi tải trang quản lý khóa học: {str(e)}', 'error')
            return redirect(url_for('admin_dashboard'))
    
    @app.route('/admin/courses/add', methods=['POST'])
    @login_required
    @admin_required
    def add_course():
        if request.method == 'POST':
            try:
            # Lấy dữ liệu từ form
                course_code = request.form.get('course_code')
                subject_id = request.form.get('subject_id')
                teacher_id = request.form.get('teacher_id')
                semester = request.form.get('semester')
                year = request.form.get('year')
                max_students = request.form.get('max_students')
                classroom = request.form.get('classroom')
                status = request.form.get('status')
                start_date = request.form.get('start_date')
                end_date = request.form.get('end_date')
                description = request.form.get('description')
                class_ids = request.form.getlist('class_ids')  # QUAN TRỌNG: lấy class_ids

                # KIỂM TRA VÀ TỰ ĐỘNG PHÂN CÔNG
                teacher = Teacher.query.get(int(teacher_id))
                subject = Subject.query.get(int(subject_id))
            
                if teacher and subject and subject not in teacher.assigned_subjects:
                # Tự động phân công môn học cho giáo viên
                    teacher.assigned_subjects.append(subject)
                    db.session.add(teacher)
                    flash(f'Đã tự động phân công môn {subject.subject_name} cho giáo viên {teacher.full_name}', 'info')

            # Debug: in ra dữ liệu nhận được
                print(f"Creating course: {course_code}, subject: {subject_id}, teacher: {teacher_id}")
                print(f"Class IDs: {class_ids}")
                print(f"Semester type: {type(semester)}, value: {semester}")  # Debug semester

            # Kiểm tra dữ liệu bắt buộc
                if not all([course_code, subject_id, teacher_id, semester, year]):
                    flash('Vui lòng điền đầy đủ các trường bắt buộc.', 'error')
                    return redirect(url_for('manage_courses'))

            # Kiểm tra mã khóa học đã tồn tại chưa
                existing_course = Course.query.filter_by(course_code=course_code).first()
                if existing_course:
                    flash('Mã khóa học đã tồn tại. Vui lòng chọn mã khóa học khác.', 'error')
                    return redirect(url_for('manage_courses'))

            # Tạo khóa học mới - SỬA: bỏ qua validation tạm thời
                new_course = Course(
                course_code=course_code,
                subject_id=int(subject_id) if subject_id else None,
                teacher_id=int(teacher_id) if teacher_id else None,
                semester=int(semester) if semester else 1,
                year=year,
                max_students=int(max_students) if max_students else 50,  # SỬA: max_stents -> max_students
                room=classroom,
                status=status,
                start_date=datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None,
                end_date=datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None,
                description=description,
                current_students=0,  # Đảm bảo khởi tạo = 0
                registered_students=0  # Đảm bảo khởi tạo = 0
            )
            
                db.session.add(new_course)
                db.session.flush()  # Lấy ID của course mới
                total_registered = 0

            # Gán khóa học cho các lớp được chọn
                if class_ids:
                    for class_id in class_ids:
                        class_course = ClassCourse(
                        class_id=class_id,
                        course_id=new_course.id,
                        semester=f"HK{semester}-{year}",
                        academic_year=year
                    )
                        db.session.add(class_course)
                         
                    # Tự động đăng ký sinh viên
                registered_count = new_course.auto_register_class_students()
                if registered_count > 0:
                    new_course.current_students = registered_count
                    new_course.registered_students = registered_count
                    total_registered += registered_count
                
                db.session.commit()
                flash(f'Đã thêm khóa học "{course_code}" thành công.', 'success')
            
            except Exception as e:
                db.session.rollback()
                print(f"Error creating course: {str(e)}")  # Debug
                import traceback
                print(f"Traceback: {traceback.format_exc()}")  # Chi tiết lỗi
                flash(f'Lỗi khi thêm khóa học: {str(e)}', 'error')
        
            return redirect(url_for('manage_courses'))
        
    @app.route('/admin/reports')
    @login_required
    @admin_required
    def reports():
        reports_list = []  # Would be populated with generated reports
        
        stats = {
            'total_students': Student.query.count(),
            'total_courses': Course.query.count(),
            'avg_gpa': db.session.query(db.func.avg(Student.gpa)).scalar() or 0
        }
        
        return render_template('admin/reports.html',
                             reports=reports_list,
                             stats=stats)
    
    # Teacher Routes
    @app.route('/teacher/dashboard')
    @login_required
    @teacher_required
    def teacher_dashboard():
        teacher_courses = Course.query.filter_by(teacher_id=current_user.teacher_profile.id).all()
    
        student_set = set()
        for course in teacher_courses:
        # Lấy tất cả sinh viên đã đăng ký và được duyệt trong khóa học này
            registrations = CourseRegistration.query.filter_by(
            course_id=course.id,
            status='approved'
        ).all()
            for reg in registrations:
                student_set.add(reg.student_id)
    
        actual_total_students = len(student_set)
    
        stats = {
        'total_courses': len(teacher_courses),
        'total_students': actual_total_students,  # SỬA: Dùng số lượng không trùng lặp
        'pending_grading': Score.query.filter(
            Score.course_id.in_([c.id for c in teacher_courses]),
            Score.status == 'draft'
        ).count(),
        'upcoming_classes': 0  # Would be calculated
    }
    
        upcoming_classes = []  # Would be populated
        teaching_tasks = []    # Would be populated
        recent_activities = [] # Would be populated
    
        performance = {
        'avg_score': 8.0,  # Would be calculated
        'attendance_rate': 95,  # Would be calculated
        'pass_rate': 90,   # Would be calculated
        'rating': 4.5      # Would be calculated
    }
    
        return render_template('teacher/teacher_dashboard.html',
                         stats=stats,
                         upcoming_classes=upcoming_classes,
                         teaching_tasks=teaching_tasks,
                         recent_activities=recent_activities,
                         performance=performance)
    @app.route('/teacher/class-list')
    @login_required
    @teacher_required
    def teacher_class_list():
        """Danh sách lớp học của giáo viên - ĐÃ SỬA"""
        try:
            teacher_id = current_user.teacher_profile.id
        
            print(f"DEBUG: Teacher ID = {teacher_id}")
        
        # SỬA: Query đơn giản và chính xác hơn
        # Lấy tất cả ClassCourse mà giáo viên này dạy, kèm thông tin đầy đủ
            class_courses = ClassCourse.query.join(
            Course, ClassCourse.course_id == Course.id
        ).filter(
            Course.teacher_id == teacher_id
        ).options(
            db.joinedload(ClassCourse.class_),
            db.joinedload(ClassCourse.course).joinedload(Course.subject),
            db.joinedload(ClassCourse.course).joinedload(Course.teacher).joinedload(Teacher.user)
        ).all()
        
            print(f"DEBUG: Found {len(class_courses)} class_courses")
        
        # Tạo danh sách lớp học duy nhất
            unique_classes = {}
        
            for class_course in class_courses:
                class_obj = class_course.class_
                course = class_course.course
            
                if not class_obj:
                    continue
                
                class_id = class_obj.id
                if class_id not in unique_classes:
                # Lấy tất cả khóa học của giáo viên trong lớp này
                    teacher_courses_in_class = [
                    cc for cc in class_obj.class_courses 
                    if cc.course.teacher_id == teacher_id
                ]
                    actual_student_count = Student.query.filter(
                    Student.classes.any(id=class_id)
                ).count()
                
                    print(f"DEBUG: Class {class_obj.class_name} - Student count: {actual_student_count}")
                    
                # Tính điểm trung bình - SỬA: Xử lý trường hợp không có điểm
                    total_avg = 0
                    valid_courses = 0
                    for cc in teacher_courses_in_class:
                        course_avg = calculate_course_avg_score(cc.course_id)
                        if course_avg > 0:
                            total_avg += course_avg
                            valid_courses += 1
                
                    avg_score = round(total_avg / valid_courses, 2) if valid_courses > 0 else 0.0
                
                    unique_classes[class_id] = {
                    'id': class_obj.id,
                    'class_name': class_obj.class_name,
                    'class_code': class_obj.class_code,
                    'course_name': course.subject.subject_name if course and course.subject else 'N/A',
                    'course_code': course.course_code if course else 'N/A',
                    'semester': course.semester if course else 1,
                    'year': course.year if course else 'N/A',
                    'student_count': actual_student_count,
                    'avg_score': avg_score,
                    'status': course.status if course else 'unknown',
                    'room': course.room if course else 'Chưa có phòng',
                    'schedule': course.schedule if course else 'Chưa có lịch',
                    'completed_weeks': calculate_completed_weeks(course) if course else 0,
                    'total_weeks': 15,
                    'teacher_role': 'Giảng viên chính',
                    'icon': course.subject.icon if course and course.subject else 'book',
                    'course_count': len(teacher_courses_in_class),
                    'course_id': course.id if course else None  # THÊM: để dùng cho link
                }
        
            classes_data = list(unique_classes.values())
        
            print(f"DEBUG: Final result - {len(classes_data)} unique classes")
            for cls in classes_data:
                print(f"  - {cls['class_name']}: {cls['course_count']} courses, {cls['student_count']} students")
        
            return render_template('teacher/teacher_class_list.html', 
                             classes=classes_data)
                             
        except Exception as e:
            logger.error(f"Error in teacher_class_list: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            flash('Lỗi khi tải danh sách lớp học. Vui lòng thử lại.', 'error')
            return redirect(url_for('teacher_dashboard'))
        
    @app.route('/teacher/classes/export-pdf')
    @login_required
    @teacher_required
    def export_teacher_classes_pdf():
        """Export danh sách lớp học của giáo viên ra PDF"""
        try:
            register_vietnamese_fonts()
            teacher_id = current_user.teacher_profile.id
        
        # Lấy danh sách lớp học của giáo viên
            class_courses = ClassCourse.query.join(
            Course, ClassCourse.course_id == Course.id
        ).filter(
            Course.teacher_id == teacher_id
        ).options(
            db.joinedload(ClassCourse.class_),
            db.joinedload(ClassCourse.course).joinedload(Course.subject),
        ).all()

        # Tạo PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30)
            elements = []

        # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,
            textColor=colors.HexColor('#2c3e50')
        )

        # Tiêu đề
            title = Paragraph("DANH SÁCH LỚP HỌC - GIÁO VIÊN", title_style)
            elements.append(title)

        # Thông tin giáo viên
            info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.gray,
            alignment=1
        )
        
            teacher_info = f"Giáo viên: {current_user.full_name} | Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            export_info = Paragraph(teacher_info, info_style)
            elements.append(export_info)
            elements.append(Spacer(1, 20))

        # Dữ liệu bảng
            data = [['STT', 'Mã lớp', 'Tên lớp', 'Môn học', 'Học kỳ', 'Số SV', 'Điểm TB', 'Trạng thái']]

            unique_classes = {}
            for class_course in class_courses:
                class_obj = class_course.class_
                course = class_course.course
            
                if not class_obj:
                    continue
                
                class_id = class_obj.id
                if class_id not in unique_classes:
                # Tính điểm trung bình
                    teacher_courses_in_class = [
                    cc for cc in class_obj.class_courses 
                    if cc.course.teacher_id == teacher_id
                ]
                
                    total_avg = 0
                    valid_courses = 0
                    for cc in teacher_courses_in_class:
                        course_avg = calculate_course_avg_score(cc.course_id)
                        if course_avg > 0:
                            total_avg += course_avg
                            valid_courses += 1
                
                    avg_score = round(total_avg / valid_courses, 2) if valid_courses > 0 else 0.0
                
                    unique_classes[class_id] = {
                    'class_name': class_obj.class_name,
                    'class_code': class_obj.class_code,
                    'course_name': course.subject.subject_name if course and course.subject else 'N/A',
                    'semester': course.semester if course else 1,
                    'student_count': Student.query.filter(Student.classes.any(id=class_id)).count(),
                    'avg_score': avg_score,
                    'status': course.status if course else 'unknown'
                }

        # Thêm dữ liệu vào bảng
            for i, (class_id, class_data) in enumerate(unique_classes.items(), 1):
                status_text = {
                'active': 'Đang học',
                'upcoming': 'Sắp bắt đầu', 
                'completed': 'Đã kết thúc'
            }.get(class_data['status'], class_data['status'])
            
                data.append([
                str(i),
                class_data['class_code'],
                class_data['class_name'],
                class_data['course_name'],
                f"HK{class_data['semester']}",
                str(class_data['student_count']),
                f"{class_data['avg_score']:.2f}",
                status_text
            ])

        # Tạo bảng
            table = Table(data, colWidths=[30, 60, 100, 120, 40, 50, 50, 60])
            table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))

            elements.append(table)

        # Tạo PDF
            doc.build(elements)
            buffer.seek(0)

        # Trả về file PDF
            response = make_response(buffer.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename=danh_sach_lop_hoc_giao_vien_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'

            return response

        except Exception as e:
            logger.error(f"Error exporting teacher classes PDF: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi khi xuất PDF: {str(e)}'}), 500

# Thêm route export Excel cho teacher_input_scores
    @app.route('/teacher/scores/export-excel/<int:course_id>')
    @login_required
    @teacher_required
    def export_teacher_scores_excel(course_id):
        """Export điểm khóa học ra Excel"""
        try:
            teacher_id = current_user.teacher_profile.id
            course = Course.query.filter_by(id=course_id, teacher_id=teacher_id).first()
        
            if not course:
                flash('Không tìm thấy khóa học hoặc không có quyền truy cập', 'error')
                return redirect(url_for('teacher_input_scores'))

        # Lấy danh sách sinh viên và điểm
            result = Course.get_course_with_students(course_id, teacher_id)
            if not result:
                flash('Không thể lấy dữ liệu điểm', 'error')
                return redirect(url_for('teacher_input_scores'))

            students = result['students']
        
        # Tạo DataFrame
            data = []
            for student in students:
            # Tính điểm tổng nếu chưa có
                final_score = student.get('final_score')
                if not final_score and student.get('process_score') and student.get('exam_score'):
                    final_score = (student['process_score'] * 0.4) + (student['exam_score'] * 0.6)
            
            # Tính xếp loại
                grade_info = calculate_detailed_grade(final_score) if final_score else {'letterGrade': 'N/A', 'text': 'Chưa có điểm'}
            
                data.append({
                'STT': len(data) + 1,
                'Mã SV': student['student_id'],
                'Họ tên': student['full_name'],
                'Lớp': student['class_name'],
                'Điểm QT': student.get('process_score') or '',
                'Điểm thi': student.get('exam_score') or '',
                'Điểm tổng': round(final_score, 2) if final_score else '',
                'Xếp loại': grade_info['letterGrade'],
                'Mô tả': grade_info['text'],
                'Ghi chú': student.get('notes') or ''
            })

            df = pd.DataFrame(data)

        # Tạo file Excel
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet điểm chi tiết
                df.to_excel(writer, sheet_name='Bảng điểm chi tiết', index=False)
            
            # Sheet thống kê
                stats_data = calculate_score_statistics(students)
                stats_df = pd.DataFrame([stats_data])
                stats_df.to_excel(writer, sheet_name='Thống kê', index=False)

            output.seek(0)

            filename = f"bang_diem_{course.course_code}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

        except Exception as e:
            logger.error(f"Error exporting scores Excel: {str(e)}")
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('teacher_input_scores'))

    def calculate_detailed_grade(score):
        """Tính xếp loại chi tiết"""
        if score is None or score == '':
            return {'letterGrade': 'N/A', 'gradePoint': 0, 'text': 'Chưa có điểm'}
    
        numeric_score = float(score)
    
        if numeric_score >= 9.0: return {'letterGrade': 'A+', 'gradePoint': 4.0, 'text': 'Xuất sắc'}
        if numeric_score >= 8.5: return {'letterGrade': 'A', 'gradePoint': 4.0, 'text': 'Giỏi'}
        if numeric_score >= 8.0: return {'letterGrade': 'B+', 'gradePoint': 3.5, 'text': 'Khá giỏi'}
        if numeric_score >= 7.0: return {'letterGrade': 'B', 'gradePoint': 3.0, 'text': 'Khá'}
        if numeric_score >= 6.5: return {'letterGrade': 'C+', 'gradePoint': 2.5, 'text': 'Trung bình khá'}
        if numeric_score >= 5.5: return {'letterGrade': 'C', 'gradePoint': 2.0, 'text': 'Trung bình'}
        if numeric_score >= 5.0: return {'letterGrade': 'D+', 'gradePoint': 1.5, 'text': 'Trung bình yếu'}
        if numeric_score >= 4.0: return {'letterGrade': 'D', 'gradePoint': 1.0, 'text': 'Yếu'}
    
        return {'letterGrade': 'F', 'gradePoint': 0.0, 'text': 'Kém'}

    def calculate_score_statistics(students):
        """Tính thống kê điểm"""
        scores = []
        for student in students:
            if student.get('final_score'):
                scores.append(float(student['final_score']))
            elif student.get('process_score') and student.get('exam_score'):
                final_score = (student['process_score'] * 0.4) + (student['exam_score'] * 0.6)
                scores.append(final_score)
    
        if not scores:
            return {
            'Tổng số SV': len(students),
            'Đã chấm điểm': 0,
            'Chưa chấm': len(students),
            'Điểm TB': 0,
            'Điểm cao nhất': 0,
            'Điểm thấp nhất': 0,
            'Tỷ lệ đỗ': '0%'
        }
    
        avg_score = sum(scores) / len(scores)
        max_score = max(scores)
        min_score = min(scores)
        pass_count = len([s for s in scores if s >= 5.0])
        pass_rate = (pass_count / len(scores)) * 100
    
        return {
        'Tổng số SV': len(students),
        'Đã chấm điểm': len(scores),
        'Chưa chấm': len(students) - len(scores),
        'Điểm TB': round(avg_score, 2),
        'Điểm cao nhất': round(max_score, 2),
        'Điểm thấp nhất': round(min_score, 2),
        'Tỷ lệ đỗ': f'{pass_rate:.1f}%'
    }
    
    def calculate_course_avg_score(course_id):
        """Tính điểm trung bình của khóa học - ĐÃ SỬA XỬ LÝ LỖI"""
        try:
            scores = Score.query.filter_by(course_id=course_id).all()
            if not scores:
                return 0.0
    
            valid_scores = [s.final_score for s in scores if s.final_score is not None]
            if not valid_scores:
                return 0.0
        
            return round(sum(valid_scores) / len(valid_scores), 2)
        except Exception as e:
            logger.error(f"Error calculating course avg score for course {course_id}: {str(e)}")
            return 0.0
        
    def calculate_completed_weeks(course):
        """Tính số tuần đã hoàn thành - ĐÃ SỬA XỬ LÝ LỖI"""
        if not course or not course.start_date:
            return 0

        from datetime import datetime
        today = datetime.now().date()

        if course.start_date > today:
            return 0

        if course.end_date and course.end_date < today:
            return 15  # Đã hoàn thành

    # Tính số tuần từ start_date đến today
        try:
            days_passed = (today - course.start_date).days
            weeks_passed = days_passed // 7
            return min(weeks_passed, 15)
        except Exception as e:
            logger.error(f"Error calculating completed weeks: {str(e)}")
            return 0

    @app.route('/teacher/student-list')
    @login_required
    @teacher_required
    def teacher_student_list():
        """Danh sách sinh viên - ĐÃ SỬA HOÀN TOÀN"""
        try:
            teacher_id = current_user.teacher_profile.id
            course_id = request.args.get('course_id')
            class_id = request.args.get('class_id')

            students_data = []
            current_course = None
            current_class = None
            class_stats = {'avg_score': 0, 'attendance_rate': 0, 'pass_rate': 0}

        # TRƯỜNG HỢP 1: Có course_id - hiển thị sinh viên của khóa học CỤ THỂ
            if course_id:
                current_course = Course.query.filter_by(
                id=course_id, 
                teacher_id=teacher_id  # QUAN TRỌNG: Kiểm tra giáo viên có dạy khóa này
            ).first()
                
                if not current_course:
                    flash('Không tìm thấy khóa học hoặc không có quyền truy cập', 'error')
                    return redirect(url_for('teacher_class_list'))
                
                class_courses = ClassCourse.query.filter_by(course_id=course_id).all()
                class_ids = [cc.class_id for cc in class_courses]

            # Lấy sinh viên đã đăng ký khóa học này
                registrations = CourseRegistration.query.filter_by(
                course_id=course_id, 
                status='approved'
            ).options(
                db.joinedload(CourseRegistration.student)
                    .joinedload(Student.user),
                db.joinedload(CourseRegistration.student)
                    .joinedload(Student.classes),
            ).all()

                for reg in registrations:
                    student = reg.student
                # Lấy điểm ĐÚNG từ khóa học HIỆN TẠI
                    score = Score.query.filter_by(
                    student_id=student.id, 
                    course_id=course_id  # QUAN TRỌNG: course_id hiện tại
                ).first()
                    

                    correct_class_name = "N/A"
                    for class_obj in student.classes:
                        if class_obj.id in class_ids:
                            correct_class_name = class_obj.class_name
                            break
                    else:
                    # Nếu không tìm thấy, lấy lớp đầu tiên
                        correct_class_name = student.classes[0].class_name if student.classes else "N/A"

                    students_data.append({
                    'id': student.id,
                    'student_id': student.student_id,
                    'full_name': student.user.full_name,
                    'email': student.user.email,
                    'class_name': correct_class_name,
                    'avatar': student.user.avatar,
                    'process_score': score.process_score if score else None,
                    'exam_score': score.exam_score if score else None,
                    'final_score': score.final_score if score else None,
                    'grade': score.grade if score else None,
                    'attendance_rate': 95  # Có thể tính từ bảng attendance
                })

            # Tính thống kê cho khóa học HIỆN TẠI
                class_stats = calculate_course_statistics(course_id)

        # TRƯỜNG HỢP 2: Có class_id - hiển thị tất cả sinh viên trong lớp với điểm từ các môn của GIÁO VIÊN NÀY
            elif class_id:
                current_class = Class.query.get(class_id)
                if not current_class:
                    flash('Không tìm thấy lớp học', 'error')
                    return redirect(url_for('teacher_class_list'))

            # Kiểm tra giáo viên có dạy lớp này không
                teacher_has_access = False
                teacher_courses_in_class = []
            
                for class_course in current_class.class_courses:
                    if class_course.course.teacher_id == teacher_id:
                       teacher_has_access = True
                       teacher_courses_in_class.append(class_course.course)

                if not teacher_has_access:
                    flash('Bạn không có quyền truy cập lớp học này', 'error')
                    return redirect(url_for('teacher_class_list'))

            # Lấy tất cả sinh viên trong lớp
                for student in current_class.students:
                # Tìm điểm số từ các khóa học của GIÁO VIÊN NÀY trong lớp này
                    scores_in_teacher_courses = []
                    for course in teacher_courses_in_class:
                        score = Score.query.filter_by(
                        student_id=student.id,
                        course_id=course.id
                    ).first()
                        if score:
                            scores_in_teacher_courses.append(score)

                # Ưu tiên hiển thị điểm từ khóa học gần đây nhất hoặc active
                    recent_score = None
                    if scores_in_teacher_courses:
                    # Ưu tiên khóa học đang active
                        active_scores = [s for s in scores_in_teacher_courses 
                                   if s.course.status == 'active']
                        if active_scores:
                            recent_score = active_scores[0]
                        else:
                            recent_score = scores_in_teacher_courses[0]

                    students_data.append({
                    'id': student.id,
                    'student_id': student.student_id,
                    'full_name': student.user.full_name,
                    'email': student.user.email,
                    'class_name': current_class.class_name,
                    'avatar': student.user.avatar,
                    'process_score': recent_score.process_score if recent_score else None,
                    'exam_score': recent_score.exam_score if recent_score else None,
                    'final_score': recent_score.final_score if recent_score else None,
                    'grade': recent_score.grade if recent_score else None,
                    'attendance_rate': 0
                })

        # TRƯỜNG HỢP 3: Không có tham số - hiển thị tất cả sinh viên từ các khóa học của GIÁO VIÊN NÀY
            else:
            # Lấy tất cả khóa học của giáo viên
                teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            
            # Tạo set để tránh trùng lặp sinh viên
                student_course_classes = {}
            
                for course in teacher_courses:
                    class_courses = ClassCourse.query.filter_by(course_id=course.id).all()
                    course_class_ids = [cc.class_id for cc in class_courses]
                    registrations = CourseRegistration.query.filter_by(
                    course_id=course.id, 
                    status='approved'
                ).options(
                    db.joinedload(CourseRegistration.student)
                        .joinedload(Student.user),
                    db.joinedload(CourseRegistration.student)
                        .joinedload(Student.classes),
                ).all()

                    for reg in registrations:
                        student = reg.student

                        correct_class_name = "N/A"
                        for class_obj in student.classes:
                            if class_obj.id in course_class_ids:
                                correct_class_name = class_obj.class_name
                                break
                        else:
                        # Nếu không tìm thấy, lấy lớp đầu tiên
                            correct_class_name = student.classes[0].class_name if student.classes else "N/A"
                    
                    # Lưu lớp chính xác cho sinh viên
                        key = f"{student.id}_{course.id}"
                        student_course_classes[key] = correct_class_name

                    
                    # Lấy điểm từ khóa học HIỆN TẠI (của giáo viên này)
                        score = Score.query.filter_by(
                        student_id=student.id, 
                        course_id=course.id
                    ).first()

                        students_data.append({
                        'id': student.id,
                        'student_id': student.student_id,
                        'full_name': student.user.full_name,
                        'email': student.user.email,
                        'class_name': correct_class_name,
                        'avatar': student.user.avatar,
                        'process_score': score.process_score if score else None,
                        'exam_score': score.exam_score if score else None,
                        'final_score': score.final_score if score else None,
                        'grade': score.grade if score else None,
                        'attendance_rate': 95
                    })

            return render_template('teacher/teacher_student_list.html',
            students=students_data,
            current_course=current_course,
            current_class_id=class_id,
            class_stats=class_stats
            )
        
        except Exception as e:
            logger.error(f"Error in teacher_student_list: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            flash('Lỗi khi tải danh sách sinh viên', 'error')
            return redirect(url_for('teacher_class_list'))

     
    def calculate_course_statistics(course_id):
        """Tính thống kê cho khóa học CỤ THỂ - ĐÃ SỬA"""
        scores = Score.query.filter_by(course_id=course_id).all()
    
        if not scores:
            return {'avg_score': 0, 'attendance_rate': 0, 'pass_rate': 0}
    
        valid_scores = [s.final_score for s in scores if s.final_score is not None]
    
        if not valid_scores:
            return {'avg_score': 0, 'attendance_rate': 0, 'pass_rate': 0}
    
        avg_score = round(sum(valid_scores) / len(valid_scores), 2)
        pass_rate = len([s for s in valid_scores if s >= 5.0]) / len(valid_scores) * 100
    
        return {
        'avg_score': avg_score,
        'attendance_rate': 95,  # Có thể tính từ bảng attendance
        'pass_rate': round(pass_rate, 1)
        }

    @app.route('/teacher/input-scores')
    @app.route('/teacher/input-scores/<int:course_id>')
    @login_required
    @teacher_required
    def teacher_input_scores(course_id=None):
        """Trang nhập điểm cho giáo viên - hỗ trợ cả có và không có course_id"""
        teacher_id = current_user.teacher_profile.id
    
        try:
        # Lấy tất cả khóa học của giáo viên
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
        
        # Lấy danh sách lớp duy nhất từ các khóa học
            teacher_classes = []
            for course in teacher_courses:
                for class_course in course.class_courses:
                    class_obj = class_course.class_
                    if class_obj and class_obj not in teacher_classes:
                        teacher_classes.append(class_obj)
        
        # Xử lý khi có course_id (trang chi tiết)
            selected_course = None
            students_data = []
        
            if course_id:
                result = Course.get_course_with_students(course_id, teacher_id)
                if result:
                    selected_course = result['course']
                    students_data = result['students']
                else:
                    flash('Không tìm thấy khóa học hoặc không có quyền truy cập', 'error')
        
            return render_template('teacher/teacher_input_scores.html',
                         classes=teacher_classes,
                         courses=teacher_courses,
                         selected_course=selected_course,
                         students=students_data)
                         
        except Exception as e:
            logger.error(f"Error in teacher_input_scores: {str(e)}")
            flash('Lỗi khi tải trang nhập điểm', 'error')
            return redirect(url_for('teacher_dashboard'))
        
    @app.route('/teacher/students/export-excel')
    @login_required
    @teacher_required
    def export_teacher_students_excel():
        """Export danh sách sinh viên của giáo viên ra Excel"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Lấy tham số từ URL
            course_id = request.args.get('course_id')
            class_id = request.args.get('class_id')
        
        # Lấy dữ liệu sinh viên dựa trên tham số
            students_data = []
        
            if course_id:
            # Lấy sinh viên của khóa học cụ thể
                result = Course.get_course_with_students(course_id, teacher_id)
                if result:
                    students_data = result['students']
                    course = result['course']
                    title = f"Danh sách sinh viên - {course.course_code}"
                else:
                    flash('Không tìm thấy khóa học', 'error')
                    return redirect(url_for('teacher_student_list'))
                
            elif class_id:
            # Lấy tất cả sinh viên trong lớp
                class_obj = Class.query.get(class_id)
                if class_obj:
                    for student in class_obj.students:
                        students_data.append({
                        'student_id': student.student_id,
                        'full_name': student.user.full_name,
                        'email': student.user.email,
                        'class_name': class_obj.class_name,
                        'phone': student.user.phone or 'N/A',
                        'status': student.status
                    })
                    title = f"Danh sách sinh viên - {class_obj.class_name}"
                else:
                    flash('Không tìm thấy lớp học', 'error')
                    return redirect(url_for('teacher_student_list'))
            else:
            # Lấy tất cả sinh viên từ các khóa học của giáo viên
                teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
                student_set = set()
            
                for course in teacher_courses:
                    registrations = CourseRegistration.query.filter_by(
                    course_id=course.id, 
                    status='approved'
                ).all()
                    for reg in registrations:
                        student = reg.student
                        class_names = ', '.join([cls.class_name for cls in student.classes]) if student.classes else 'N/A'
                    
                        students_data.append({
                        'student_id': student.student_id,
                        'full_name': student.user.full_name,
                        'email': student.user.email,
                        'class_name': class_names,
                        'phone': student.user.phone or 'N/A',
                        'status': student.status
                    })
                title = "Danh sách sinh viên - Tất cả khóa học"

        # Tạo DataFrame
            data = []
            for idx, student in enumerate(students_data, 1):
                data.append({
                'STT': idx,
                'Mã SV': student['student_id'],
                'Họ tên': student['full_name'],
                'Email': student['email'],
                'Lớp': student['class_name'],
                'Số điện thoại': student.get('phone', 'N/A'),
                'Trạng thái': student.get('status', 'active')
            })

            df = pd.DataFrame(data)

        # Tạo file Excel
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Danh sách sinh viên', index=False)
            
            # Auto-adjust columns width
                worksheet = writer.sheets['Danh sách sinh viên']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = (max_length + 2)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

            output.seek(0)

            filename = f"danh_sach_sinh_vien_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

        except Exception as e:
            logger.error(f"Error exporting teacher students Excel: {str(e)}")
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('teacher_student_list'))


    @app.route('/teacher/students/export-pdf')
    @login_required
    @teacher_required
    def export_teacher_students_pdf():
        """Export danh sách sinh viên của giáo viên ra PDF"""
        try:
            register_vietnamese_fonts()
            teacher_id = current_user.teacher_profile.id
        
        # Lấy tham số từ URL
            course_id = request.args.get('course_id')
            class_id = request.args.get('class_id')
        
        # Lấy dữ liệu sinh viên
            students_data = []
            title = "Danh sách sinh viên"
        
            if course_id:
                result = Course.get_course_with_students(course_id, teacher_id)
                if result:
                    students_data = result['students']
                    course = result['course']
                    title = f"Danh sách sinh viên - {course.course_code}"
                
            elif class_id:
                class_obj = Class.query.get(class_id)
                if class_obj:
                    for student in class_obj.students:
                        students_data.append({
                        'student_id': student.student_id,
                        'full_name': student.user.full_name,
                        'email': student.user.email,
                        'class_name': class_obj.class_name
                    })
                    title = f"Danh sách sinh viên - {class_obj.class_name}"
            else:
                teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
                for course in teacher_courses:
                    registrations = CourseRegistration.query.filter_by(
                    course_id=course.id, 
                    status='approved'
                ).all()
                    for reg in registrations:
                        student = reg.student
                        class_names = ', '.join([cls.class_name for cls in student.classes]) if student.classes else 'N/A'
                    
                        students_data.append({
                        'student_id': student.student_id,
                        'full_name': student.user.full_name,
                        'email': student.user.email,
                        'class_name': class_names
                    })
                title = "Danh sách sinh viên - Tất cả khóa học"

        # Tạo PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30)
            elements = []

        # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,
            textColor=colors.HexColor('#2c3e50')
        )

        # Tiêu đề
            title_paragraph = Paragraph(title, title_style)
            elements.append(title_paragraph)

        # Thông tin giáo viên và thời gian
            info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.gray,
            alignment=1
        )
        
            teacher_info = f"Giáo viên: {current_user.full_name} | Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Tổng số: {len(students_data)} sinh viên"
            export_info = Paragraph(teacher_info, info_style)
            elements.append(export_info)
            elements.append(Spacer(1, 20))

        # Dữ liệu bảng
            data = [['STT', 'Mã SV', 'Họ tên', 'Lớp', 'Email']]

            for i, student in enumerate(students_data, 1):
                data.append([
                str(i),
                student['student_id'],
                student['full_name'],
                student['class_name'],
                student['email']
            ])

        # Tạo bảng
            table = Table(data, colWidths=[30, 80, 120, 80, 150])
            table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))

            elements.append(table)

        # Tạo PDF
            doc.build(elements)
            buffer.seek(0)

        # Trả về file PDF
            response = make_response(buffer.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename=danh_sach_sinh_vien_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'

            return response

        except Exception as e:
            logger.error(f"Error exporting teacher students PDF: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi khi xuất PDF: {str(e)}'}), 500
        
    
    def get_teacher_students_data(teacher_id, course_id=None, class_id=None):
        """Lấy dữ liệu sinh viên cho giáo viên"""
        students_data = []
    
        if course_id:
        # Lấy sinh viên của khóa học cụ thể
            result = Course.get_course_with_students(course_id, teacher_id)
            if result:
                return result['students']
    
        elif class_id:
        # Lấy sinh viên của lớp cụ thể
            class_obj = Class.query.get(class_id)
            if class_obj:
                for student in class_obj.students:
                    students_data.append({
                    'student_id': student.student_id,
                    'full_name': student.user.full_name,
                    'email': student.user.email,
                    'class_name': class_obj.class_name,
                    'phone': student.user.phone or 'N/A'
                })
    
        else:
        # Lấy tất cả sinh viên từ các khóa học của giáo viên
            teacher_courses = Course.query.filter_by(teacher_id=teacher_id).all()
            for course in teacher_courses:
                registrations = CourseRegistration.query.filter_by(
                course_id=course.id, 
                status='approved'
            ).all()
                for reg in registrations:
                    student = reg.student
                    class_names = ', '.join([cls.class_name for cls in student.classes]) if student.classes else 'N/A'
                
                    students_data.append({
                    'student_id': student.student_id,
                    'full_name': student.user.full_name,
                    'email': student.user.email,
                    'class_name': class_names,
                    'phone': student.user.phone or 'N/A'
                })
    
        return students_data

# API để lấy danh sách sinh viên của khóa học
    @app.route('/api/teacher/courses/<int:course_id>/students')
    @login_required
    @teacher_required
    def api_get_course_students(course_id):
        try:
            teacher_id = current_user.teacher_profile.id
            course = Course.query.filter_by(id=course_id, teacher_id=teacher_id).first()
        
            if not course:
                return jsonify({'success': False, 'message': 'Không tìm thấy khóa học hoặc không có quyền truy cập'}), 403

            class_courses = ClassCourse.query.filter_by(course_id=course_id).all()
            class_ids = [cc.class_id for cc in class_courses]
       
        # Lấy danh sách sinh viên đã đăng ký
            registrations = CourseRegistration.query.filter_by(
                course_id=course_id, 
                status='approved'
            ).options(
                db.joinedload(CourseRegistration.student)
                .joinedload(Student.user),
                db.joinedload(CourseRegistration.student)
                .joinedload(Student.classes)
            ).all()

        
            students_data = []
            for reg in registrations:
                student = reg.student
                score = Score.query.filter_by(
                student_id=student.id, 
                course_id=course_id
            ).first()   

                correct_class_id = None
                correct_class_name = 'N/A'
                for class_obj in student.classes:
                    if class_obj.id in class_ids:
                        correct_class_id = class_obj.id
                        correct_class_name = class_obj.class_name
                        break
                else:
                    if student.classes:
                        correct_class_id = student.classes[0].id
                        correct_class_name = student.classes[0].class_name 


                students_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'full_name': student.user.full_name,
                'email': student.user.email,
                'class_name': correct_class_name,
                'process_score': score.process_score if score else None,
                'exam_score': score.exam_score if score else None,
                'final_score': score.final_score if score else None,
                'grade': score.grade if score else None,
                'status': score.status if score else 'draft',
                'notes': score.notes if score else ''
            })

        
            return jsonify({
            'success': True,
            'course': {
                'id': course.id,
                'course_code': course.course_code,
                'subject_name': course.subject.subject_name if course.subject else 'N/A'
            },
            'students': students_data
        })
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
        
    
    @app.route('/api/teacher/courses/<int:course_id>/classes')
    @login_required
    @teacher_required
    def api_get_course_classes(course_id):
        """API lấy danh sách lớp học của khóa học"""
        try:
            teacher_id = current_user.teacher_profile.id
            course = Course.query.filter_by(id=course_id, teacher_id=teacher_id).first()
        
            if not course:
                return jsonify({'success': False, 'message': 'Không có quyền truy cập'}), 403
        
        # Lấy các lớp có khóa học này
            class_courses = ClassCourse.query.filter_by(course_id=course_id).all()
        
            classes_data = []
            for class_course in class_courses:
                class_obj = class_course.class_
                classes_data.append({
                'id': class_obj.id,
                'class_name': class_obj.class_name,
                'class_code': class_obj.class_code
            })
        
            return jsonify({
            'success': True,
            'course_id': course_id,
            'classes': classes_data
        })
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    @app.route('/api/teacher/classes/<int:class_id>/courses')
    @login_required
    @teacher_required
    def api_get_class_courses(class_id):
        """Lấy danh sách khóa học của lớp mà giáo viên dạy"""
        try:
            teacher_id = current_user.teacher_profile.id
        
        # Tìm lớp và kiểm tra quyền
            class_obj = Class.query.get_or_404(class_id)
        
        # Lấy tất cả khóa học của lớp (không chỉ của giáo viên này)
            courses = []
            for class_course in class_obj.class_courses:
                course = class_course.course
            # Vẫn kiểm tra quyền nhưng hiển thị tất cả
                courses.append({
                'id': course.id,
                'course_code': course.course_code,
                'subject_name': course.subject.subject_name if course.subject else 'N/A',
                'student_count': course.approved_students,
                'teacher_name': course.teacher.user.full_name if course.teacher else 'N/A'
            })
        
            return jsonify({
            'success': True,
            'class_name': class_obj.class_name,
            'courses': courses
        })
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
        
    # API để lấy thông tin chi tiết lớp học
    @app.route('/api/teacher/class/<int:class_id>/details')
    @login_required
    @teacher_required
    def api_get_class_details(class_id):
        """API lấy thông tin chi tiết lớp học"""
        try:
            class_obj = Class.query.get_or_404(class_id)
            teacher_id = current_user.teacher_profile.id
        
        # Kiểm tra giáo viên có dạy lớp này không
            courses = Course.query.filter_by(teacher_id=teacher_id).all()
            class_courses = [cc for course in courses for cc in course.class_courses if cc.class_id == class_id]
        
            if not class_courses:
                return jsonify({'success': False, 'message': 'Không có quyền truy cập'}), 403
        
            class_data = {
            'id': class_obj.id,
            'class_name': class_obj.class_name,
            'class_code': class_obj.class_code,
            'current_students': class_obj.current_students,
            'max_students': class_obj.max_students,
            'course': class_obj.course,
            'faculty': class_obj.faculty,
            'description': class_obj.description,
            'courses': []
        }
        
        # Thêm thông tin khóa học
            for class_course in class_courses:
                course = class_course.course
                class_data['courses'].append({
                'id': course.id,
                'course_code': course.course_code,
                'subject_name': course.subject.subject_name if course.subject else 'N/A',
                'semester': course.semester,
                'status': course.status
            })
        
            return jsonify({
            'success': True,
            'class': class_data
        })
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

# API để lưu điểm
    @app.route('/api/teacher/scores/save', methods=['POST'])
    @login_required
    @teacher_required
    def api_save_scores():
        """API lưu điểm (cho AJAX)"""
        try:
            data = request.get_json()
            course_id = data.get('course_id')
            scores_data = data.get('scores', [])
        
        # Kiểm tra quyền truy cập
            course = Course.query.filter_by(id=course_id, teacher_id=current_user.teacher_profile.id).first()
            if not course:
                return jsonify({'success': False, 'message': 'Không có quyền truy cập'}), 403
        
            result = Score.batch_update_scores(course_id, scores_data)
        
            if result['success']:
                 return jsonify({
                'success': True,
                'message': f'Đã cập nhật điểm cho {result["updated_count"]} sinh viên',
                'updated_count': result['updated_count']
            })
            else:
                return jsonify({'success': False, 'message': result['error']}), 500
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

# API để export điểm
    @app.route('/api/teacher/courses/<int:course_id>/scores/export')
    @login_required
    @teacher_required
    def api_export_scores(course_id):
        """Export điểm ra Excel"""
        try:
            teacher_id = current_user.teacher_profile.id
            course = Course.query.filter_by(id=course_id, teacher_id=teacher_id).first()
        
            if not course:
                flash('Không tìm thấy khóa học', 'error')
                return redirect(url_for('teacher_input_scores'))
        
        # Tạo file Excel
            import pandas as pd
            from io import BytesIO
        
            result = Course.get_course_with_students(course_id, teacher_id)
            students = result['students'] if result else []
        
        # Tạo DataFrame
            data = []
            for student in students:
                data.append({
                'Mã SV': student['student_id'],
                'Họ tên': student['full_name'],
                'Lớp': student['class_name'],
                'Điểm quá trình': student['process_score'] or '',
                'Điểm thi': student['exam_score'] or '',
                'Điểm tổng': student['final_score'] or '',
                'Xếp loại': student['grade'] or '',
                'Ghi chú': student['notes'] or ''
            })
        
            df = pd.DataFrame(data)
        
        # Tạo file trong memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Bảng điểm', index=False)
        
            output.seek(0)
        
            filename = f"bang_diem_{course.course_code}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            flash(f'Lỗi khi export: {str(e)}', 'error')
            return redirect(url_for('teacher_input_scores'))
        
    
    @app.route('/api/teacher/save-personal-comment', methods=['POST'])
    @login_required
    @teacher_required
    def api_save_personal_comment():
        """API lưu nhận xét cá nhân của giáo viên"""
        try:
            data = request.get_json()
            student_id = data.get('student_id')
            comment = data.get('comment')
            include_in_notification = data.get('include_in_notification', False)
            course_name = data.get('course_name')
        
            teacher_id = current_user.teacher_profile.id
        
        # Lưu nhận xét vào database (có thể tạo bảng mới hoặc dùng field notes trong Score)
            student = Student.query.get(student_id)
            if student:
            # Tìm điểm gần nhất của sinh viên với giáo viên này
                score = Score.query.join(Course).filter(
                Score.student_id == student_id,
                Course.teacher_id == teacher_id
            ).order_by(Score.updated_at.desc()).first()
            
                if score:
                # Thêm nhận xét vào ghi chú
                    current_notes = score.notes or ''
                    new_note = f"\n--- NHẬN XÉT CÁ NHÂN ---\n{comment}\nGiáo viên: {current_user.full_name}\nThời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                    score.notes = current_notes + new_note
                    db.session.commit()
        
            return jsonify({
            'success': True,
            'message': 'Đã lưu nhận xét thành công'
        })
        
        except Exception as e:
            logger.error(f"Error saving personal comment: {str(e)}")
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/teacher/send-personal-notification', methods=['POST'])
    @login_required
    @teacher_required
    def api_send_personal_notification():
        """API gửi thông báo cá nhân cho sinh viên"""
        try:
            data = request.get_json()
            student_id = data.get('student_id')
            message = data.get('message')
            course_name = data.get('course_name')
        
            teacher_id = current_user.teacher_profile.id
            student = Student.query.get(student_id)
        
            if not student:
                return jsonify({'success': False, 'message': 'Không tìm thấy sinh viên'}), 404
        
        # Gửi thông báo qua WebSocket
            title = f"💬 Nhận xét từ giảng viên - Môn {course_name}"
            notification_message = f"""
             {message}

            ---   
            Giảng viên: {current_user.full_name}
            Môn học: {course_name}
            Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}
            """

            from notifications.websocket_handler import NotificationManager
            NotificationManager.send_notification(
            student.user_id,
            title,
            notification_message.strip(),
            category='academic',
            priority='normal',
            action_url='/student/scores'
        )
        
            return jsonify({
            'success': True,
            'message': 'Đã gửi thông báo cá nhân cho sinh viên'
        })
        
        except Exception as e:
            logger.error(f"Error sending personal notification: {str(e)}")
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500


    @app.route('/teacher/notifications')
    @login_required
    @teacher_required
    def teacher_notifications():
        """Trang thông báo của giáo viên với tab quản lý điểm kém"""
        try:
        # Lấy thông báo thông thường
            notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
            Notification.created_at.desc()
        ).limit(50).all()
        
        # Format notifications data for template
            notification_data = []
            for notification in notifications:
                notification_data.append({
                'id': notification.id,
                'title': notification.title,
                'message': notification.message,
                'time': notification.created_at.strftime('%d/%m/%Y %H:%M'),
                'read': notification.is_read,
                'priority': notification.priority,
                'category': notification.category,
                'icon': get_notification_icon(notification.category, notification.priority),
                'type': 'success' if notification.priority == 'low' else 'warning' if notification.priority == 'medium' else 'danger',
                'actions': get_notification_actions(notification)
            })
        
            return render_template('teacher/teacher_notifications.html',
                             notifications=notification_data)
                             
        except Exception as e:
            logger.error(f"Error in teacher_notifications: {str(e)}")
            flash('Lỗi khi tải trang thông báo', 'error')
            return redirect(url_for('teacher_dashboard'))

    def get_notification_icon(category, priority):
        """Lấy icon phù hợp cho thông báo"""
        icons = {
        'academic': 'graduation-cap',
        'system': 'cog',
        'deadline': 'clock',
        'teaching': 'chalkboard-teacher',
        'warning': 'exclamation-triangle'
    }
        return icons.get(category, 'bell')

    def get_notification_actions(notification):
        """Lấy danh sách action cho thông báo"""
        actions = []
    
        if notification.category == 'academic' and 'điểm' in notification.title.lower():
            actions.append({
            'text': 'Xem điểm',
            'icon': 'chart-line',
            'type': 'primary',
            'handler': f"viewScores()"
        })
    
        if notification.action_url:
            actions.append({
            'text': 'Xem chi tiết',
            'icon': 'external-link-alt',
            'type': 'info',
            'handler': f"window.open('{notification.action_url}', '_blank')"
        })
    
        return actions
    
    @app.route('/api/teacher/update-low-scores', methods=['POST'])
    @login_required
    @teacher_required
    def api_update_low_scores():
        """API cập nhật danh sách sinh viên điểm kém"""
        try:
            data = request.get_json()
            low_scores = data.get('low_scores', [])
            course_id = data.get('course_id')
        
            teacher_id = current_user.teacher_profile.id
        
        # Kiểm tra quyền truy cập
            course = Course.query.filter_by(id=course_id, teacher_id=teacher_id).first()
            if not course:
                return jsonify({'success': False, 'message': 'Không có quyền truy cập'}), 403
        
        # Ở đây có thể lưu vào database hoặc cache tùy nhu cầu
        # Hiện tại sẽ log lại để debug
            logger.info(f"Teacher {teacher_id} updated low scores for course {course_id}: {len(low_scores)} students")
        
        # GỬI THÔNG BÁO ĐIỂM KÉM TỰ ĐỘNG
            for low_score in low_scores:
                student_id = low_score.get('student_id')
                final_score = low_score.get('final_score')
            
            # Tìm bản ghi điểm chính thức
                score = Score.query.filter_by(
                student_id=student_id, 
                course_id=course_id
            ).first()
            
                if score and final_score < 5.0:
                    from notifications.websocket_handler import trigger_low_score_notifications
                    trigger_low_score_notifications(score)
        
            return jsonify({
            'success': True,
            'message': f'Đã cập nhật {len(low_scores)} sinh viên điểm kém'
        })        
        except Exception as e:
            logger.error(f"Error updating low scores: {str(e)}")
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
    
    # Student Routes
    @app.route('/student/dashboard')
    @login_required
    @student_required
    def student_dashboard():
        current_courses = CourseRegistration.query.filter_by(
            student_id=current_user.student_profile.id,
            status='approved'
        ).all()
        
        stats = {
            'current_courses': len(current_courses),
            'current_gpa': current_user.student_profile.gpa,
            'attendance_rate': 95,  # Would be calculated
            'upcoming_deadlines': 3,  # Would be calculated
            'overall_progress': 75,   # Would be calculated
            'completed_credits': current_user.student_profile.completed_credits,
            'total_credits': current_user.student_profile.total_credits,
            'completed_courses': 15,  # Would be calculated
            'upcoming_courses': 5     # Would be calculated
        }
        
        today_classes = []  # Would be populated
        upcoming_deadlines = []  # Would be populated
        recent_notifications = Notification.query.filter_by(
            user_id=current_user.id
        ).order_by(
            Notification.created_at.desc()
        ).limit(5).all()
        
        return render_template('student/student_dashboard.html',
                             stats=stats,
                             current_courses=current_courses,
                             today_classes=today_classes,
                             upcoming_deadlines=upcoming_deadlines,
                             recent_notifications=recent_notifications)
    
    @app.route('/student/profile')
    @login_required
    @student_required
    def student_profile():
        try:
            student = current_user.student_profile
        
        # Lấy lịch sử học tập từ database - theo học kỳ
            class_info = student.classes[0] if student.classes else None
            
            template_student_data = {
            'student_id': student.student_id,
            'full_name': student.user.full_name,
            'email': student.user.email,
            'phone': student.user.phone or 'Chưa cập nhật',
            'address': student.user.address or 'Chưa cập nhật',
            'birth_date': student.birth_date.strftime('%d/%m/%Y') if student.birth_date else 'Chưa cập nhật',
            'gender': student.gender or 'Chưa cập nhật',
            'course': student.course,
            'gpa': student.gpa or 0.0,
            'completed_credits': student.completed_credits or 0,
            'class_name': class_info.class_name if class_info else 'Chưa phân lớp',
            'faculty': class_info.faculty if class_info else 'Chưa cập nhật',
            'major': 'Công nghệ thông tin',
            'education_level': 'Đại học',
            'training_type': 'Chính quy',
            'attendance_rate': 95,
            'current_courses': CourseRegistration.query.filter_by(
                student_id=student.id, 
                status='approved'
            ).count()
        }
            academic_history = []
            scores = Score.query.filter_by(student_id=student.id).all()
        
        # Nhóm điểm theo học kỳ
            semester_data = {}
            accumulated_credits = 0

            for score in scores:
                if score and score.final_score is not None and score.course and score.course.subject:
                    semester_key = f"HK{score.course.semester}-{score.course.year}"
                    if semester_key not in semester_data:
                        semester_data[semester_key] = {
                        'semester': score.course.semester,
                        'year': score.course.year,
                        'courses': [],
                        'total_credits': 0,
                        'gpa': 0.0,
                        'accumulated_credits': 0
                    }
                
                    course_info = {
                    'course_name': score.course.subject.subject_name,
                    'course_code': score.course.course_code,
                    'credits': score.course.subject.credits,
                    'final_score': score.final_score,
                    'grade': score.grade,
                    'status': 'completed' if score.final_score is not None and score.final_score >= 5.0 else 'failed'
                    }

                
                    semester_data[semester_key]['courses'].append(course_info)
                    semester_data[semester_key]['total_credits'] += score.course.subject.credits

        # Tính GPA cho mỗi học kỳ
            for semester_key, semester in semester_data.items():
                valid_scores = [c for c in semester['courses'] if c['final_score'] is not None and c['credits'] is not None and c['final_score'] >= 0]
                if valid_scores:
                    total_weighted = sum(c['final_score'] * c['credits'] for c in valid_scores)
                    total_credits = sum(c['credits'] for c in valid_scores)
                    if total_credits > 0:
                        semester_gpa = total_weighted / total_credits
                        semester['gpa'] = round(semester_gpa, 2)
                    
                    # Tính xếp loại
                        if semester_gpa >= 3.6:
                            semester['ranking'] = 'Xuất sắc'
                        elif semester_gpa >= 3.2:
                            semester['ranking'] = 'Giỏi'
                        elif semester_gpa >= 2.5:
                            semester['ranking'] = 'Khá'
                        elif semester_gpa >= 2.0:
                            semester['ranking'] = 'Trung bình'
                        else:
                            semester['ranking'] = 'Yếu'
                
                        # Tính tín chỉ tích lũy
                        accumulated_credits += total_credits
                        semester['accumulated_credits'] = accumulated_credits

        
            academic_history = list(semester_data.values())
        
        # Lấy các môn học hiện tại từ database
            current_registrations = CourseRegistration.query.filter_by(
            student_id=student.id,
            status='approved'
        ).options(
            db.joinedload(CourseRegistration.course)
            .joinedload(Course.subject)
        ).all()
        
            current_courses = []
            for reg in current_registrations:
                if reg.course:
                # Lấy điểm nếu có
                    score = Score.query.filter_by(
                    student_id=student.id,
                    course_id=reg.course.id
                ).first()
                    
                    progress_value = 0
                    score_value = None
                    grade_value = 'Chưa có điểm'
        
                    if score:
                        if score.final_score is not None:
                            progress_value = min(score.final_score * 10, 100)
                            score_value = score.final_score
                            grade_value = score.grade or 'Chưa có điểm'
                        else:
                            progress_value = 0
                            score_value = None
                            grade_value = 'Chưa có điểm'

                
                    current_courses.append({
                    'course_code': reg.course.course_code,
                    'course_name': reg.course.subject.subject_name if reg.course.subject else 'N/A',
                    'credits': reg.course.subject.credits if reg.course.subject else 0,
                    'teacher': reg.course.teacher.user.full_name if reg.course.teacher and reg.course.teacher.user else 'N/A',
                    'status': reg.course.status,
                    'score': score_value,
                    'grade': grade_value,
                    'progress': progress_value

                })
        
        # Lấy các môn đã hoàn thành từ database
            completed_scores = Score.query.filter_by(
            student_id=student.id,
            status='published'
        ).filter(Score.final_score.isnot(None)).options(
            db.joinedload(Score.course)
            .joinedload(Course.subject)
        ).all()
        
            completed_courses = []
            for score in completed_scores:
                if score.course and score.final_score is not None:
                    final_score = score.final_score or 0
                    completed_courses.append({
                    'course_code': score.course.course_code,
                    'course_name': score.course.subject.subject_name if score.course.subject else 'N/A',
                    'credits': score.course.subject.credits if score.course.subject else 0,
                    'final_score': final_score,
                    'grade': score.grade,
                    'completion_date': score.updated_at.strftime('%d/%m/%Y') if score.updated_at else 'N/A'
                })
        
        # Lấy kỹ năng từ database
            skills = []
            try:
                student_skills = StudentSkill.query.filter_by(student_id=student.id).all()
                for skill in student_skills:
                    skills.append({
                    'name': skill.skill_name,
                    'level': skill.proficiency_level,
                    'category': skill.category
                })
            except Exception as e:
                logger.warning(f"Could not load skills from database: {e}")
            # Fallback data
                skills = [
                {'name': 'Lập trình Python', 'level': 85, 'category': 'Programming'},
                {'name': 'Cơ sở dữ liệu', 'level': 78, 'category': 'Database'},
                {'name': 'Thuật toán', 'level': 82, 'category': 'Algorithm'}
            ]
        
        # Lấy chứng chỉ từ database
            certificates = []
            try:
                student_certificates = StudentCertificate.query.filter_by(student_id=student.id).all()
                for cert in student_certificates:
                    certificates.append({
                    'name': cert.certificate_name,
                    'organization': cert.organization,
                    'date': cert.issue_date.strftime('%d/%m/%Y') if cert.issue_date else 'N/A',
                    'expiry_date': cert.expiry_date.strftime('%d/%m/%Y') if cert.expiry_date else None,
                    'url': cert.certificate_url
                })
            except Exception as e:
                logger.warning(f"Could not load certificates from database: {e}")
            # Fallback data
                certificates = [
                {'name': 'Chứng chỉ Python cơ bản', 'organization': 'Học viện CNTT', 'date': '2023-06-15'},
                {'name': 'Giải nhì Olympic Tin học', 'organization': 'Bộ GD&ĐT', 'date': '2023-12-20'}
            ]
        
        # Tài liệu học tập
            documents = [
            {'name': 'Bảng điểm', 'icon': 'file-pdf', 'color': 'danger', 'description': 'Bảng điểm học tập', 'url': url_for('student_scores')},
            {'name': 'Kế hoạch học tập', 'icon': 'file-alt', 'color': 'primary', 'description': 'Kế hoạch học tập cá nhân', 'url': '#'},
            {'name': 'Giấy chứng nhận', 'icon': 'file-certificate', 'color': 'success', 'description': 'Các chứng chỉ đạt được', 'url': '#'}
        ]
        
        # Thống kê
            stats = {
            'total_credits': student.completed_credits or 0,
            'current_gpa': student.gpa or 0.0,
            'completed_courses': len([s for s in scores if s.final_score is not None and s.final_score >= 5.0]),
            'current_courses': len(current_courses),
            'total_semesters': len(academic_history),
            'attendance_rate': 95  # Giá trị mặc định
        }
        
        # Thông tin lớp học cho template
            template_student_data = {
            'student_id': student.student_id,
            'full_name': student.user.full_name,
            'email': student.user.email,
            'phone': student.user.phone,
            'address': student.user.address,
            'birth_date': student.birth_date.strftime('%d/%m/%Y') if student.birth_date else None,
            'gender': student.gender,
            'course': student.course,
            'gpa': student.gpa or 0.0,
            'completed_credits': student.completed_credits or 0,
            'class_name': class_info.class_name if class_info else 'Chưa phân lớp',
            'faculty': class_info.faculty if class_info else 'Chưa cập nhật',
            'major': 'Công nghệ thông tin',  # Giá trị mặc định
            'education_level': 'Đại học',    # Giá trị mặc định
            'training_type': 'Chính quy',    # Giá trị mặc định
            'attendance_rate': 95,           # Giá trị mặc định
            'current_courses': len(current_courses)
        }
        
            return render_template('student/student_profile.html',
                             student=template_student_data,
                             academic_history=academic_history,
                             current_courses=current_courses,
                             completed_courses=completed_courses,
                             skills=skills,
                             certificates=certificates,
                             documents=documents,
                             stats=stats)
    
        except Exception as e:
            logger.error(f"Error in student_profile: {str(e)}")
            flash('Lỗi khi tải trang hồ sơ', 'error')
            return redirect(url_for('student_dashboard'))
        
    
    @app.route('/debug/student')
    @login_required
    def debug_student():
        student = current_user.student_profile
        return jsonify({
        'student_id': student.student_id,
        'birth_date': str(student.birth_date) if student.birth_date else None,
        'gender': student.gender,
        'phone': student.user.phone,
        'address': student.user.address,
        'completed_credits': student.completed_credits,
        'gpa': student.gpa,
        'classes': [{'class_name': c.class_name, 'faculty': c.faculty} for c in student.classes]
    })

    @app.route('/student/profile/update', methods=['POST'])
    @login_required
    @student_required
    def update_student_profile():
        try:
            student = current_user.student_profile
            data = request.get_json()
        
        # Cập nhật thông tin user
            if 'phone' in data:
                student.user.phone = data['phone']
            if 'address' in data:
                student.user.address = data['address']
            if 'full_name' in data:
                student.user.full_name = data['full_name']
        
        # Cập nhật thông tin student
            if 'birth_date' in data and data['birth_date']:
                student.birth_date = datetime.strptime(data['birth_date'], '%Y-%m-%d').date()
            if 'gender' in data:
                student.gender = data['gender']
        
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': 'Cập nhật thông tin thành công!'
        })
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating student profile: {str(e)}")
            return jsonify({
            'success': False,
            'message': 'Lỗi khi cập nhật thông tin'
        }), 500

    
    @app.route('/student/timetable')
    @login_required
    @student_required
    def student_timetable():
        try:
        # Get week parameter from request, default to current week
            week = request.args.get('week', type=int, default=1)
        
        # Get registered courses
            registrations = CourseRegistration.query.filter_by(
            student_id=current_user.student_profile.id,
            status='approved'
        ).all()
        
            courses = [reg.course for reg in registrations if reg.course]
        
        # Generate timetable data from actual courses
            timetable = []
            for course in courses:
                if course.schedule:
                # Parse schedule data (assuming format: "Thứ 2 - Tiết 1-3" or similar)
                    schedule_parts = course.schedule.split(' - ')
                    if len(schedule_parts) >= 2:
                        day_part = schedule_parts[0].lower()
                        session_part = schedule_parts[1].lower()
                    
                    # Map day names to day codes
                        day_mapping = {
                        'thứ 2': 'mon', 'thứ hai': 'mon',
                        'thứ 3': 'tue', 'thứ ba': 'tue', 
                        'thứ 4': 'wed', 'thứ tư': 'wed',
                        'thứ 5': 'thu', 'thứ năm': 'thu',
                        'thứ 6': 'fri', 'thứ sáu': 'fri',
                        'thứ 7': 'sat', 'thứ bảy': 'sat'
                    }
                    
                    # Extract day
                        day_code = None
                        for day_name, code in day_mapping.items():
                            if day_name in day_part:
                                day_code = code
                                break
                    
                    # Extract sessions
                        sessions = []
                        if 'tiết' in session_part:
                            session_text = session_part.split('tiết')[1].strip()
                            if '-' in session_text:
                                start_end = session_text.split('-')
                                if len(start_end) == 2:
                                    start_session = int(start_end[0])
                                    end_session = int(start_end[1])
                                    sessions = list(range(start_session, end_session + 1))
                            else:
                                sessions = [int(session_text)]
                    
                    # Create timetable entries for each session
                        for session in sessions:
                        # Determine class type based on course info
                            class_type = 'theory'  # default
                            if course.room and 'lab' in course.room.lower():
                                class_type = 'lab'
                            elif course.room and 'thực hành' in course.room.lower():
                                class_type = 'practice'
                            elif 'thực hành' in course.schedule.lower():
                                class_type = 'practice'
                        
                            timetable.append({
                            'id': course.id,
                            'course_code': course.course_code,
                            'course_name': course.subject.subject_name if course.subject else 'N/A',
                            'day': day_code,
                            'day_name': day_part.title(),
                            'session': session,
                            'room': course.room or 'Chưa có phòng',
                            'teacher': course.teacher.user.full_name if course.teacher and course.teacher.user else 'N/A',
                            'type': class_type,
                            'time': get_time_from_session(session),
                            'week': week,
                            'is_current': check_if_current_class(day_code, session)
                        })
        
        # Complete time slots
            time_slots = [
            {'session': 1, 'time': '07:00-07:50'},
            {'session': 2, 'time': '07:50-08:40'},
            {'session': 3, 'time': '08:40-09:30'},
            {'session': 4, 'time': '09:30-10:20'},
            {'session': 5, 'time': '10:30-11:20'},
            {'session': 6, 'time': '11:20-12:10'},
            {'session': 7, 'time': '12:30-13:20'},
            {'session': 8, 'time': '13:20-14:10'},
            {'session': 9, 'time': '14:20-15:10'},
            {'session': 10, 'time': '15:10-16:00'},
            {'session': 11, 'time': '16:10-17:00'},
            {'session': 12, 'time': '17:00-17:50'}
        ]
        
        # Calculate current week dates based on academic year
            current_week = calculate_week_dates(week)
        
            stats = {
            'total_classes': len(timetable),
            'credit_hours': sum(c.subject.credits for c in courses if c and c.subject) * 15,
            'theory_classes': len([c for c in courses if c.schedule and 'lý thuyết' in c.schedule.lower()]),
            'practice_classes': len([c for c in courses if c.schedule and 'thực hành' in c.schedule.lower()])
        }
        
            ranking_percentage = 85
        
            return render_template('student/student_timetable.html',
                             timetable=timetable,
                             time_slots=time_slots,
                             current_week=current_week,
                             stats=stats,
                             ranking_percentage=ranking_percentage)
                             
        except Exception as e:
            logger.error(f"Error in student_timetable: {str(e)}")
            flash('Lỗi khi tải thời khóa biểu', 'error')
            return redirect(url_for('student_dashboard'))

# Helper functions
    def get_time_from_session(session):
        """Get time range from session number"""
        time_slots = {
        1: '07:00-07:50', 2: '07:50-08:40', 3: '08:40-09:30',
        4: '09:30-10:20', 5: '10:30-11:20', 6: '11:20-12:10',
        7: '12:30-13:20', 8: '13:20-14:10', 9: '14:20-15:10',
        10: '15:10-16:00', 11: '16:10-17:00', 12: '17:00-17:50'
    }
        return time_slots.get(session, 'N/A')

    def calculate_week_dates(week_number):
        """Calculate start and end dates for a given week number"""
    # Assuming academic year starts on September 1st
        from datetime import datetime, timedelta
    
        academic_year_start = datetime(2025, 11, 13)  # Adjust based on actual academic year
        week_start = academic_year_start + timedelta(weeks=week_number-1)
        week_end = week_start + timedelta(days=6)
    
        return {
        'week': week_number,
        'start_date': week_start.strftime('%d/%m/%Y'),
        'end_date': week_end.strftime('%d/%m/%Y'),
        'start_date_iso': week_start.strftime('%Y-%m-%d'),
        'end_date_iso': week_end.strftime('%Y-%m-%d')
    }

    def check_if_current_class(day_code, session):
        """Check if this class is happening right now"""
        from datetime import datetime
    
    # Map day codes to numbers (Monday=0, Sunday=6)
        day_mapping = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5}
    
        current_time = datetime.now()
        current_day = current_time.weekday()  # Monday=0, Sunday=6
        current_hour = current_time.hour
        current_minute = current_time.minute
    
    # Check if same day
        if day_code in day_mapping and day_mapping[day_code] == current_day:
        # Check if current time matches session time
            session_times = {
            1: (7, 0, 7, 50), 2: (7, 50, 8, 40), 3: (8, 40, 9, 30),
            4: (9, 30, 10, 20), 5: (10, 30, 11, 20), 6: (11, 20, 12, 10),
            7: (12, 30, 13, 20), 8: (13, 20, 14, 10), 9: (14, 20, 15, 10),
            10: (15, 10, 16, 0), 11: (16, 10, 17, 0), 12: (17, 0, 17, 50)
        }
        
            if session in session_times:
                start_h, start_m, end_h, end_m = session_times[session]
                current_total_minutes = current_hour * 60 + current_minute
                start_total_minutes = start_h * 60 + start_m
                end_total_minutes = end_h * 60 + end_m
            
                if start_total_minutes <= current_total_minutes <= end_total_minutes:
                    return True
    
        return False
    
    @app.route('/student/scores')
    @login_required 
    @student_required
    def student_scores():
        try:
            student_id = current_user.student_profile.id
            scores = Score.query.filter_by(student_id=student_id).all()

            student_profile = current_user.student_profile
            current_gpa = student_profile.gpa if student_profile.gpa else 0.0
    
        # ✅ SỬA: Group by semester với logic thống nhất
            semesters = {}
            for score in scores:
                if score and score.course and score.course.subject:
                    key = f"{score.course.semester}-{score.course.year}"
                    if key not in semesters:
                        semesters[key] = {
                        'semester': score.course.semester,
                        'year': score.course.year,
                        'courses': [],
                        'gpa': 0.0,
                        'total_credits': 0,
                        'weighted_sum': 0.0
                    }

            
                # ✅ SỬA: Tính điểm theo hệ số tín chỉ
                    credits = score.course.subject.credits if score.course.subject else 0
                    final_score = score.final_score if score.final_score else 0
                
                    course_data = {
                    'course_name': score.course.subject.subject_name,
                    'course_code': score.course.course_code,
                    'credits': credits,
                    'teacher': score.course.teacher.user.full_name if score.course.teacher and score.course.teacher.user else 'N/A',
                    'process_score': score.process_score,
                    'exam_score': score.exam_score,
                    'final_score': final_score,
                    'grade': score.grade
                }
                
                    semesters[key]['courses'].append(course_data)
                
                # ✅ SỬA: Tính GPA có trọng số tín chỉ
                    if final_score and credits > 0:
                        semesters[key]['total_credits'] += credits
                        semesters[key]['weighted_sum'] += final_score * credits

        # ✅ SỬA: Tính GPA cho mỗi học kỳ
            for semester in semesters.values():
                if semester['total_credits'] > 0:
                    semester['gpa'] = round(semester['weighted_sum'] / semester['total_credits'], 2)

        # ✅ SỬA: Lấy thông tin từ student profile
            student_profile = current_user.student_profile
            current_gpa = student_profile.gpa if student_profile.gpa else 0.0
        
        # Tính toán các số liệu thống kê
            completed_courses = len([s for s in scores if s.final_score and s.final_score >= 5.0])
            total_courses = len(scores)
            completion_rate = (completed_courses / total_courses * 100) if total_courses > 0 else 0

            current_courses = CourseRegistration.query.filter_by(
            student_id=student_id,
            status='approved'
            ).count()

        
        # Xác định academic rank dựa trên GPA
            if current_gpa >= 3.6:
                academic_rank = "Xuất sắc"
            elif current_gpa >= 3.2:
                academic_rank = "Giỏi"
            elif current_gpa >= 2.5:
                academic_rank = "Khá"
            elif current_gpa >= 2.0:
                academic_rank = "Trung bình"
            else:
                academic_rank = "Yếu"

            ranking_percentage = min(100, max(0, (current_gpa / 4.0) * 100))

            return render_template('student/student_scores.html',
                     scores=scores,
                     semesters=list(semesters.values()),
                     current_gpa=current_gpa,
                     total_credits=student_profile.total_credits or 0,
                     completed_credits=student_profile.completed_credits or 0,
                     completed_courses=completed_courses,
                     passed_courses=completed_courses,
                     total_courses=total_courses,
                     current_courses=current_courses,
                     completion_rate=completion_rate,
                     academic_rank=academic_rank,
                     ranking_percentage=ranking_percentage)


        except Exception as e:
            logger.error(f"Error in student_scores: {str(e)}")
            return render_template('student/student_scores.html',
                     scores=[],
                     semesters=[],
                     current_gpa=0.0,
                     ranking_percentage=0,
                     error_message="Có lỗi xảy ra khi tải dữ liệu điểm số")
        
    # Student Export Routes
    @app.route('/student/export-scores-excel')
    @login_required
    @student_required
    def export_student_scores_excel():
        """Export bảng điểm sinh viên ra Excel"""
        try:
            student_id = current_user.student_profile.id
            student = current_user.student_profile
        
        # Lấy dữ liệu điểm số
            scores = Score.query.filter_by(student_id=student_id).all()
        
        # Tạo DataFrame
            data = []
            for score in scores:
                if score and score.course and score.course.subject:
                    data.append({
                    'Mã môn': score.course.course_code,
                    'Tên môn': score.course.subject.subject_name,
                    'Số tín chỉ': score.course.subject.credits,
                    'Điểm quá trình': score.process_score or '',
                    'Điểm thi': score.exam_score or '',
                    'Điểm tổng': score.final_score or '',
                    'Xếp loại': score.grade or 'Chưa có',
                    'Học kỳ': f"HK{score.course.semester}",
                    'Năm học': score.course.year,
                    'Trạng thái': 'Đạt' if score.final_score and score.final_score >= 5.0 else 'Chưa đạt'
                })
        
            df = pd.DataFrame(data)
        
        # Tạo file Excel
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet điểm chi tiết
                df.to_excel(writer, sheet_name='Bảng điểm chi tiết', index=False)
            
            # Sheet thống kê
                stats_data = {
                'Họ tên': [student.user.full_name],
                'Mã SV': [student.student_id],
                'Lớp': [student.classes[0].class_name if student.classes else 'N/A'],
                'Khóa': [student.course],
                'GPA hiện tại': [student.gpa or 0.0],
                'Tín chỉ tích lũy': [student.completed_credits or 0],
                'Tổng số môn': [len(scores)],
                'Môn đã hoàn thành': [len([s for s in scores if s.final_score and s.final_score >= 5.0])],
                'Ngày xuất': [datetime.now().strftime('%d/%m/%Y %H:%M')]
            }
                stats_df = pd.DataFrame(stats_data)
                stats_df.to_excel(writer, sheet_name='Thông tin sinh viên', index=False)
        
            output.seek(0)
        
            filename = f"bang_diem_{student.student_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
            return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
        except Exception as e:
            logger.error(f"Error exporting student scores Excel: {str(e)}")
            flash(f'Lỗi khi export Excel: {str(e)}', 'error')
            return redirect(url_for('student_scores'))

    @app.route('/student/export-scores-pdf')
    @login_required
    @student_required
    def export_student_scores_pdf():
        """Export bảng điểm sinh viên ra PDF"""
        try:
            register_vietnamese_fonts()
        
            student_id = current_user.student_profile.id
            student = current_user.student_profile
        
        # Lấy dữ liệu điểm số
            scores = Score.query.filter_by(student_id=student_id).all()
        
        # Tạo PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30,encoding = 'utf-8')
            elements = []
        
        # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,
            textColor=colors.HexColor('#2c3e50')
        )
        
        # Tiêu đề
            title = Paragraph("BẢNG ĐIỂM HỌC TẬP", title_style)
            elements.append(title)
        
        # Thông tin sinh viên
            info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.gray,
            alignment=0
        )
        
            class_name = student.classes[0].class_name if student.classes else 'N/A'
            student_info = [
            f"Họ tên: {student.user.full_name}",
            f"Mã SV: {student.student_id}",
            f"Lớp: {class_name}",
            f"Khóa: {student.course}",
            f"GPA: {student.gpa or 0.0}",
            f"Tín chỉ tích lũy: {student.completed_credits or 0}",
            f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ]
        
            for info in student_info:
                elements.append(Paragraph(info, info_style))
        
            elements.append(Spacer(1, 20))
        
        # Dữ liệu bảng điểm
            data = [['STT', 'Mã môn', 'Tên môn', 'TC', 'Điểm QT', 'Điểm thi', 'Điểm TK', 'Xếp loại', 'HK', 'Năm học']]
        
            for i, score in enumerate(scores, 1):
                if score and score.course and score.course.subject:
                    data.append([
                    str(i),
                    score.course.course_code,
                    score.course.subject.subject_name,
                    str(score.course.subject.credits),
                    f"{score.process_score:.1f}" if score.process_score else '',
                    f"{score.exam_score:.1f}" if score.exam_score else '',
                    f"{score.final_score:.1f}" if score.final_score else '',
                    score.grade or 'N/A',
                    f"HK{score.course.semester}",
                    score.course.year
                ])
        
        # Tạo bảng
            if len(data) > 1:  # Có dữ liệu
                table = Table(data, colWidths=[30, 60, 120, 30, 50, 50, 50, 50, 30, 60])
                table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
                elements.append(table)
            else:
                elements.append(Paragraph("Chưa có dữ liệu điểm số", info_style))
        
        # Thống kê
            elements.append(Spacer(1, 20))
            completed_courses = len([s for s in scores if s.final_score and s.final_score >= 5.0])
            stats_text = f"Tổng số môn: {len(scores)} | Môn đã hoàn thành: {completed_courses} | Tỷ lệ hoàn thành: {(completed_courses/len(scores)*100 if scores else 0):.1f}%"
            elements.append(Paragraph(stats_text, info_style))
        
        # Tạo PDF
            doc.build(elements)
            buffer.seek(0)
        
        # Trả về file PDF
            response = make_response(buffer.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename=bang_diem_{student.student_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'
        
            return response
        
        except Exception as e:
            logger.error(f"Error exporting student scores PDF: {str(e)}")
            return jsonify({'success': False, 'message': f'Lỗi khi xuất PDF: {str(e)}'}), 500
        
    @app.route('/admin/sync-system', methods=['POST'])
    @login_required
    @admin_required
    def sync_system():
        """Đồng bộ toàn bộ dữ liệu hệ thống"""
        try:
            from models import sync_system_data
            if sync_system_data():
                
                flash('Đồng bộ hệ thống thành công!', 'success')
            else:
                flash('Lỗi khi đồng bộ hệ thống', 'error')
        except Exception as e:
            flash(f'Lỗi: {str(e)}', 'error')
    
        return redirect(url_for('admin_dashboard'))
    # API để lấy danh sách sinh viên của lớp
    @app.route('/api/class/<int:class_id>/students')
    @login_required
    @admin_required
    def api_get_class_students(class_id):
        try:
            class_obj = Class.query.get_or_404(class_id)
            students = Student.query.filter(Student.classes.any(id=class_id)).all()
        
            student_data = []
            for student in students:
                student_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'full_name': student.user.full_name,
                'email': student.user.email,
                'gpa': student.gpa,
                'status': student.status
            })
        
            return jsonify({
            'success': True,
            'class_name': class_obj.class_name,
            'students': student_data
        })
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500
    
    @app.route('/api/class/<int:class_id>/students/<int:student_id>', methods=['DELETE'])
    @login_required
    @admin_required
    def api_remove_student_from_class(class_id, student_id):
        try:
            student = Student.query.get_or_404(student_id)
            class_obj = Class.query.get_or_404(class_id)
        
            if class_obj not in student.classes:
                return jsonify({
                'success': False,
                'message': 'Sinh viên không thuộc lớp này'
            }), 400
        
        # Cập nhật class_id về None
            student.classes.remove(class_obj)
        
        # Cập nhật số lượng sinh viên trong lớp - SỬA CÁCH NÀY
            if class_obj.current_students > 0:
                class_obj.current_students -= 1
        
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã xóa sinh viên {student.user.full_name} khỏi lớp'
        })
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    
    @app.route('/api/class/<int:class_id>/info')
    @login_required
    @admin_required
    def api_get_class_info(class_id):
        """API lấy thông tin lớp học"""
        try:
            class_obj = Class.query.get_or_404(class_id)
        
            return jsonify({
            'success': True,
            'class_name': class_obj.class_name,
            'class_code': class_obj.class_code,
            'current_students': class_obj.current_students,
            'max_students': class_obj.max_students
        })
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/class/<int:class_id>/add-students', methods=['POST'])
    @login_required
    @admin_required 
    def api_add_students_to_class(class_id):
        """API thêm sinh viên vào lớp"""
        try:
            data = request.get_json()
            student_ids = data.get('student_ids', [])
        
            class_obj = Class.query.get_or_404(class_id)
        
        # Kiểm tra số lượng sinh viên
            if class_obj.current_students + len(student_ids) > class_obj.max_students:
                return jsonify({
                'success': False,
                'message': f'Vượt quá số lượng tối đa. Chỉ còn {class_obj.max_students - class_obj.current_students} chỗ trống'
            }), 400
        
            added_count = 0
            for student_id in student_ids:
                student = Student.query.get(student_id)
                if student and class_obj not in student.classes:
                    student.classes.append(class_obj)
                    added_count += 1
        
        # Cập nhật số lượng sinh viên
            class_obj.current_students += added_count
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã thêm {added_count} sinh viên vào lớp',
            'added_count': added_count
        })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

# API để lấy danh sách sinh viên chưa có lớp - SỬA LẠI
    @app.route('/api/students/available')
    @login_required
    @admin_required
    def api_get_available_students():
        try:
        # Lấy sinh viên chưa có lớp
            students = Student.query.all()
        
            student_data = []
            for student in students:
                current_classes = [cls.class_name for cls in student.classes] if hasattr(student, 'classes') else []
                student_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'full_name': student.user.full_name,
                'email': student.user.email,
                'current_classes': current_classes,  # Danh sách các lớp đang học
                'class_count': len(current_classes)
            })

        
            return jsonify({
            'success': True,
            'students': student_data
        })
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500


    def check_prerequisites(student_id, course_id):
        """Kiểm tra điều kiện tiên quyết"""
        course = Course.query.get(course_id)
        if not course or not course.subject or not course.subject.prerequisites:
            return True, []
    
    # Lấy danh sách môn học đã hoàn thành
        completed_scores = Score.query.filter_by(
        student_id=student_id,
        status='published'
    ).filter(Score.final_score.isnot(None)).filter(Score.final_score >= 5.0).all()
    
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

    @app.route('/admin/courses/delete/<int:course_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_course(course_id):
        try:
            course = Course.query.get_or_404(course_id)
            course_name = course.course_code
            db.session.delete(course)
            db.session.commit()
            return jsonify({'success': True, 'message': f'Đã xóa khóa học {course_name}'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'}), 500

    @app.route('/admin/courses/edit/<int:course_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_course(course_id):
        if request.method == 'GET':
            course = Course.query.get_or_404(course_id)
            return jsonify({
            'id': course.id,
            'course_code': course.course_code,
            'subject_id': course.subject_id,
            'teacher_id': course.teacher_id,
            'semester': course.semester,
            'year': course.year,
            'max_students': course.max_students,
            'room': course.room,
            'status': course.status,
            'start_date': course.start_date.isoformat() if course.start_date else '',
            'end_date': course.end_date.isoformat() if course.end_date else ''
        })
        else:
        # Xử lý cập nhật
           pass

    
    @app.route('/api/admin/courses/<int:course_id>/students')  
    @login_required
    @admin_required
    def api_get_admin_course_students(course_id):
        """API lấy danh sách sinh viên của khóa học"""
        try:
            course = Course.query.get_or_404(course_id)
        
        # Lấy danh sách sinh viên đã đăng ký khóa học này
            registrations = CourseRegistration.query.filter_by(
            course_id=course_id
        ).options(
            db.joinedload(CourseRegistration.student)
                .joinedload(Student.user),
            db.joinedload(CourseRegistration.student)
                .joinedload(Student.classes)
        ).all()
        
            students_data = []
            for reg in registrations:
                student = reg.student
                students_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'full_name': student.user.full_name,
                'email': student.user.email,
                'class_names': [cls.class_name for cls in student.classes],
                'registration_status': reg.status,
                'registration_id': reg.id
            })
        
            return jsonify({
            'success': True,
            'course': {
                'id': course.id,
                'course_code': course.course_code,
                'subject_name': course.subject.subject_name if course.subject else 'N/A',
                'max_students': course.max_students,
                'current_students': course.current_students
            },
            'students': students_data
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/admin/courses/<int:course_id>/add-students', methods=['POST'])
    @login_required
    @admin_required
    def api_add_students_to_course_admin(course_id):
        """API thêm sinh viên vào khóa học"""
        try:
            data = request.get_json()
            student_ids = data.get('student_ids', [])
        
            course = Course.query.get_or_404(course_id)
        
        # Kiểm tra số lượng sinh viên
            if course.current_students + len(student_ids) > course.max_students:
                return jsonify({
                'success': False,
                'message': f'Vượt quá số lượng tối đa. Chỉ còn {course.max_students - course.current_students} chỗ trống'
            }), 400
        
            added_count = 0
            for student_id in student_ids:
                student = Student.query.get(student_id)
                if student:
                # Kiểm tra xem sinh viên đã đăng ký chưa
                    existing_reg = CourseRegistration.query.filter_by(
                    course_id=course_id,
                    student_id=student.id
                ).first()
                
                    if not existing_reg:
                     # Thêm đăng ký mới
                        registration = CourseRegistration(
                        student_id=student.id,
                        course_id=course_id,
                        status='approved',  # Tự động duyệt khi admin thêm
                        registration_date=datetime.utcnow()
                    )
                        db.session.add(registration)
                        added_count += 1
        
        # Cập nhật số lượng sinh viên
            if added_count > 0:
                course.current_students += added_count
                course.update_registration_counts()
        
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã thêm {added_count} sinh viên vào khóa học',
            'added_count': added_count
        })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/admin/courses/<int:course_id>/remove-student/<int:student_id>', methods=['DELETE'])
    @login_required
    @admin_required
    def api_remove_student_from_course_admin(course_id, student_id):
        """API xóa sinh viên khỏi khóa học"""
        try:
            course = Course.query.get_or_404(course_id)
            student = Student.query.get_or_404(student_id)
        
        # Tìm đăng ký
            registration = CourseRegistration.query.filter_by(
            course_id=course_id,
            student_id=student_id
        ).first()
        
            if not registration:
                return jsonify({
                'success': False,
                'message': 'Sinh viên không có trong khóa học này'
            }), 400
        
        # Xóa đăng ký
            db.session.delete(registration)
        
        # Cập nhật số lượng
            if course.current_students > 0:
                course.current_students -= 1
                course.update_registration_counts()
        
            db.session.commit()
        
            return jsonify({
            'success': True,
            'message': f'Đã xóa sinh viên {student.user.full_name} khỏi khóa học'
        })
        
        except Exception as e:
            db.session.rollback()
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

# Cập nhật route thêm lớp để xử lý sinh viên - SỬA LẠI
    @app.route('/admin/classes/add', methods=['POST'])
    @login_required
    @admin_required
    def add_class():
        if request.method == 'POST':
            try:
                validate_csrf(request.form.get('csrf_token'))
            except BadRequest:
                flash('CSRF token không hợp lệ.', 'error')
                return redirect(url_for('manage_classes'))
        
            try:
            # Lấy dữ liệu cơ bản
                class_name = request.form.get('class_name')
                teacher_id = request.form.get('teacher_id')
                class_code = request.form.get('class_code')
                course = request.form.get('course')
                faculty = request.form.get('faculty')
                max_students = request.form.get('max_students')
                description = request.form.get('description')
                student_ids = request.form.getlist('student_ids')  # Lấy danh sách sinh viên
            
            # Validation
                if not class_name or not class_code:
                    flash('Vui lòng điền đầy đủ các trường bắt buộc: Tên lớp và Mã lớp.', 'error')
                    return redirect(url_for('manage_classes'))
            
                existing_class = Class.query.filter_by(class_code=class_code).first()
                if existing_class:
                    flash('Mã lớp đã tồn tại.', 'error')
                    return redirect(url_for('manage_classes'))
            
            # Tạo lớp mới
                new_class = Class(
                class_name=class_name,
                class_code=class_code,
                course=course,
                faculty=faculty,
                teacher_id=teacher_id if teacher_id else None,
                max_students=int(max_students) if max_students else 50,
                description=description,
                current_students=0,
                status='active'
            )
            
                db.session.add(new_class)
                db.session.flush()  # Lấy ID của lớp mới
            
            # Thêm sinh viên vào lớp nếu có
                if student_ids:
                    students = Student.query.filter(Student.id.in_(student_ids)).all()
                    for student in students:
                        if new_class not in student.classes:
                            student.classes.append(new_class)
                
                    new_class.current_students = len(students)
            
                db.session.commit()
                flash(f'Đã thêm lớp "{class_name}" thành công với {new_class.current_students} sinh viên.', 'success')
            
            except Exception as e:
                db.session.rollback()
                flash(f'Lỗi khi thêm lớp: {str(e)}', 'error')
        
            return redirect(url_for('manage_classes'))

    @app.route('/student/notifications')
    @login_required
    @student_required
    def student_notifications():
        notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
            Notification.created_at.desc()
        ).all()
        
        stats = {
            'unread_count': len([n for n in notifications if not n.is_read]),
            'academic_count': len([n for n in notifications if n.category == 'academic']),
            'deadline_count': len([n for n in notifications if n.category == 'deadline']),
            'system_count': len([n for n in notifications if n.category == 'system'])
        }
        
        return render_template('student/student_notifications.html',
                             notifications=notifications,
                             stats=stats)
    
    


    @app.route('/api/sync/system', methods=['POST'])
    @login_required
    @admin_required
    def api_sync_system():
        """API đồng bộ toàn bộ hệ thống"""
        try:
            from models import sync_complete_system
            if sync_complete_system():
                return jsonify({
                'success': True,
                'message': 'Đồng bộ hệ thống thành công!'
            })
            else:
                return jsonify({
                'success': False,
                'message': 'Lỗi khi đồng bộ hệ thống'
            }), 500
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/sync/check-prerequisites/<int:course_id>/<int:student_id>')
    @login_required
    def api_check_prerequisites(course_id, student_id):
        """Kiểm tra điều kiện tiên quyết của sinh viên cho khóa học"""
        try:
            course = Course.query.get_or_404(course_id)
            student = Student.query.get_or_404(student_id)
        
            if not course.subject or not course.subject.prerequisites:
                return jsonify({
                'can_register': True,
                'missing_prerequisites': []
            })
        
        # Lấy danh sách môn học đã hoàn thành của sinh viên
            completed_courses = Score.query.filter_by(
                student_id=student_id,
            status='published'
        ).filter(Score.final_score >= 5.0).all()
        
            completed_subject_ids = [score.course.subject_id for score in completed_courses if score.course]
        
        # Kiểm tra prerequisites
            import json
            try:
                required_prereq_ids = json.loads(course.subject.prerequisites)
                missing_prereqs = []
            
                for prereq_id in required_prereq_ids:
                    prereq_subject = Subject.query.get(prereq_id)
                    if prereq_subject and prereq_id not in completed_subject_ids:
                        missing_prereqs.append(prereq_subject.subject_name)
            
                return jsonify({
                'can_register': len(missing_prereqs) == 0,
                'missing_prerequisites': missing_prereqs
            })
            
            except Exception as e:
                return jsonify({
                'can_register': True,
                'missing_prerequisites': []
            })
            
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi khi kiểm tra điều kiện: {str(e)}'
        }), 500

    @app.route('/api/sync/teacher-available-subjects/<int:teacher_id>')
    @login_required
    def api_teacher_available_subjects(teacher_id):
        """Lấy danh sách môn học giáo viên có thể dạy (theo department)"""
        try:
            teacher = Teacher.query.get_or_404(teacher_id)
        
        # Lấy môn học cùng department với giáo viên
            available_subjects = Subject.query.filter_by(department=teacher.department).all()
        
            subject_data = []
            for subject in available_subjects:
                subject_data.append({
                'id': subject.id,
                'subject_code': subject.subject_code,
                'subject_name': subject.subject_name,
                'credits': subject.credits,
                'is_assigned': subject in teacher.assigned_subjects
            })
        
            return jsonify({
            'success': True,
            'available_subjects': subject_data
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    @app.route('/api/sync/class-courses/<int:class_id>')
    @login_required
    def api_get_sync_class_courses(class_id):
        """Lấy danh sách khóa học của lớp"""
        try:
            class_obj = Class.query.get_or_404(class_id)
        
            class_courses_data = []
            for class_course in class_obj.class_courses:
                course = class_course.course
                class_courses_data.append({
                'id': course.id,
                'course_code': course.course_code,
                'subject_name': course.subject.subject_name if course.subject else 'N/A',
                'teacher_name': course.teacher.user.full_name if course.teacher else 'N/A',
                'semester': class_course.semester,
                'status': course.status,
                'registered_students': course.registered_students,
                'max_students': course.max_students
            })
        
            return jsonify({
            'success': True,
            'class_name': class_obj.class_name,
            'courses': class_courses_data
        })
        
        except Exception as e:
            return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}'
        }), 500

    
    # Utility functions
    def calculate_grade(score):
        """Calculate grade from score"""
        if score is None:
            return 'N/A'  # hoặc 'Chưa có điểm'
        if score >= 8.5:
            return 'A'
        elif score >= 8.0:
            return 'B+'
        elif score >= 7.0:
            return 'B'
        elif score >= 6.5:
            return 'C+'
        elif score >= 5.5:
            return 'C'
        elif score >= 5.0:
            return 'D+'
        elif score >= 4.0:
            return 'D'
        else:
            return 'F'
    
    # API Routes for AJAX calls
    @app.route('/api/notifications/mark-read', methods=['POST'])
    @login_required
    def api_mark_notification_read():
        notification_id = request.json.get('notification_id')
        # Mark as read logic
        return jsonify({'success': True})
    
    @app.route('/api/scores/update', methods=['POST'])
    @login_required
    @teacher_required
    def api_update_score():
        # Update score logic
        return jsonify({'success': True})
    
    # Export routes
    @app.route('/export/transcript')
    @login_required
    def export_transcript():
        # This would require pdf_generator utility
        flash('Chức năng export đang được phát triển.', 'info')
        return redirect(url_for('student_scores'))
    
    @app.route('/export/scores/<int:course_id>')
    @login_required
    @teacher_required
    def export_scores(course_id):
        # This would require excel_generator utility
        flash('Chức năng export đang được phát triển.', 'info')
        return redirect(url_for('teacher_input_scores'))
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('500.html'), 500
    
    return app



def initialize_app():
    """Initialize the application with database and sample data"""
    app = create_app()
    start_notification_scheduler(app)
    
    with app.app_context():
        create_tables()
        
        if app.config['DEBUG']:
            try:
                create_sample_data()
                logger.info("Sample data created successfully")
            except Exception as e:
                logger.warning(f"Could not create sample data: {e}")
    
    return app

if __name__ == '__main__':
    app = initialize_app()
    def get_local_ip():
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    local_ip = get_local_ip()
    
    print(f"\n📍 http://{local_ip}:5000\n")

    socketio.run(app, debug=False, host='0.0.0.0', port=5000)
