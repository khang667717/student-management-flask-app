import os
from datetime import timedelta
from dotenv import load_dotenv
#config.py
# Tải biến môi trường từ file .env
load_dotenv()

class Config:
    # Basic Flask Config
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database Config - ƯU TIÊN BIẾN MÔI TRƯỜNG
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'mysql+pymysql://root:12345678@localhost/student_management'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session Config
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # File Upload Config
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xlsx', 'xls'}
    
    # Email Config - SỬ DỤNG BIẾN MÔI TRƯỜNG
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'noreply@studentmanagement.com'
    
    # Redis Config (for Celery and SocketIO)
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # Application Specific Config
    MAX_CREDITS_PER_SEMESTER = 24
    MIN_CREDITS_PER_SEMESTER = 12
    ACADEMIC_WARNING_GPA = 2.0
    ACADEMIC_PROBATION_GPA = 1.5
    
    # Notification Config
    NOTIFICATION_RETENTION_DAYS = 30
    AUTO_EMAIL_NOTIFICATIONS = True

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    DEBUG = False
    TESTING = False

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}