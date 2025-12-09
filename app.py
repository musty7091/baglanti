import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Güvenlik anahtarını değiştirdik
app.config['SECRET_KEY'] = 'baglanti_sistemi_gizli_anahtar_ertan_market'
# Veritabanı dosyasının adı baglanti.db oldu
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///baglanti.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELLER ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    contact_info = db.Column(db.String(250))
    transactions = db.relationship('Transaction', backref='supplier', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    unit = db.Column(db.String(20), default='Adet')
    transactions = db.relationship('Transaction', backref='product', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    # Tipler: 'alim_faturasi' veya 'teslim_alma'
    transaction_type = db.Column(db.String(20), nullable=False) 
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Float, default=0.0)
    vat = db.Column(db.Integer, default=20)
    doc_number = db.Column(db.String(50))
    location = db.Column(db.String(100))
    receiver = db.Column(db.String(100))
    description = db.Column(db.String(250))
    total_amount = db.Column(db.Float, default=0.0)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def setup_database():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            hashed_pw = generate_password_hash('admin123', method='pbkdf2:sha256')
            new_user = User(username='admin', password_hash=hashed_pw)
            db.session.add(new_user)
            db.session.commit()
            print("Veritabanı (baglanti.db) ve admin kullanıcısı oluşturuldu.")

@app.route('/')
def index():
    return "Baglanti Yazilimi Calisiyor!"

if __name__ == '__main__':
    setup_database()
    app.run(debug=True)