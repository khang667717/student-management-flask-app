from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField  # THÊM SelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError 
# from wtforms.validators import Regexp # Bỏ ghi chú nếu cần dùng
from wtforms import FieldList, FormField  # Thêm import này nếu cần


def validate_teacher_department(form, field):
    """Validator cho department khi role là teacher"""
    if form.role.data == 'teacher' and not field.data:
        raise ValidationError('Vui lòng chọn chuyên ngành cho giáo viên')

def validate_student_course(form, field):
    """Validator cho course_year khi role là student"""
    if form.role.data == 'student' and not field.data:
        raise ValidationError('Vui lòng chọn khóa học cho sinh viên')

class LoginForm(FlaskForm):
    # Tên trường phải KHỚP với tên bạn dùng trong template (username, password, remember_me, submit)
    username = StringField('Tên đăng nhập', validators=[DataRequired(), Length(min=1, max=64)])
    password = PasswordField('Mật khẩu', validators=[DataRequired()])
    remember_me = BooleanField('Ghi nhớ đăng nhập')
    submit = SubmitField('Đăng Nhập')

class RegistrationForm(FlaskForm):
    """
    Form Đăng ký Tài khoản Sinh viên
    """
    
    # 1. Thông tin Đăng nhập
    username = StringField(
        'Tên đăng nhập', 
        validators=[
            DataRequired(message='Tên đăng nhập không được để trống.'), 
            Length(min=6, max=20, message='Tên đăng nhập phải từ 6 đến 20 ký tự.')
        ]
    )
    email = StringField(
        'Email', 
        validators=[
            DataRequired(message='Email không được để trống.'), 
            Email(message='Email không hợp lệ.')
        ]
    )
    password = PasswordField(
        'Mật khẩu', 
        validators=[
            DataRequired(message='Mật khẩu không được để trống.'),
            Length(min=6, message='Mật khẩu phải có ít nhất 6 ký tự.')
        ]
    )
    confirm_password = PasswordField(
        'Xác nhận mật khẩu', 
        validators=[
            DataRequired(message='Vui lòng xác nhận mật khẩu.'), 
            EqualTo('password', message='Mật khẩu xác nhận không khớp.')
        ]
    )
    
    # 2. Thông tin Cá nhân
    full_name = StringField(
        'Họ và tên', 
        validators=[
            DataRequired(message='Họ và tên không được để trống.')
        ]
    )
    student_id = StringField(
        'Mã sinh viên', 
        validators=[
            DataRequired(message='Mã sinh viên không được để trống.'), 
            Length(max=15, message='Mã sinh viên tối đa 15 ký tự.')
        ]
    )
    phone = StringField('Số điện thoại')
    address = StringField('Địa chỉ')
    
    # 3. Điều khoản
    agree_terms = BooleanField(
        'Đồng ý điều khoản', 
        validators=[
            DataRequired(message='Bạn phải đồng ý với điều khoản sử dụng.')
        ]
    )
    
    # 4. Nút Submit
    submit = SubmitField('Đăng Ký')


class AddUserForm(FlaskForm):
    full_name = StringField(
        'Họ và tên', 
        validators=[DataRequired(message='Họ và tên không được để trống.')]
    )
    username = StringField(
        'Tên đăng nhập', 
        validators=[
            DataRequired(message='Tên đăng nhập không được để trống.'), 
            Length(min=3, max=20, message='Tên đăng nhập phải từ 3 đến 20 ký tự.')
        ]
    )
    email = StringField(
        'Email', 
        validators=[
            DataRequired(message='Email không được để trống.'), 
            Email(message='Email không hợp lệ.')
        ]
    )
    role = SelectField(
        'Vai trò', 
        choices=[
            ('', 'Chọn vai trò'),  # Thêm option trống
            ('student', 'Sinh viên'),
            ('teacher', 'Giáo viên'), 
            ('admin', 'Admin')
        ], 
        validators=[DataRequired(message='Vui lòng chọn vai trò.')]
    )
    
    
    # 🎯 DYNAMIC FIELDS - Sẽ hiển thị dựa trên role được chọn
    department = SelectField(
        'Chuyên ngành (Giảng viên)',
        choices=[
            ('', 'Chọn chuyên ngành'),
            ('cntt', 'Công nghệ Thông tin'),
            ('kt', 'Kế Toán'),
            ('qtkd', 'Quản trị Kinh doanh'),
            ('anh', 'Ngôn ngữ Anh'),
            ('dl', 'Du lịch'),
            ('csdl', 'Cơ sở dữ liệu'),
            ('dstt', 'Đại số tuyến tính'),
            ('nmhm', 'Nhập môn học máy'),
            
        ],
        validators=[validate_teacher_department]  # Không required mặc định
    )
    
    course_year = SelectField(
        'Khóa học (Sinh viên)',
        choices=[
            ('', 'Chọn khóa học'),
            ('K2024', 'K2024'),
            ('K2025', 'K2025'),
            ('K2026', 'K2026'),
            ('K2027', 'K2027')
        ],
        validators=[validate_student_course]  # Không required mặc định
    )
    
    password = PasswordField(
        'Mật khẩu', 
        validators=[
            DataRequired(message='Mật khẩu không được để trống.'),
            Length(min=6, message='Mật khẩu phải có ít nhất 6 ký tự.')
        ]
    )
    confirm_password = PasswordField(
        'Xác nhận mật khẩu', 
        validators=[
            DataRequired(message='Vui lòng xác nhận mật khẩu.'), 
            EqualTo('password', message='Mật khẩu xác nhận không khớp.')
        ]
    )
    is_active = BooleanField('Kích hoạt tài khoản ngay', default=True)
    submit = SubmitField('Thêm User')



