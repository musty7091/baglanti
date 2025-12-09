from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from datetime import datetime
from app.models import DatabaseManager

main = Blueprint('main', __name__)

# --- LOGIN / LOGOUT ---

@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
        
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = DatabaseManager.get_user_by_username(username)
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('main.index'))
        else:
            flash('Kullanıcı adı veya şifre hatalı.', 'danger')
            
    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Çıkış yapıldı.', 'info')
    return redirect(url_for('main.login'))

# --- ANA SAYFALAR ---

@main.route('/')
@login_required
def index():
    toplam_adet, toplam_tutar, ozet = DatabaseManager.get_dashboard_stats()
    return render_template('dashboard.html', toplam_adet=toplam_adet, toplam_tutar=toplam_tutar, ozet=ozet)

@main.route('/tanimlar')
@login_required
def tanimlar():
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('tanimlar.html', tedarikciler=tedarikciler, urunler=urunler)

@main.route('/tedarikci-ekle', methods=['POST'])
@login_required
def tedarikci_ekle():
    conn = DatabaseManager.get_db_connection()
    conn.execute("INSERT INTO tedarikciler (ad) VALUES (?)", (request.form['ad'],))
    conn.commit()
    conn.close()
    flash('Tedarikçi eklendi.', 'success')
    return redirect(url_for('main.tanimlar'))

@main.route('/urun-ekle', methods=['POST'])
@login_required
def urun_ekle():
    conn = DatabaseManager.get_db_connection()
    conn.execute("INSERT INTO urunler (barkod, ad) VALUES (?, ?)", (request.form['barkod'], request.form['ad']))
    conn.commit()
    conn.close()
    flash('Ürün eklendi.', 'success')
    return redirect(url_for('main.tanimlar'))

@main.route('/baglanti-yap')
@login_required
def baglanti_yap():
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('baglanti.html', tedarikciler=tedarikciler, urunler=urunler, bugun=datetime.now().strftime('%Y-%m-%d'))

@main.route('/baglanti-kaydet', methods=['POST'])
@login_required
def baglanti_kaydet():
    maliyet = DatabaseManager.add_baglanti(request.form)
    flash(f"Bağlantı kaydedildi. Birim Maliyet: {maliyet:.2f} TL", 'success')
    return redirect(url_for('main.baglanti_yap'))

@main.route('/mal-cek')
@login_required
def mal_cek():
    secili_tedarikci = request.args.get('tedarikci_id', type=int)
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('mal_cek.html', tedarikciler=tedarikciler, urunler=urunler, secili_tedarikci=secili_tedarikci, bugun=datetime.now().strftime('%Y-%m-%d'))

@main.route('/mal-cek-kaydet', methods=['POST'])
@login_required
def mal_cek_kaydet():
    success, message = DatabaseManager.process_sevkiyat(request.form)
    if success:
        flash(message, 'success')
        return redirect(url_for('main.index'))
    else:
        flash(message, 'danger')
        return redirect(url_for('main.mal_cek'))

@main.route('/rapor')
@login_required
def rapor():
    conn = DatabaseManager.get_db_connection()
    filtre_tedarikci = request.args.get('tedarikci')
    filtre_urun = request.args.get('urun')
    
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    
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

    # ID'yi de çekiyoruz ki Sil/Düzenle yapabilelim (f.id)
    base_aktif = '''
        SELECT f.id, t.ad as tedarikci, u.ad as urun, f.tarih, f.fatura_no, f.net_maliyet, f.toplam_adet, f.kalan_adet as kalan
        FROM faturalar f
        JOIN tedarikciler t ON f.tedarikci_id = t.id
        JOIN urunler u ON f.urun_id = u.id
        WHERE f.kalan_adet > 0
    '''
    sql_aktif, params_aktif = build_query(base_aktif)
    sql_aktif += " ORDER BY t.ad, u.ad, f.tarih"
    
    aktif_data = conn.execute(sql_aktif, params_aktif).fetchall()
    genel_toplam = sum(r['net_maliyet'] * r['kalan'] for r in aktif_data)

    base_gecmis = '''
        SELECT f.id, t.ad as tedarikci, u.ad as urun, f.tarih, f.fatura_no, f.net_maliyet, f.toplam_adet, f.kalan_adet as kalan
        FROM faturalar f
        JOIN tedarikciler t ON f.tedarikci_id = t.id
        JOIN urunler u ON f.urun_id = u.id
        WHERE f.kalan_adet = 0
    '''
    sql_gecmis, params_gecmis = build_query(base_gecmis)
    sql_gecmis += " ORDER BY f.tarih DESC"
    
    gecmis_data = conn.execute(sql_gecmis, params_gecmis).fetchall()
    
    base_hareket = '''
        SELECT h.tarih, t.ad as tedarikci, u.ad as urun, h.adet, h.sevk_no, h.depo, h.teslim_alan as alan
        FROM hareketler h
        JOIN tedarikciler t ON h.tedarikci_id = t.id
        JOIN urunler u ON h.urun_id = u.id
        WHERE 1=1
    '''
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

# --- SİLME VE DÜZENLEME ROUTE'LARI ---

@main.route('/fatura-sil/<int:id>')
@login_required
def fatura_sil(id):
    success, msg = DatabaseManager.delete_fatura(id)
    if success:
        flash(msg, 'success')
    else:
        flash(msg, 'danger')
    return redirect(url_for('main.rapor'))

@main.route('/fatura-duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def fatura_duzenle(id):
    if request.method == 'POST':
        success, msg = DatabaseManager.update_fatura(id, request.form)
        if success:
            flash(msg, 'success')
            return redirect(url_for('main.rapor'))
        else:
            flash(msg, 'danger')
    
    fatura = DatabaseManager.get_fatura(id)
    return render_template('fatura_duzenle.html', f=fatura)