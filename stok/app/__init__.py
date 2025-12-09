from flask import Flask
from flask_login import LoginManager
from config import Config

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Veritabanı başlat
    from app.models import DatabaseManager
    DatabaseManager.init_db(app.config['DB_NAME'])

    # Login Yönetimi
    login_manager = LoginManager()
    login_manager.login_view = 'main.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return DatabaseManager.get_user_by_id(user_id)

    # --- ÖZEL FİLTRELER (TL Formatı) ---
    @app.template_filter('money')
    def money_format(value):
        if value is None:
            return "0,00"
        # Önce Amerikan formatına çevir: 1,234.56
        s = "{:,.2f}".format(value)
        # Sonra karakterleri değiştir: Virgül -> X, Nokta -> Virgül, X -> Nokta
        # Sonuç: 1.234,56
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    # Blueprint'leri kaydet
    from app.routes import main
    app.register_blueprint(main)

    return app