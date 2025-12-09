import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'cok-gizli-anahtar-degistirilecek'
    DB_NAME = "stok_takip.db"
