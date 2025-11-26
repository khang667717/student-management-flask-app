import os
import re

def fix_template_file(file_path):
    """Sửa lỗi trong template file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Sửa student.classes thành student_classes với xử lý dynamic query
    old_pattern = r'{% for class in (.*?)\.classes %}(.*?){% endfor %}'
    new_content = re.sub(old_pattern, 
                        r'{% set \1_classes = \1.classes.all() if \1.classes.__class__.__name__ == "AppenderQuery" else \1.classes %}{% for class in \1_classes %}\2{% endfor %}', 
                        content, 
                        flags=re.DOTALL)
    
    # Sửa class.current_students thành class.current_students_count
    new_content = new_content.replace('class.current_students', 'class.current_students_count')
    
    # Sửa registration.student.classes
    new_content = new_content.replace('registration.student.classes', 'student_classes')
    
    if content != new_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"✅ Đã sửa: {file_path}")
    else:
        print(f"ℹ️  Không cần sửa: {file_path}")

def fix_all_templates():
    """Sửa tất cả template files"""
    template_dir = 'templates'
    
    for root, dirs, files in os.walk(template_dir):
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                fix_template_file(file_path)

if __name__ == '__main__':
    print("🚀 Bắt đầu sửa tất cả templates...")
    fix_all_templates()
    print("🎉 Hoàn thành!")