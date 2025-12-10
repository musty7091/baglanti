import sqlite3
import os
import shutil
from datetime import datetime
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
        
        admin = c.execute("SELECT * FROM kullanicilar WHERE username = 'admin'").fetchone()
        if not admin:
            hashed_pw = generate_password_hash('admin123')
            c.execute("INSERT INTO kullanicilar (username, password) VALUES (?, ?)", ('admin', hashed_pw))

        conn.commit()
        conn.close()

    # --- EXCEL İLE TOPLU YÜKLEME (AKILLI IMPORT) ---
    @staticmethod
    def import_from_excel(filepath):
        import pandas as pd
        
        conn = DatabaseManager.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Excel dosyasını oku
            df = pd.read_excel(filepath)
            
            # Sütun isimlerini küçük harfe çevir ve boşlukları temizle
            df.columns = [str(c).lower().strip() for c in df.columns]
            
            # GÜNCELLENEN ZORUNLU SÜTUNLAR
            required_cols = ['barkod', 'urun_adi', 'tedarikci', 'fatura_no', 'tarih', 'adet', 'birim_fiyat', 'iskonto', 'kdv']
            
            for col in required_cols:
                if col not in df.columns:
                    return False, f"Excel dosyasında '{col}' sütunu bulunamadı! Lütfen güncel şablonu kullanın."

            kayit_sayisi = 0
            yeni_urun_sayisi = 0
            
            for index, row in df.iterrows():
                # 1. Verileri al ve temizle
                barkod = str(row['barkod']).strip()
                urun_adi = str(row['urun_adi']).strip()
                tedarikci_adi = str(row['tedarikci']).strip()
                fatura_no = str(row['fatura_no']).strip()
                tarih = str(row['tarih']).split()[0]
                adet = int(row['adet'])
                
                # Fiyat Hesaplama Bileşenleri
                birim_fiyat = float(row['birim_fiyat'])
                iskonto = float(row['iskonto']) if pd.notna(row['iskonto']) else 0
                kdv = float(row['kdv']) if pd.notna(row['kdv']) else 20

                # 2. TEDARİKÇİ KONTROLÜ (Yoksa Oluştur)
                ted_row = cursor.execute("SELECT id FROM tedarikciler WHERE ad = ?", (tedarikci_adi,)).fetchone()
                if ted_row:
                    tedarikci_id = ted_row['id']
                else:
                    cursor.execute("INSERT INTO tedarikciler (ad) VALUES (?)", (tedarikci_adi,))
                    tedarikci_id = cursor.lastrowid

                # 3. ÜRÜN KONTROLÜ (Yoksa Oluştur)
                urun_row = cursor.execute("SELECT id FROM urunler WHERE barkod = ?", (barkod,)).fetchone()
                if urun_row:
                    urun_id = urun_row['id']
                else:
                    cursor.execute("INSERT INTO urunler (barkod, ad) VALUES (?, ?)", (barkod, urun_adi))
                    urun_id = cursor.lastrowid
                    yeni_urun_sayisi += 1

                # 4. MALİYET HESAPLAMA (Otomatik)
                iskontolu_fiyat = birim_fiyat - (birim_fiyat * iskonto / 100)
                net_maliyet = iskontolu_fiyat * (1 + kdv / 100)

                # 5. FATURA KAYDI
                # Not: Aynı fatura içinde aynı ürün varsa mükerrerlik kontrolü burada yapılabilir.
                # Şimdilik direkt ekliyoruz.
                cursor.execute('''
                    INSERT INTO faturalar (tedarikci_id, urun_id, fatura_no, tarih, toplam_adet, kalan_adet, net_maliyet)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (tedarikci_id, urun_id, fatura_no, tarih, adet, adet, net_maliyet))
                
                kayit_sayisi += 1

            conn.commit()
            conn.close()
            return True, f"{kayit_sayisi} kalem işlendi. {yeni_urun_sayisi} yeni ürün tanımlandı."

        except Exception as e:
            conn.close()
            return False, f"Hata oluştu: {str(e)}"

    # --- YEDEKLEME SİSTEMİ ---
    @staticmethod
    def backup_db():
        db_name = current_app.config['DB_NAME']
        backup_folder = "yedekler"
        if not os.path.exists(backup_folder):
            os.makedirs(backup_folder)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_name = f"{db_name.split('.')[0]}_{timestamp}.db"
        destination = os.path.join(backup_folder, backup_name)
        try:
            shutil.copy2(db_name, destination)
            DatabaseManager.clean_old_backups(backup_folder, keep=30)
            return True, f"Yedek alındı: {backup_name}"
        except Exception as e:
            return False, f"Yedekleme hatası: {str(e)}"

    @staticmethod
    def clean_old_backups(folder, keep=30):
        try:
            files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith('.db')]
            files.sort(key=os.path.getctime)
            if len(files) > keep:
                files_to_delete = files[:len(files) - keep]
                for f in files_to_delete:
                    try: os.remove(f)
                    except: pass
        except Exception as e:
            print(f"Yedek temizleme hatası: {e}")

    # --- DİĞER STANDART FONKSİYONLAR ---
    @staticmethod
    def get_all_invoices_grouped(tedarikci_id=None, tarih_bas=None, tarih_bit=None):
        conn = DatabaseManager.get_db_connection()
        base_sql = '''
            SELECT f.fatura_no, f.tarih, f.tedarikci_id, t.ad as tedarikci_ad,
                COUNT(f.id) as kalem_sayisi, SUM(f.toplam_adet) as genel_toplam_adet,
                SUM(f.kalan_adet) as genel_kalan_adet, SUM(f.toplam_adet * f.net_maliyet) as fatura_toplam_tutar
            FROM faturalar f
            JOIN tedarikciler t ON f.tedarikci_id = t.id
            WHERE 1=1
        '''
        params = []
        if tedarikci_id:
            base_sql += " AND f.tedarikci_id = ?"
            params.append(tedarikci_id)
        if tarih_bas:
            base_sql += " AND f.tarih >= ?"
            params.append(tarih_bas)
        if tarih_bit:
            base_sql += " AND f.tarih <= ?"
            params.append(tarih_bit)
        base_sql += " GROUP BY f.fatura_no, f.tedarikci_id ORDER BY f.tarih DESC"
        rows = conn.execute(base_sql, params).fetchall()
        conn.close()
        return rows

    @staticmethod
    def delete_invoice_whole(tedarikci_id, fatura_no):
        conn = DatabaseManager.get_db_connection()
        check = conn.execute('SELECT COUNT(*) FROM faturalar WHERE tedarikci_id = ? AND fatura_no = ? AND toplam_adet != kalan_adet', (tedarikci_id, fatura_no)).fetchone()[0]
        if check > 0:
            conn.close()
            return False, "Sevkiyat yapılmış fatura silinemez."
        conn.execute('DELETE FROM faturalar WHERE tedarikci_id = ? AND fatura_no = ?', (tedarikci_id, fatura_no))
        conn.commit()
        conn.close()
        return True, "Fatura silindi."

    @staticmethod
    def get_user_by_id(user_id):
        conn = DatabaseManager.get_db_connection()
        user_data = conn.execute("SELECT * FROM kullanicilar WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if user_data: return User(user_data['id'], user_data['username'], user_data['password'])
        return None

    @staticmethod
    def get_user_by_username(username):
        conn = DatabaseManager.get_db_connection()
        user_data = conn.execute("SELECT * FROM kullanicilar WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user_data: return User(user_data['id'], user_data['username'], user_data['password'])
        return None

    @staticmethod
    def get_dashboard_stats():
        conn = DatabaseManager.get_db_connection()
        toplam_adet = conn.execute("SELECT SUM(kalan_adet) FROM faturalar").fetchone()[0] or 0
        toplam_tutar = conn.execute("SELECT SUM(kalan_adet * net_maliyet) FROM faturalar").fetchone()[0] or 0
        toplam_cesit = conn.execute("SELECT COUNT(DISTINCT urun_id) FROM faturalar WHERE kalan_adet > 0").fetchone()[0] or 0
        ozet = conn.execute('SELECT t.ad, SUM(f.kalan_adet), SUM(f.kalan_adet * f.net_maliyet), t.id FROM faturalar f JOIN tedarikciler t ON f.tedarikci_id = t.id WHERE f.kalan_adet > 0 GROUP BY t.id').fetchall()
        conn.close()
        return toplam_adet, toplam_tutar, toplam_cesit, ozet

    @staticmethod
    def add_baglanti(data):
        adet = int(data['adet'])
        if adet < 1: return 0
        fiyat = float(data['fiyat'])
        if fiyat < 0: return 0
        iskonto = float(data['iskonto'])
        kdv = float(data['kdv'])
        iskontolu_fiyat = fiyat - (fiyat * iskonto / 100)
        net_maliyet = iskontolu_fiyat * (1 + kdv / 100)
        conn = DatabaseManager.get_db_connection()
        conn.execute('INSERT INTO faturalar (tedarikci_id, urun_id, fatura_no, tarih, toplam_adet, kalan_adet, net_maliyet) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                     (data['tedarikci_id'], data['urun_id'], data['fatura_no'], data['tarih'], adet, adet, net_maliyet))
        conn.commit()
        conn.close()
        return net_maliyet

    @staticmethod
    def process_sevkiyat(data):
        cekilecek = int(data['adet'])
        if cekilecek < 1: return False, "Geçersiz miktar."
        conn = DatabaseManager.get_db_connection()
        faturalar = conn.execute('SELECT * FROM faturalar WHERE tedarikci_id = ? AND urun_id = ? AND kalan_adet > 0 ORDER BY tarih ASC, id ASC', (data['tedarikci_id'], data['urun_id'])).fetchall()
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
            conn.execute('INSERT INTO hareketler (fatura_id, urun_id, tedarikci_id, adet, sevk_no, depo, teslim_alan, tarih) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
                         (fatura['id'], data['urun_id'], data['tedarikci_id'], dusulecek, data['sevk_no'], data['depo'], data['teslim_alan'], data['tarih']))
            kalan_istenen -= dusulecek
        conn.commit()
        conn.close()
        return True, "İşlem Başarılı"

    @staticmethod
    def get_pending_invoices_grouped():
        conn = DatabaseManager.get_db_connection()
        rows = conn.execute('SELECT DISTINCT t.id as tedarikci_id, t.ad as tedarikci_ad, f.fatura_no, f.tarih FROM faturalar f JOIN tedarikciler t ON f.tedarikci_id = t.id WHERE f.kalan_adet > 0 ORDER BY f.tarih ASC').fetchall()
        conn.close()
        return rows

    @staticmethod
    def get_invoice_products(tedarikci_id, fatura_no):
        conn = DatabaseManager.get_db_connection()
        rows = conn.execute('SELECT f.id as fatura_id, u.ad as urun_ad, u.barkod, f.kalan_adet, f.net_maliyet FROM faturalar f JOIN urunler u ON f.urun_id = u.id WHERE f.tedarikci_id = ? AND f.fatura_no = ? AND f.kalan_adet > 0', (tedarikci_id, fatura_no)).fetchall()
        result = [dict(row) for row in rows]
        conn.close()
        return result

    @staticmethod
    def process_invoice_bulk_sevkiyat(data):
        conn = DatabaseManager.get_db_connection()
        fatura_ids = data.getlist('fatura_id[]')
        cekilecek_adetler = data.getlist('adet[]')
        kayit_sayisi = 0
        for i in range(len(fatura_ids)):
            fid = fatura_ids[i]
            adet_str = cekilecek_adetler[i]
            if not adet_str or int(adet_str) <= 0: continue
            adet = int(adet_str)
            fatura = conn.execute("SELECT * FROM faturalar WHERE id = ?", (fid,)).fetchone()
            if not fatura or adet > fatura['kalan_adet']: continue
            conn.execute("UPDATE faturalar SET kalan_adet = ? WHERE id = ?", (fatura['kalan_adet'] - adet, fid))
            conn.execute('INSERT INTO hareketler (fatura_id, urun_id, tedarikci_id, adet, sevk_no, depo, teslim_alan, tarih) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
                         (fid, fatura['urun_id'], fatura['tedarikci_id'], adet, data['sevk_no'], data['depo'], data['teslim_alan'], data['tarih']))
            kayit_sayisi += 1
        conn.commit()
        conn.close()
        return True, f"{kayit_sayisi} kalem ürün başarıyla sevkedildi." if kayit_sayisi > 0 else (False, "İşlem yapılmadı.")

    @staticmethod
    def delete_movement(hareket_id):
        conn = DatabaseManager.get_db_connection()
        hareket = conn.execute("SELECT * FROM hareketler WHERE id = ?", (hareket_id,)).fetchone()
        if not hareket:
            conn.close()
            return False, "Hareket bulunamadı."
        fatura = conn.execute("SELECT * FROM faturalar WHERE id = ?", (hareket['fatura_id'],)).fetchone()
        if not fatura:
            conn.close()
            return False, "Fatura silinmiş."
        conn.execute("UPDATE faturalar SET kalan_adet = ? WHERE id = ?", (fatura['kalan_adet'] + hareket['adet'], hareket['fatura_id']))
        conn.execute("DELETE FROM hareketler WHERE id = ?", (hareket_id,))
        conn.commit()
        conn.close()
        return True, "İşlem geri alındı."

    @staticmethod
    def get_grouped_movements(filtre_tedarikci=None, filtre_urun=None):
        conn = DatabaseManager.get_db_connection()
        sql = 'SELECT h.sevk_no, h.tarih, h.depo, h.teslim_alan, t.ad as tedarikci, COUNT(h.id) as kalem_sayisi, SUM(h.adet) as toplam_adet FROM hareketler h JOIN tedarikciler t ON h.tedarikci_id = t.id WHERE 1=1'
        params = []
        if filtre_tedarikci: sql += " AND h.tedarikci_id = ?"; params.append(filtre_tedarikci)
        if filtre_urun: sql += " AND h.urun_id = ?"; params.append(filtre_urun)
        sql += " GROUP BY h.sevk_no, h.tarih ORDER BY h.id DESC"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows

    @staticmethod
    def get_movement_details_by_sevk(sevk_no):
        conn = DatabaseManager.get_db_connection()
        rows = conn.execute('SELECT h.id, u.ad as urun_ad, h.adet, h.depo, h.teslim_alan FROM hareketler h JOIN urunler u ON h.urun_id = u.id WHERE h.sevk_no = ?', (sevk_no,)).fetchall()
        conn.close()
        return [dict(row) for row in rows]

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
            return False, "Sevkiyat yapılmış fatura silinemez."
        conn.execute("DELETE FROM faturalar WHERE id = ?", (fatura_id,))
        conn.commit()
        conn.close()
        return True, "Fatura silindi."

    @staticmethod
    def update_fatura(fatura_id, data):
        conn = DatabaseManager.get_db_connection()
        fatura = conn.execute("SELECT toplam_adet, kalan_adet FROM faturalar WHERE id = ?", (fatura_id,)).fetchone()
        mal_cekilmis = fatura['toplam_adet'] != fatura['kalan_adet']
        yeni_adet = int(data['adet'])
        if yeni_adet < 1:
            conn.close()
            return False, "Adet en az 1 olmalı."
        if mal_cekilmis and yeni_adet != fatura['toplam_adet']:
            conn.close()
            return False, "Mal çıkışı yapılmış, adet değiştirilemez!"
        
        yeni_kalan = fatura['kalan_adet'] if mal_cekilmis else yeni_adet
        fiyat = float(data['fiyat'])
        iskonto = float(data['iskonto'])
        kdv = float(data['kdv'])
        iskontolu_fiyat = fiyat - (fiyat * iskonto / 100)
        net_maliyet = iskontolu_fiyat * (1 + kdv / 100)
        
        conn.execute('UPDATE faturalar SET fatura_no=?, tarih=?, toplam_adet=?, kalan_adet=?, net_maliyet=? WHERE id=?', 
                     (data['fatura_no'], data['tarih'], yeni_adet, yeni_kalan, net_maliyet, fatura_id))
        conn.commit()
        conn.close()
        return True, "Fatura güncellendi."

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
            return False, "İşlem görmüş tedarikçi silinemez."
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
            return False, "İşlem görmüş ürün silinemez."
        conn.execute("DELETE FROM urunler WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return True, "Ürün silindi."