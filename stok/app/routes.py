from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
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
    # Artık 4 değer dönüyor
    toplam_adet, toplam_tutar, toplam_cesit, ozet = DatabaseManager.get_dashboard_stats()
    
    return render_template('dashboard.html', 
                         toplam_adet=toplam_adet, 
                         toplam_tutar=toplam_tutar, 
                         toplam_cesit=toplam_cesit, # Yeni veri
                         ozet=ozet)

# --- TANIMLAR ---
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

@main.route('/tedarikci-duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def tedarikci_duzenle(id):
    if request.method == 'POST':
        DatabaseManager.update_tedarikci(id, request.form['ad'])
        flash('Tedarikçi güncellendi.', 'success')
        return redirect(url_for('main.tanimlar'))
    t = DatabaseManager.get_tedarikci(id)
    return render_template('tanim_duzenle.html', type='tedarikci', data=t)

@main.route('/tedarikci-sil/<int:id>')
@login_required
def tedarikci_sil(id):
    success, msg = DatabaseManager.delete_tedarikci(id)
    flash(msg, 'success' if success else 'danger')
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

@main.route('/urun-duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def urun_duzenle(id):
    if request.method == 'POST':
        DatabaseManager.update_urun(id, request.form['barkod'], request.form['ad'])
        flash('Ürün güncellendi.', 'success')
        return redirect(url_for('main.tanimlar'))
    u = DatabaseManager.get_urun(id)
    return render_template('tanim_duzenle.html', type='urun', data=u)

@main.route('/urun-sil/<int:id>')
@login_required
def urun_sil(id):
    success, msg = DatabaseManager.delete_urun(id)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('main.tanimlar'))

# --- BAĞLANTI (GİRİŞ) ---
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
    tedarikci_id = request.form.get('tedarikci_id')
    fatura_no = request.form.get('fatura_no')
    tarih = request.form.get('tarih')
    
    urun_ids = request.form.getlist('urun_id[]')
    adetler = request.form.getlist('adet[]')
    fiyatlar = request.form.getlist('fiyat[]')
    iskontolar = request.form.getlist('iskonto[]')
    kdvler = request.form.getlist('kdv[]')
    
    if not urun_ids:
        flash("Lütfen en az bir ürün ekleyin.", "danger")
        return redirect(url_for('main.baglanti_yap'))

    kayit_sayisi = 0
    for i in range(len(urun_ids)):
        if not urun_ids[i] or not adetler[i]: continue
            
        data = {
            'tedarikci_id': tedarikci_id,
            'fatura_no': fatura_no,
            'tarih': tarih,
            'urun_id': urun_ids[i],
            'adet': adetler[i],
            'fiyat': fiyatlar[i],
            'iskonto': iskontolar[i] or 0,
            'kdv': kdvler[i] or 20
        }
        DatabaseManager.add_baglanti(data)
        kayit_sayisi += 1
        
    flash(f"{kayit_sayisi} kalem ürün başarıyla kaydedildi.", 'success')
    return redirect(url_for('main.baglanti_yap'))

# --- MAL ÇIKIŞI (FIFO & TOPLU) ---
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
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('main.index') if success else url_for('main.mal_cek'))

@main.route('/toplu-cikis')
@login_required
def toplu_cikis():
    faturalar = DatabaseManager.get_pending_invoices_grouped()
    return render_template('toplu_cikis.html', faturalar=faturalar, bugun=datetime.now().strftime('%Y-%m-%d'))

@main.route('/api/fatura-detay', methods=['POST'])
@login_required
def get_fatura_detay():
    data = request.get_json()
    tedarikci_id = data.get('tedarikci_id')
    fatura_no = data.get('fatura_no')
    urunler = DatabaseManager.get_invoice_products(tedarikci_id, fatura_no)
    return jsonify(urunler)

@main.route('/toplu-cikis-kaydet', methods=['POST'])
@login_required
def toplu_cikis_kaydet():
    success, msg = DatabaseManager.process_invoice_bulk_sevkiyat(request.form)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('main.index') if success else url_for('main.toplu_cikis'))

# --- RAPOR & DÜZENLEME ---
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

@main.route('/fatura-sil/<int:id>')
@login_required
def fatura_sil(id):
    success, msg = DatabaseManager.delete_fatura(id)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('main.rapor'))

@main.route('/fatura-duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def fatura_duzenle(id):
    if request.method == 'POST':
        success, msg = DatabaseManager.update_fatura(id, request.form)
        flash(msg, 'success' if success else 'danger')
        return redirect(url_for('main.rapor') if success else url_for('main.fatura_duzenle', id=id))
    fatura = DatabaseManager.get_fatura(id)
    return render_template('fatura_duzenle.html', f=fatura)