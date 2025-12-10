from flask import Flask
from flask_login import LoginManager
from config import Config
import os

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Veritabanı başlat
    from app.models import DatabaseManager
    DatabaseManager.init_db(app.config['DB_NAME'])

    # --- OTOMATİK YEDEKLEME (UYGULAMA BAŞLARKEN) ---
    # Sadece ana işlemde çalışsın (Debug modunda iki kere çalışmasını engeller)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        with app.app_context():
            print("Sistem başlatılıyor... Otomatik yedek alınıyor...")
            DatabaseManager.backup_db()
    # -----------------------------------------------

    # Login Yönetimi
    login_manager = LoginManager()
    login_manager.login_view = 'main.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return DatabaseManager.get_user_by_id(user_id)

    @app.template_filter('money')
    def money_format(value):
        if value is None: return "0,00"
        s = "{:,.2f}".format(value)
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    from app.routes import main
    app.register_blueprint(main)

    return app