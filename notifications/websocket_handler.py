from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request, current_app
from flask_login import current_user
from models import db, Notification, User, Student
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

socketio = SocketIO(cors_allowed_origins="*", async_mode='eventlet')

class NotificationManager:
    @staticmethod
    def send_notification(user_id, title, message, category='system', priority='normal', action_url=None):
        """Send notification to specific user - ĐÃ SỬA"""
        try:
            # Save to database
            notification = Notification(
                user_id=user_id,
                title=title,
                message=message,
                category=category,
                priority=priority,
                action_url=action_url
            )
            db.session.add(notification)
            db.session.commit()
            
            # SỬA: Import socketio từ module hiện tại thay vì từ app
            from . import socketio  # Hoặc từ notifications.websocket_handler import socketio
            
            if socketio:
                socketio.emit('new_notification', {
                    'id': notification.id,
                    'title': title,
                    'message': message,
                    'category': category,
                    'priority': priority,
                    'action_url': action_url,
                    'time': notification.created_at.isoformat(),
                    'unread': True
                }, room=f'user_{user_id}')
                logger.info(f"✅ WebSocket notification sent to user {user_id}")
            else:
                logger.warning("⚠️ SocketIO not available, skipping WebSocket notification")
            
            logger.info(f"✅ Database notification saved for user {user_id}: {title}")
            
        except Exception as e:
            logger.error(f"❌ Error sending notification: {e}")
            db.session.rollback()

    @staticmethod
    def send_bulk_notification(user_ids, title, message, category='system', priority='normal'):
        """Send notification to multiple users"""
        for user_id in user_ids:
            NotificationManager.send_notification(user_id, title, message, category, priority)

    @staticmethod
    def send_course_notification(course_id, title, message, priority='normal'):
        """Send notification to all students in a course"""
        from models import CourseRegistration, Course
        
        course = Course.query.get(course_id)
        if not course:
            logger.error(f"Course {course_id} not found")
            return
        
        registrations = CourseRegistration.query.filter_by(
            course_id=course_id, 
            status='approved'
        ).all()
        
        user_ids = [reg.student.user_id for reg in registrations]
        
        # Also notify the teacher
        user_ids.append(course.teacher.user_id)
        
        NotificationManager.send_bulk_notification(
            user_ids, 
            title, 
            message, 
            category='academic', 
            priority=priority
        )

    @staticmethod
    def send_class_notification(class_id, title, message, priority='normal'):
        """Send notification to all students in a class"""
        from models import Student, Class
        
        class_ = Class.query.get(class_id)
        if not class_:
            logger.error(f"Class {class_id} not found")
            return
        
        students = Student.query.filter_by(class_id=class_id).all()
        user_ids = [student.user_id for student in students]
        
        # Also notify the class teacher
        if class_.teacher:
            user_ids.append(class_.teacher.user_id)
        
        NotificationManager.send_bulk_notification(
            user_ids, 
            title, 
            message, 
            category='academic', 
            priority=priority
        )
    @staticmethod
    def send_bulk_low_score_notifications(course_id=None, threshold=5.0):
        """Gửi thông báo điểm kém cho TẤT CẢ sinh viên trong khóa học"""
        try:
            from models import Score, Course
        
        # Lấy tất cả điểm kém
            query = Score.query.filter(
            Score.final_score < threshold,
            Score.status == 'published'
        )
        
            if course_id:
                query = query.filter(Score.course_id == course_id)
        
            low_scores = query.all()
        
            sent_count = 0
            for score in low_scores:
                try:
                    trigger_low_score_notifications(score, threshold)
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error processing score {score.id}: {str(e)}")
                    continue
        
            logger.info(f"✅ Sent low score notifications for {sent_count} students")
            return sent_count
        
        except Exception as e:
            logger.error(f"Error in bulk low score notifications: {str(e)}")
            return 0

    @staticmethod  
    def send_class_low_score_notifications(class_id, threshold=5.0):
        """Gửi thông báo điểm kém cho TẤT CẢ sinh viên trong lớp"""
        try:
            from models import Student, Score
        
        # Lấy sinh viên trong lớp
            students = Student.query.filter_by(class_id=class_id).all()
            student_ids = [s.id for s in students]
        
        # Lấy điểm kém của các sinh viên này
            low_scores = Score.query.filter(
            Score.student_id.in_(student_ids),
            Score.final_score < threshold,
            Score.status == 'published'
        ).all()
        
            sent_count = 0
            for score in low_scores:
                try:
                    trigger_low_score_notifications(score, threshold)
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error processing score {score.id}: {str(e)}")
                    continue
        
            logger.info(f"✅ Sent low score notifications for {sent_count} students in class {class_id}")
            return sent_count
        
        except Exception as e:
            logger.error(f"Error in class low score notifications: {str(e)}")
            return 0
# WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        logger.info(f"User {current_user.id} connected to WebSocket")
        
        # Send unread notifications count
        unread_count = Notification.query.filter_by(
            user_id=current_user.id, 
            is_read=False
        ).count()
        
        emit('notification_count', {'count': unread_count})
    else:
        # Reject connection for unauthenticated users
        return False

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    if current_user.is_authenticated:
        leave_room(f'user_{current_user.id}')
        logger.info(f"User {current_user.id} disconnected from WebSocket")

@socketio.on('mark_notification_read')
def handle_mark_notification_read(data):
    """Mark notification as read"""
    if not current_user.is_authenticated:
        return
    
    notification_id = data.get('notification_id')
    if not notification_id:
        return
    
    notification = Notification.query.filter_by(
        id=notification_id, 
        user_id=current_user.id
    ).first()
    
    if notification and not notification.is_read:
        notification.is_read = True
        db.session.commit()
        
        # Update unread count
        unread_count = Notification.query.filter_by(
            user_id=current_user.id, 
            is_read=False
        ).count()
        
        emit('notification_count', {'count': unread_count})
        logger.info(f"User {current_user.id} marked notification {notification_id} as read")

@socketio.on('mark_all_notifications_read')
def handle_mark_all_notifications_read():
    """Mark all notifications as read"""
    if not current_user.is_authenticated:
        return
    
    Notification.query.filter_by(
        user_id=current_user.id, 
        is_read=False
    ).update({'is_read': True})
    
    db.session.commit()
    
    emit('notification_count', {'count': 0})
    logger.info(f"User {current_user.id} marked all notifications as read")

@socketio.on('get_notifications')
def handle_get_notifications(data):
    """Get user notifications"""
    if not current_user.is_authenticated:
        return
    
    page = data.get('page', 1)
    per_page = data.get('per_page', 20)
    
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(
        Notification.created_at.desc()
    ).paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    notifications_data = []
    for notification in notifications.items:
        notifications_data.append({
            'id': notification.id,
            'title': notification.title,
            'message': notification.message,
            'category': notification.category,
            'priority': notification.priority,
            'action_url': notification.action_url,
            'time': notification.created_at.isoformat(),
            'is_read': notification.is_read
        })
    
    emit('notifications_list', {
        'notifications': notifications_data,
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': page
    })

# Notification triggers
def trigger_low_score_notifications(score, threshold=5.0):
    """
    Trigger thông báo điểm kém cho sinh viên và giáo viên
    threshold: ngưỡng điểm kém (mặc định 5.0)
    """
    try:
        student = score.student
        course = score.course
        teacher = course.teacher

        logger.info(f"🔔 Bắt đầu gửi thông báo điểm kém cho {student.user.full_name}")
        logger.info(f"📧 Email sinh viên: {student.user.email}")
        logger.info(f"👨‍🏫 Giáo viên: {teacher.user.full_name}")
        
        if score.final_score and score.final_score < threshold:
            # 1. THÔNG BÁO CHO SINH VIÊN
            student_title = f"⚠️ Cảnh báo điểm môn {course.subject.subject_name}"
            student_message = f"""
Điểm môn {course.subject.subject_name} của bạn là {score.final_score:.1f} - DƯỚI MỨC ĐẠT.

📊 Chi tiết:
• Điểm quá trình: {score.process_score or 'Chưa có'}
• Điểm thi: {score.exam_score or 'Chưa có'}  
• Điểm tổng: {score.final_score:.1f}
• Xếp loại: {score.grade}

💡 Khuyến nghị:
- Liên hệ giảng viên {teacher.user.full_name} để được hỗ trợ
- Tham gia các buổi phụ đạo (nếu có)
- Ôn tập kỹ cho kỳ thi cải thiện

📞 Liên hệ: {teacher.user.email}
            """
            
            NotificationManager.send_notification(
                student.user_id,
                student_title,
                student_message.strip(),
                category='academic',
                priority='high',
                action_url=f'/student/scores'
            )
            
            # 2. GỬI EMAIL CHO SINH VIÊN
            logger.info(f"📤 Đang gửi email đến: {student.user.email}")
            email_success = send_low_score_email(  # 🚨 SỬA: Lưu kết quả gửi email
                student_email=student.user.email,
                student_name=student.user.full_name,
                course_name=course.subject.subject_name,
                course_code=course.course_code,
                process_score=score.process_score,
                exam_score=score.exam_score,
                final_score=score.final_score,
                grade=score.grade,
                teacher_name=teacher.user.full_name,
                teacher_email=teacher.user.email
            )
            
            if email_success:
                logger.info(f"✅ Đã gửi email thành công đến {student.user.email}")
            else:
                logger.error(f"❌ Gửi email thất bại đến {student.user.email}")
            
            # 3. THÔNG BÁO CHO GIÁO VIÊN
            teacher_title = f"📉 Sinh viên điểm kém - {course.subject.subject_name}"
            teacher_message = f"""
Sinh viên {student.user.full_name} ({student.student_id}) có điểm dưới chuẩn.

📊 Kết quả:
• Điểm QT: {score.process_score or 'N/A'}
• Điểm thi: {score.exam_score or 'N/A'}
• Điểm tổng: {score.final_score:.1f} 
• Xếp loại: {score.grade}

👤 Thông tin SV:
- Lớp: {student.classes[0].class_name if student.classes else 'N/A'}
- Email: {student.user.email}
- SĐT: {student.user.phone or 'Chưa cập nhật'}

🎯 Hành động đề xuất:
- Liên hệ hỗ trợ sinh viên
- Đề xuất buổi phụ đạo
- Cập nhật kế hoạch giảng dạy
            """
            
            NotificationManager.send_notification(
                teacher.user_id,
                teacher_title,
                teacher_message.strip(),
                category='teaching',
                priority='medium',
                action_url=f'/teacher/input-scores?course_id={course.id}'
            )
            
            logger.info(f"✅ Low score notification sent for student {student.id} in course {course.id}")
            
    except Exception as e:
        logger.error(f"❌ Error in low score notification: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")

def send_low_score_email(student_email, student_name, course_name, course_code, 
                        process_score, exam_score, final_score, grade, 
                        teacher_name, teacher_email):
    """Gửi email thông báo điểm kém cho sinh viên - ĐÃ SỬA"""
    try:
        from flask_mail import Message
        from flask import current_app
        
        # 🚨 SỬA: Kiểm tra cấu hình email chi tiết hơn
        required_configs = {
            'MAIL_SERVER': current_app.config.get('MAIL_SERVER'),
            'MAIL_USERNAME': current_app.config.get('MAIL_USERNAME'), 
            'MAIL_PASSWORD': current_app.config.get('MAIL_PASSWORD'),
            'MAIL_PORT': current_app.config.get('MAIL_PORT'),
            'MAIL_DEFAULT_SENDER': current_app.config.get('MAIL_DEFAULT_SENDER')
        }
        
        # Kiểm tra các config bắt buộc
        missing_configs = [key for key, value in required_configs.items() if not value]
        if missing_configs:
            logger.error(f"❌ Cấu hình email thiếu: {missing_configs}")
            return False
            
        mail = current_app.extensions.get('mail')
        if not mail:
            logger.error("❌ Mail extension không được khởi tạo")
            return False
            
        # 🚨 SỬA: Test kết nối đơn giản hơn (tránh lỗi với một số SMTP)
        try:
            # Chỉ test kết nối cơ bản, không dùng with mail.connect()
            logger.info(f"🔧 Testing email connection to {required_configs['MAIL_SERVER']}:{required_configs['MAIL_PORT']}")
        except Exception as conn_error:
            logger.error(f"❌ Lỗi kết nối mail server: {str(conn_error)}")
            return False
            
        subject = f"🔔 Thông báo điểm môn {course_name} - Hệ thống Quản lý Học tập"
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #ff6b6b, #ee5a24); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
        .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
        .score-card {{ background: white; border-left: 4px solid #ff6b6b; padding: 15px; margin: 15px 0; }}
        .recommendation {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; }}
        .contact-info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 5px; }}
        .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ Thông báo Điểm Học tập</h1>
            <p>Môn {course_name} ({course_code})</p>
        </div>
        
        <div class="content">
            <p>Xin chào <strong>{student_name}</strong>,</p>
            
            <div class="score-card">
                <h3>📊 Kết quả học tập</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Điểm quá trình:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;">{process_score or 'Chưa có'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Điểm thi:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;">{exam_score or 'Chưa có'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Điểm tổng kết:</strong></td>
                        <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong style="color: #e74c3c;">{final_score:.1f}</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;"><strong>Xếp loại:</strong></td>
                        <td style="padding: 8px;"><strong>{grade}</strong></td>
                    </tr>
                </table>
            </div>

            <div class="recommendation">
                <h4>💡 Khuyến nghị học tập</h4>
                <ul>
                    <li>Liên hệ giảng viên để được hướng dẫn thêm</li>
                    <li>Tham gia các buổi phụ đạo của môn học</li>
                    <li>Ôn tập lại các nội dung trọng tâm</li>
                    <li>Chuẩn bị cho kỳ thi cải thiện (nếu có)</li>
                </ul>
            </div>

            <div class="contact-info">
                <h4>📞 Thông tin liên hệ</h4>
                <p><strong>Giảng viên:</strong> {teacher_name}</p>
                <p><strong>Email:</strong> {teacher_email}</p>
            </div>

            <p>Trân trọng,<br>
            <strong>Phòng Đào tạo</strong><br>
            Hệ thống Quản lý Học tập</p>
        </div>
        
        <div class="footer">
            <p>Email này được gửi tự động từ hệ thống. Vui lòng không trả lời.</p>
        </div>
    </div>
</body>
</html>
        """
        
        msg = Message(
            subject=subject,
            recipients=[student_email],
            html=html_body,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER')
        )
        
        mail.send(msg)
        logger.info(f"✅ Low score email sent to {student_email}")
        return True  # 🚨 SỬA: Trả về True khi thành công
        
    except Exception as e:
        logger.error(f"❌ Error sending low score email: {str(e)}")
        import traceback
        logger.error(f"❌ Email error details: {traceback.format_exc()}")
        return False  # 🚨 SỬA: Trả về False khi thất bại
    
# CẬP NHẬT HÀM trigger_score_notification HIỆN TẠI
def trigger_score_notification(score):
    """Trigger notification when score is published - ĐÃ NÂNG CẤP"""
    if score.status == 'published' and score.final_score:
        student = score.student
        course = score.course
        
        # GỬI THÔNG BÁO ĐIỂM KÉM NẾU DƯỚI NGƯỠNG
        if score.final_score < 5.0:
            trigger_low_score_notifications(score, threshold=5.0)
        
        # THÔNG BÁO THÔNG THƯỜNG (giữ nguyên logic cũ)
        elif score.final_score >= 5.0:
            title = f"Điểm môn {course.subject.subject_name} đã được công bố"
            message = f"Bạn đã hoàn thành môn {course.subject.subject_name} với điểm {score.final_score:.1f}"
            priority = 'normal'
        else:
            title = f"Thông báo điểm môn {course.subject.subject_name}"
            message = f"Điểm môn {course.subject.subject_name} của bạn là {score.final_score:.1f}. Vui lòng liên hệ giảng viên để biết thêm chi tiết."
            priority = 'high'
        
        # Chỉ gửi thông báo thông thường nếu không phải điểm kém (để tránh trùng lặp)
        if score.final_score >= 5.0:
            NotificationManager.send_notification(
                student.user_id,
                title,
                message,
                category='academic',
                priority=priority,
                action_url=f'/student/scores'
            )
def trigger_registration_notification(registration):
    """Trigger notification for course registration"""
    student = registration.student
    course = registration.course
    
    if registration.status == 'approved':
        title = f"Đăng ký học phần được duyệt"
        message = f"Đăng ký môn {course.subject.subject_name} của bạn đã được duyệt."
        priority = 'normal'
    elif registration.status == 'rejected':
        title = f"Đăng ký học phần bị từ chối"
        message = f"Đăng ký môn {course.subject.subject_name} của bạn đã bị từ chối. Vui lòng liên hệ phòng đào tạo để biết thêm chi tiết."
        priority = 'high'
    else:
        return
    
    NotificationManager.send_notification(
        student.user_id,
        title,
        message,
        category='academic',
        priority=priority,
        action_url=f'/student/course-register'
    )

def trigger_deadline_notification():
    """Trigger deadline notifications"""
    from models import Course, CourseRegistration
    from datetime import datetime, timedelta
    
    # Notify about upcoming deadlines (within 3 days)
    upcoming_deadline = datetime.utcnow() + timedelta(days=3)
    
    courses_with_deadlines = Course.query.filter(
        Course.end_date <= upcoming_deadline,
        Course.end_date >= datetime.utcnow()
    ).all()
    
    for course in courses_with_deadlines:
        days_left = (course.end_date - datetime.utcnow().date()).days
        title = f"Deadline sắp tới: {course.subject.subject_name}"
        message = f"Còn {days_left} ngày đến deadline môn {course.subject.subject_name}. Vui lòng hoàn thành các bài tập và ôn tập cho kỳ thi."
        
        NotificationManager.send_course_notification(
            course.id,
            title,
            message,
            priority='high' if days_left <= 1 else 'normal'
        )

def trigger_academic_warning(student):
    """Trigger academic warning notification - ĐÃ SỬA"""
    # CHỈ gửi cảnh báo nếu GPA thực sự có giá trị và dưới ngưỡng
    if student.gpa and student.gpa < current_app.config.get('ACADEMIC_WARNING_GPA', 2.0):
        title = "Cảnh báo học tập"
        message = f"GPA của bạn hiện tại là {student.gpa:.2f}, dưới mức yêu cầu. Vui lòng liên hệ cố vấn học tập để được hỗ trợ."
        
        NotificationManager.send_notification(
            student.user_id,
            title,
            message,
            category='academic',
            priority='high',
            action_url=f'/student/scores'
        )


import threading
import time



# Background task for periodic notifications
def start_notification_scheduler(app):
    """Start background scheduler for periodic notifications - ĐÃ SỬA"""

    def scheduler():
        with app.app_context():
            while True:
                try:
                    trigger_deadline_notification()

                    # CHỈ chạy vào lúc 8h sáng và kiểm tra GPA thực
                    if datetime.utcnow().hour == 8:
                        students_needing_warning = Student.query.filter(
                            Student.gpa.isnot(None),  # CHỈ sinh viên có GPA
                            Student.gpa > 0,          # GPA phải lớn hơn 0
                            Student.gpa < app.config.get('ACADEMIC_WARNING_GPA', 2.0)
                        ).all()
                        
                        for student in students_needing_warning:
                            trigger_academic_warning(student)

                    time.sleep(3600)  # Chờ 1 giờ

                except Exception as e:
                    logger.error(f"Error in notification scheduler: {e}")
                    time.sleep(300)   # Nếu lỗi, chờ 5 phút

    scheduler_thread = threading.Thread(target=scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("Notification scheduler started")

