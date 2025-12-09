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
    login_manager.login_view = 'main.login' # Giriş yapılmamışsa buraya atar
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return DatabaseManager.get_user_by_id(user_id)

    # Blueprint'leri kaydet
    from app.routes import main
    app.register_blueprint(main)

    return app