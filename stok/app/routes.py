from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from app.models import DatabaseManager

main = Blueprint('main', __name__)

@main.route('/')
def index():
    toplam_adet, toplam_tutar, ozet = DatabaseManager.get_dashboard_stats()
    return render_template('dashboard.html', toplam_adet=toplam_adet, toplam_tutar=toplam_tutar, ozet=ozet)

@main.route('/tanimlar')
def tanimlar():
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('tanimlar.html', tedarikciler=tedarikciler, urunler=urunler)

@main.route('/tedarikci-ekle', methods=['POST'])
def tedarikci_ekle():
    conn = DatabaseManager.get_db_connection()
    conn.execute("INSERT INTO tedarikciler (ad) VALUES (?)", (request.form['ad'],))
    conn.commit()
    conn.close()
    flash('Tedarikçi eklendi.', 'success')
    return redirect(url_for('main.tanimlar'))

@main.route('/urun-ekle', methods=['POST'])
def urun_ekle():
    conn = DatabaseManager.get_db_connection()
    conn.execute("INSERT INTO urunler (barkod, ad) VALUES (?, ?)", (request.form['barkod'], request.form['ad']))
    conn.commit()
    conn.close()
    flash('Ürün eklendi.', 'success')
    return redirect(url_for('main.tanimlar'))

@main.route('/baglanti-yap')
def baglanti_yap():
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('baglanti.html', tedarikciler=tedarikciler, urunler=urunler, bugun=datetime.now().strftime('%Y-%m-%d'))

@main.route('/baglanti-kaydet', methods=['POST'])
def baglanti_kaydet():
    maliyet = DatabaseManager.add_baglanti(request.form)
    flash(f"Bağlantı kaydedildi. Birim Maliyet: {maliyet:.2f} TL", 'success')
    return redirect(url_for('main.baglanti_yap'))

@main.route('/mal-cek')
def mal_cek():
    secili_tedarikci = request.args.get('tedarikci_id', type=int)
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('mal_cek.html', tedarikciler=tedarikciler, urunler=urunler, secili_tedarikci=secili_tedarikci, bugun=datetime.now().strftime('%Y-%m-%d'))

@main.route('/mal-cek-kaydet', methods=['POST'])
def mal_cek_kaydet():
    success, message = DatabaseManager.process_sevkiyat(request.form)
    if success:
        flash(message, 'success')
        return redirect(url_for('main.index'))
    else:
        flash(message, 'danger')
        return redirect(url_for('main.mal_cek'))

@main.route('/rapor')
def rapor():
    conn = DatabaseManager.get_db_connection()
    
    # Filtre Parametrelerini Al
    filtre_tedarikci = request.args.get('tedarikci')
    filtre_urun = request.args.get('urun')
    
    # Dropdownlar için listeleri çek (Sayfadaki filtre kutuları için)
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    
    # --- Dinamik Sorgu Oluşturma (SQL Builder) ---
    def build_query(base_sql, table_alias='f'):
        clauses = []
        params = []
        
        if filtre_tedarikci:
            clauses.append(f"AND {table_alias}.tedarikci_id = ?")
            params.append(filtre_tedarikci)
        
        if filtre_urun:
            clauses.append(f"AND {table_alias}.urun_id = ?")
            params.append(filtre_urun)
            
        full_sql = base_sql + " " + " ".join(clauses)
        return full_sql, params

    # 1. Aktif (Bekleyen) Bakiyeler
    base_aktif = '''
        SELECT t.ad as tedarikci, u.ad as urun, f.tarih, f.fatura_no, f.net_maliyet, f.toplam_adet, f.kalan_adet as kalan
        FROM faturalar f
        JOIN tedarikciler t ON f.tedarikci_id = t.id
        JOIN urunler u ON f.urun_id = u.id
        WHERE f.kalan_adet > 0
    '''
    sql_aktif, params_aktif = build_query(base_aktif)
    sql_aktif += " ORDER BY t.ad, u.ad, f.tarih" # Sıralamayı en sona ekle
    
    aktif_data = conn.execute(sql_aktif, params_aktif).fetchall()
    genel_toplam = sum(r['net_maliyet'] * r['kalan'] for r in aktif_data)

    # 2. Tamamlanan (Geçmiş/Sıfırlanmış) Bağlantılar
    base_gecmis = '''
        SELECT t.ad as tedarikci, u.ad as urun, f.tarih, f.fatura_no, f.net_maliyet, f.toplam_adet, f.kalan_adet as kalan
        FROM faturalar f
        JOIN tedarikciler t ON f.tedarikci_id = t.id
        JOIN urunler u ON f.urun_id = u.id
        WHERE f.kalan_adet = 0
    '''
    sql_gecmis, params_gecmis = build_query(base_gecmis)
    sql_gecmis += " ORDER BY f.tarih DESC"
    
    gecmis_data = conn.execute(sql_gecmis, params_gecmis).fetchall()
    
    # 3. Son Sevk Hareketleri (Buna da filtre uygulayalım ki tam olsun)
    base_hareket = '''
        SELECT h.tarih, t.ad as tedarikci, u.ad as urun, h.adet, h.sevk_no, h.depo, h.teslim_alan as alan
        FROM hareketler h
        JOIN tedarikciler t ON h.tedarikci_id = t.id
        JOIN urunler u ON h.urun_id = u.id
        WHERE 1=1
    '''
    # Hareket tablosunda alias 'h' olduğu için fonksiyonu ona göre çağırıyoruz
    sql_hareket, params_hareket = build_query(base_hareket, table_alias='h')
    sql_hareket += " ORDER BY h.id DESC LIMIT 50"

    hareketler = conn.execute(sql_hareket, params_hareket).fetchall()
    
    conn.close()
    
    return render_template('rapor.html', 
                         aktif_baglantilar=aktif_data, 
                         gecmis_baglantilar=gecmis_data,
                         genel_toplam=genel_toplam, 
                         hareketler=hareketler,
                         tedarikciler=tedarikciler,
                         urunler=urunler,
                         secili_tedarikci=filtre_tedarikci,
                         secili_urun=filtre_urun)
