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
        
        c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)''')
        
        # Varsayılan Admin Kullanıcısı
        admin = c.execute("SELECT * FROM kullanicilar WHERE username = 'admin'").fetchone()
        if not admin:
            hashed_pw = generate_password_hash('admin123')
            c.execute("INSERT INTO kullanicilar (username, password) VALUES (?, ?)", ('admin', hashed_pw))
            print("Varsayılan kullanıcı oluşturuldu: admin / admin123")

        conn.commit()
        conn.close()

    # --- KULLANICI İŞLEMLERİ ---
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

    # --- RAPOR VE DASHBOARD ---
    @staticmethod
    def get_dashboard_stats():
        conn = DatabaseManager.get_db_connection()
        
        # 1. Toplam Kalan Adet
        toplam_adet = conn.execute("SELECT SUM(kalan_adet) FROM faturalar").fetchone()[0] or 0
        
        # 2. Toplam Parasal Değer
        toplam_tutar = conn.execute("SELECT SUM(kalan_adet * net_maliyet) FROM faturalar").fetchone()[0] or 0
        
        # 3. (YENİ) Stokta Olan Ürün Çeşit Sayısı
        # DISTINCT komutu aynı ürün birden fazla faturada olsa bile 1 sayar.
        toplam_cesit = conn.execute("SELECT COUNT(DISTINCT urun_id) FROM faturalar WHERE kalan_adet > 0").fetchone()[0] or 0
        
        # Tedarikçi Bazlı Özet
        ozet = conn.execute('''
            SELECT t.ad, SUM(f.kalan_adet), SUM(f.kalan_adet * f.net_maliyet), t.id
            FROM faturalar f
            JOIN tedarikciler t ON f.tedarikci_id = t.id
            WHERE f.kalan_adet > 0
            GROUP BY t.id
        ''').fetchall()
        
        conn.close()
        # toplam_cesit değişkenini de döndürüyoruz
        return toplam_adet, toplam_tutar, toplam_cesit, ozet

    # --- BAĞLANTI / GİRİŞ İŞLEMLERİ ---
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

    # --- SEVKİYAT (FIFO MANITIĞI) ---
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

    # --- TOPLU ÇIKIŞ (FATURA BAZLI) ---
    @staticmethod
    def get_pending_invoices_grouped():
        conn = DatabaseManager.get_db_connection()
        rows = conn.execute('''
            SELECT DISTINCT t.id as tedarikci_id, t.ad as tedarikci_ad, f.fatura_no, f.tarih
            FROM faturalar f
            JOIN tedarikciler t ON f.tedarikci_id = t.id
            WHERE f.kalan_adet > 0
            ORDER BY f.tarih ASC
        ''').fetchall()
        conn.close()
        return rows

    @staticmethod
    def get_invoice_products(tedarikci_id, fatura_no):
        conn = DatabaseManager.get_db_connection()
        rows = conn.execute('''
            SELECT f.id as fatura_id, u.ad as urun_ad, u.barkod, f.kalan_adet, f.net_maliyet
            FROM faturalar f
            JOIN urunler u ON f.urun_id = u.id
            WHERE f.tedarikci_id = ? AND f.fatura_no = ? AND f.kalan_adet > 0
        ''', (tedarikci_id, fatura_no)).fetchall()
        
        result = [dict(row) for row in rows]
        conn.close()
        return result

    @staticmethod
    def process_invoice_bulk_sevkiyat(data):
        conn = DatabaseManager.get_db_connection()
        
        fatura_ids = data.getlist('fatura_id[]')
        cekilecek_adetler = data.getlist('adet[]')
        
        sevk_no = data.get('sevk_no')
        depo = data.get('depo')
        teslim_alan = data.get('teslim_alan')
        islem_tarihi = data.get('tarih')
        
        kayit_sayisi = 0
        
        for i in range(len(fatura_ids)):
            fid = fatura_ids[i]
            adet_str = cekilecek_adetler[i]
            
            if not adet_str or int(adet_str) <= 0:
                continue
                
            adet = int(adet_str)
            fatura = conn.execute("SELECT * FROM faturalar WHERE id = ?", (fid,)).fetchone()
            
            if not fatura or adet > fatura['kalan_adet']:
                continue
            
            yeni_kalan = fatura['kalan_adet'] - adet
            conn.execute("UPDATE faturalar SET kalan_adet = ? WHERE id = ?", (yeni_kalan, fid))
            
            conn.execute('''
                INSERT INTO hareketler (fatura_id, urun_id, tedarikci_id, adet, sevk_no, depo, teslim_alan, tarih)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (fid, fatura['urun_id'], fatura['tedarikci_id'], adet, sevk_no, depo, teslim_alan, islem_tarihi))
            
            kayit_sayisi += 1
            
        conn.commit()
        conn.close()
        
        if kayit_sayisi == 0:
            return False, "İşlem yapılmadı (Miktar girilmedi)."
        return True, f"{kayit_sayisi} kalem ürün başarıyla sevkedildi."

    # --- DÜZENLEME VE SİLME (CRUD) ---
    @staticmethod
    def get_fatura(fatura_id):
        conn = DatabaseManager.get_db_connection()
        fatura = conn.execute("SELECT * FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        conn.close()
        return fatura

    @staticmethod
    def delete_fatura(fatura_id):
        conn = DatabaseManager.get_db_connection()
        fatura = conn.execute("SELECT toplam_adet, kalan_adet FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        if fatura['toplam_adet'] != fatura['kalan_adet']:
            conn.close()
            return False, "Bu faturadan mal sevkiyatı yapılmış! Silinemez."
        conn.execute("DELETE FROM faturalar WHERE id = ?", (fatura_id,))
        conn.commit()
        conn.close()
        return True, "Fatura başarıyla silindi."

    @staticmethod
    def update_fatura(fatura_id, data):
        conn = DatabaseManager.get_db_connection()
        fatura = conn.execute("SELECT toplam_adet, kalan_adet FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        mal_cekilmis = fatura['toplam_adet'] != fatura['kalan_adet']
        yeni_adet = int(data['adet'])
        
        if mal_cekilmis and yeni_adet != fatura['toplam_adet']:
            conn.close()
            return False, "Bu faturadan mal çıkışı yapılmış. Adet değiştirilemez!"

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

    # --- TANIM YÖNETİMİ ---
    @staticmethod
    def get_tedarikci(id):
        conn = DatabaseManager.get_db_connection()
        row = conn.execute("SELECT * FROM tedarikciler WHERE id = ?", (id,)).fetchone()
        conn.close()
        return row

    @staticmethod
    def update_tedarikci(id, ad):
        conn = DatabaseManager.get_db_connection()
        conn.execute("UPDATE tedarikciler SET ad = ? WHERE id = ?", (ad, id))
        conn.commit()
        conn.close()

    @staticmethod
    def delete_tedarikci(id):
        conn = DatabaseManager.get_db_connection()
        count = conn.execute("SELECT COUNT(*) FROM faturalar WHERE tedarikci_id = ?", (id,)).fetchone()[0]
        if count > 0:
            conn.close()
            return False, "Bu tedarikçiye ait kayıtlı faturalar var. Silinemez."
        conn.execute("DELETE FROM tedarikciler WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return True, "Tedarikçi silindi."

    @staticmethod
    def get_urun(id):
        conn = DatabaseManager.get_db_connection()
        row = conn.execute("SELECT * FROM urunler WHERE id = ?", (id,)).fetchone()
        conn.close()
        return row

    @staticmethod
    def update_urun(id, barkod, ad):
        conn = DatabaseManager.get_db_connection()
        conn.execute("UPDATE urunler SET barkod = ?, ad = ? WHERE id = ?", (barkod, ad, id))
        conn.commit()
        conn.close()

    @staticmethod
    def delete_urun(id):
        conn = DatabaseManager.get_db_connection()
        count = conn.execute("SELECT COUNT(*) FROM faturalar WHERE urun_id = ?", (id,)).fetchone()[0]
        if count > 0:
            conn.close()
            return False, "Bu ürüne ait işlem geçmişi var. Silinemez."
        conn.execute("DELETE FROM urunler WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return True, "Ürün silindi."