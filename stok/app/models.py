import sqlite3
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

class DatabaseManager:
    @staticmethod
    def get_db_connection():
        conn = sqlite3.connect(current_app.config['DB_NAME'])
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def init_db(db_name):
        conn = sqlite3.connect(db_name)
        c = conn.cursor()
        
        # Tablolar
        c.execute('''CREATE TABLE IF NOT EXISTS tedarikciler 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, ad TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS urunler 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, barkod TEXT, ad TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS faturalar 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      tedarikci_id INTEGER, urun_id INTEGER, 
                      fatura_no TEXT, tarih TEXT, 
                      toplam_adet INTEGER, kalan_adet INTEGER, 
                      net_maliyet REAL)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS hareketler 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      fatura_id INTEGER, urun_id INTEGER, tedarikci_id INTEGER,
                      adet INTEGER, sevk_no TEXT, depo TEXT, teslim_alan TEXT, tarih TEXT)''')
        
        # Kullanıcılar Tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)''')
        
        # Varsayılan Admin Kullanıcısı Oluştur (Eğer yoksa)
        admin = c.execute("SELECT * FROM kullanicilar WHERE username = 'admin'").fetchone()
        if not admin:
            hashed_pw = generate_password_hash('admin123')
            c.execute("INSERT INTO kullanicilar (username, password) VALUES (?, ?)", ('admin', hashed_pw))
            print("Varsayılan kullanıcı oluşturuldu: admin / admin123")

        conn.commit()
        conn.close()

    # --- Kullanıcı İşlemleri ---
    @staticmethod
    def get_user_by_id(user_id):
        conn = DatabaseManager.get_db_connection()
        user_data = conn.execute("SELECT * FROM kullanicilar WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if user_data:
            return User(user_data['id'], user_data['username'], user_data['password'])
        return None

    @staticmethod
    def get_user_by_username(username):
        conn = DatabaseManager.get_db_connection()
        user_data = conn.execute("SELECT * FROM kullanicilar WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user_data:
            return User(user_data['id'], user_data['username'], user_data['password'])
        return None

    # --- İş Mantığı Metodları ---
    
    @staticmethod
    def get_dashboard_stats():
        conn = DatabaseManager.get_db_connection()
        toplam_adet = conn.execute("SELECT SUM(kalan_adet) FROM faturalar").fetchone()[0] or 0
        toplam_tutar = conn.execute("SELECT SUM(kalan_adet * net_maliyet) FROM faturalar").fetchone()[0] or 0
        
        ozet = conn.execute('''
            SELECT t.ad, SUM(f.kalan_adet), SUM(f.kalan_adet * f.net_maliyet), t.id
            FROM faturalar f
            JOIN tedarikciler t ON f.tedarikci_id = t.id
            WHERE f.kalan_adet > 0
            GROUP BY t.id
        ''').fetchall()
        conn.close()
        return toplam_adet, toplam_tutar, ozet

    @staticmethod
    def add_baglanti(data):
        fiyat = float(data['fiyat'])
        iskonto = float(data['iskonto'])
        kdv = float(data['kdv'])
        adet = int(data['adet'])
        
        iskontolu_fiyat = fiyat - (fiyat * iskonto / 100)
        net_maliyet = iskontolu_fiyat * (1 + kdv / 100)
        
        conn = DatabaseManager.get_db_connection()
        conn.execute('''
            INSERT INTO faturalar (tedarikci_id, urun_id, fatura_no, tarih, toplam_adet, kalan_adet, net_maliyet)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (data['tedarikci_id'], data['urun_id'], data['fatura_no'], data['tarih'], adet, adet, net_maliyet))
        conn.commit()
        conn.close()
        return net_maliyet

    @staticmethod
    def process_sevkiyat(data):
        conn = DatabaseManager.get_db_connection()
        cekilecek = int(data['adet'])
        
        faturalar = conn.execute('''
            SELECT * FROM faturalar 
            WHERE tedarikci_id = ? AND urun_id = ? AND kalan_adet > 0
            ORDER BY tarih ASC, id ASC
        ''', (data['tedarikci_id'], data['urun_id'])).fetchall()
        
        toplam_bakiye = sum(f['kalan_adet'] for f in faturalar)
        if toplam_bakiye < cekilecek:
            conn.close()
            return False, f"Yetersiz Bakiye! Mevcut: {toplam_bakiye}"
            
        kalan_istenen = cekilecek
        for fatura in faturalar:
            if kalan_istenen <= 0: break
                
            mevcut = fatura['kalan_adet']
            dusulecek = min(mevcut, kalan_istenen)
            
            conn.execute('UPDATE faturalar SET kalan_adet = ? WHERE id = ?', (mevcut - dusulecek, fatura['id']))
            
            conn.execute('''
                INSERT INTO hareketler (fatura_id, urun_id, tedarikci_id, adet, sevk_no, depo, teslim_alan, tarih)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (fatura['id'], data['urun_id'], data['tedarikci_id'], dusulecek, 
                  data['sevk_no'], data['depo'], data['teslim_alan'], data['tarih']))
            
            kalan_istenen -= dusulecek
            
        conn.commit()
        conn.close()
        return True, "İşlem Başarılı"

    # --- Silme ve Düzenleme Fonksiyonları ---

    @staticmethod
    def get_fatura(fatura_id):
        conn = DatabaseManager.get_db_connection()
        fatura = conn.execute("SELECT * FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        conn.close()
        return fatura

    @staticmethod
    def delete_fatura(fatura_id):
        conn = DatabaseManager.get_db_connection()
        # Kontrol: Faturadan mal çekilmiş mi?
        fatura = conn.execute("SELECT toplam_adet, kalan_adet FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        
        if fatura['toplam_adet'] != fatura['kalan_adet']:
            conn.close()
            return False, "Bu faturadan mal sevkiyatı yapılmış! Önce sevkiyatları iptal etmelisiniz (Şu an desteklenmiyor)."
        
        conn.execute("DELETE FROM faturalar WHERE id = ?", (fatura_id,))
        conn.commit()
        conn.close()
        return True, "Fatura başarıyla silindi."

    @staticmethod
    def update_fatura(fatura_id, data):
        conn = DatabaseManager.get_db_connection()
        
        # Kontrol: Mal çekilmiş mi? Çekildiyse sadece Belge No ve Tarih değişebilir, ADET/FİYAT değişemez.
        fatura = conn.execute("SELECT toplam_adet, kalan_adet FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        mal_cekilmis = fatura['toplam_adet'] != fatura['kalan_adet']
        
        yeni_adet = int(data['adet'])
        
        if mal_cekilmis and yeni_adet != fatura['toplam_adet']:
            conn.close()
            return False, "Bu faturadan mal çıkışı yapılmış. Adet değiştirilemez!"

        # Maliyet yeniden hesapla
        fiyat = float(data['fiyat'])
        iskonto = float(data['iskonto'])
        kdv = float(data['kdv'])
        iskontolu_fiyat = fiyat - (fiyat * iskonto / 100)
        net_maliyet = iskontolu_fiyat * (1 + kdv / 100)

        conn.execute('''
            UPDATE faturalar 
            SET fatura_no=?, tarih=?, toplam_adet=?, kalan_adet=?, net_maliyet=?
            WHERE id=?
        ''', (data['fatura_no'], data['tarih'], yeni_adet, yeni_adet, net_maliyet, fatura_id))
        
        conn.commit()
        conn.close()
        return True, "Fatura güncellendi."