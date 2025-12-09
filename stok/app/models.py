import sqlite3
from flask import current_app

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
        
        # Tabloları oluştur
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
        conn.commit()
        conn.close()

    # --- İş Mantığı Metodları (Business Logic) ---
    
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
        # Maliyet hesaplama mantığı burada
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
        # FIFO ve Stok Düşme Mantığı
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
