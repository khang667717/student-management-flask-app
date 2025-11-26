import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import smtplib

load_dotenv()

def check_database():
    try:
        engine = create_engine(os.environ.get('DATABASE_URL'))
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Database: CONNECTED")
            return True
    except Exception as e:
        print(f"❌ Database: ERROR - {e}")
        return False

def check_email():
    try:
        server = smtplib.SMTP(os.environ.get('MAIL_SERVER'), int(os.environ.get('MAIL_PORT')))
        server.starttls()
        server.login(os.environ.get('MAIL_USERNAME'), os.environ.get('MAIL_PASSWORD'))
        server.quit()
        print("✅ Email: CONNECTED")
        return True
    except Exception as e:
        print(f"❌ Email: ERROR - {e}")
        return False

def check_config():
    print("🔍 SYSTEM CONFIGURATION CHECK")
    print("=" * 40)
    
    configs = {
        "SECRET_KEY": os.environ.get('SECRET_KEY'),
        "DATABASE_URL": os.environ.get('DATABASE_URL'),
        "MAIL_USERNAME": os.environ.get('MAIL_USERNAME'),
        "MAIL_PASSWORD": "***" if os.environ.get('MAIL_PASSWORD') else None,
        "MAIL_DEFAULT_SENDER": os.environ.get('MAIL_DEFAULT_SENDER')
    }
    
    for key, value in configs.items():
        status = "✅ SET" if value else "❌ MISSING"
        print(f"{key:<20}: {value} {status}")
    
    print("=" * 40)
    
    # Check if sender matches username
    if (os.environ.get('MAIL_USERNAME') and os.environ.get('MAIL_DEFAULT_SENDER') and
        os.environ.get('MAIL_USERNAME') != os.environ.get('MAIL_DEFAULT_SENDER')):
        print("⚠️  WARNING: MAIL_USERNAME and MAIL_DEFAULT_SENDER should match for Gmail")
    
    return check_database() and check_email()

if __name__ == "__main__":
    check_config()