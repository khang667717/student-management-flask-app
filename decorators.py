from functools import wraps
from flask import flash, redirect, url_for, request, jsonify
from flask_login import current_user
from models import UserRole
import logging

logger = logging.getLogger(__name__)

def role_required(role):
    """Decorator to require specific role for access"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Vui lòng đăng nhập để truy cập trang này.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            if current_user.role != role and not current_user.is_admin:
                flash('Bạn không có quyền truy cập trang này.', 'error')
                logger.warning(f'Unauthorized access attempt by user {current_user.id} to {request.path}')
                return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require admin role"""
    return role_required(UserRole.ADMIN)(f)

def teacher_required(f):
    """Decorator to require teacher role"""
    return role_required(UserRole.TEACHER)(f)

def student_required(f):
    """Decorator to require student role"""
    return role_required(UserRole.STUDENT)(f)

def permission_required(permission):
    """Decorator for more granular permissions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                flash('Vui lòng đăng nhập.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            # Check permission based on role and additional logic
            has_permission = check_permission(current_user, permission, *args, **kwargs)
            
            if not has_permission:
                if request.is_json:
                    return jsonify({'error': 'Insufficient permissions'}), 403
                flash('Bạn không có quyền thực hiện thao tác này.', 'error')
                return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def check_permission(user, permission, *args, **kwargs):
    """Check if user has specific permission"""
    # Admin has all permissions
    if user.is_admin:
        return True
    
    # Define permission matrix
    permissions = {
        'manage_users': [UserRole.ADMIN],
        'manage_students': [UserRole.ADMIN, UserRole.TEACHER],
        'manage_teachers': [UserRole.ADMIN],
        'manage_courses': [UserRole.ADMIN, UserRole.TEACHER],
        'input_scores': [UserRole.TEACHER],
        'view_scores': [UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT],
        'register_courses': [UserRole.STUDENT],
        'export_data': [UserRole.ADMIN, UserRole.TEACHER],
    }
    
    if permission in permissions:
        return user.role in permissions[permission]
    
    return False

def log_activity(action, module):
    """Decorator to log user activities"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from models import SystemLog, db
            from flask import request
            
            result = f(*args, **kwargs)
            
            # Log the activity
            if current_user.is_authenticated:
                log = SystemLog(
                    user_id=current_user.id,
                    action=action,
                    module=module,
                    description=f'{action} in {module}',
                    ip_address=request.remote_addr,
                    user_agent=request.user_agent.string
                )
                db.session.add(log)
                db.session.commit()
            
            return result
        return decorated_function
    return decorator

def handle_exceptions(f):
    """Decorator to handle exceptions gracefully"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f'Error in {f.__name__}: {str(e)}', exc_info=True)
            
            if request.is_json:
                return jsonify({'error': 'Đã xảy ra lỗi hệ thống'}), 500
            
            flash('Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.', 'error')
            return redirect(url_for('index'))
    return decorated_function