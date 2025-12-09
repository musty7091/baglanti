from flask import Flask
from config import Config

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Veritabanı başlatıcıyı import et
    from app.models import DatabaseManager
    DatabaseManager.init_db(app.config['DB_NAME'])

    # Blueprint'leri (Route'ları) kaydet
    from app.routes import main
    app.register_blueprint(main)

    return app
