import os
import pandas as pd
from io import BytesIO
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from app.models import DatabaseManager

main = Blueprint('main', __name__)

# --- DOSYA YÜKLEME AYARLARI ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    toplam_adet, toplam_tutar, toplam_cesit, ozet = DatabaseManager.get_dashboard_stats()
    return render_template('dashboard.html', 
                         toplam_adet=toplam_adet, 
                         toplam_tutar=toplam_tutar, 
                         toplam_cesit=toplam_cesit,
                         ozet=ozet)

# --- YEDEKLEME ---
@main.route('/yedek-al')
@login_required
def yedek_al():
    success, msg = DatabaseManager.backup_db()
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('main.tanimlar'))

# --- EXCEL İŞLEMLERİ (YÜKLEME VE ŞABLON İNDİRME) ---

@main.route('/sablon-indir')
@login_required
def sablon_indir():
    # Şablon için gerekli sütunlar
    columns = ['barkod', 'urun_adi', 'tedarikci', 'fatura_no', 'tarih', 'adet', 'birim_fiyat', 'iskonto', 'kdv']
    
    # Boş bir DataFrame oluştur
    df = pd.DataFrame(columns=columns)
    
    # Bellekte (RAM) Excel dosyası oluştur
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sablon')
        
        # Sütun genişliklerini ayarla (Estetik için)
        worksheet = writer.sheets['Sablon']
        for idx, col in enumerate(columns):
            worksheet.column_dimensions[chr(65 + idx)].width = 20

    output.seek(0)
    
    return send_file(output, 
                     download_name='stok_giris_sablonu.xlsx', 
                     as_attachment=True, 
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@main.route('/excel-yukle', methods=['GET', 'POST'])
@login_required
def excel_yukle():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Dosya seçilmedi.', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('Dosya seçilmedi.', 'danger')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Modeldeki fonksiyonu çağır
            success, msg = DatabaseManager.import_from_excel(filepath)
            
            try:
                os.remove(filepath)
            except:
                pass
            
            flash(msg, 'success' if success else 'danger')
            return redirect(url_for('main.excel_yukle'))
            
    return render_template('excel_yukle.html')

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
    ad = request.form['ad'].strip()
    
    existing = conn.execute("SELECT * FROM tedarikciler WHERE ad = ?", (ad,)).fetchone()
    if existing:
        conn.close()
        flash('Bu isimde bir tedarikçi zaten var!', 'danger')
        return redirect(url_for('main.tanimlar'))
        
    conn.execute("INSERT INTO tedarikciler (ad) VALUES (?)", (ad,))
    conn.commit()
    conn.close()
    flash('Tedarikçi eklendi.', 'success')
    return redirect(url_for('main.tanimlar'))

@main.route('/tedarikci-duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def tedarikci_duzenle(id):
    if request.method == 'POST':
        ad = request.form['ad'].strip()
        DatabaseManager.update_tedarikci(id, ad)
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
    barkod = request.form['barkod'].strip()
    ad = request.form['ad'].strip()
    
    conn = DatabaseManager.get_db_connection()
    mevcut_urun = conn.execute("SELECT * FROM urunler WHERE barkod = ?", (barkod,)).fetchone()
    
    if mevcut_urun:
        conn.close()
        flash(f"HATA: Bu barkod ({barkod}) zaten '{mevcut_urun['ad']}' ismiyle kayıtlı!", 'danger')
        return redirect(url_for('main.tanimlar'))

    conn.execute("INSERT INTO urunler (barkod, ad) VALUES (?, ?)", (barkod, ad))
    conn.commit()
    conn.close()
    flash('Ürün başarıyla eklendi.', 'success')
    return redirect(url_for('main.tanimlar'))

@main.route('/urun-duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def urun_duzenle(id):
    if request.method == 'POST':
        yeni_barkod = request.form['barkod'].strip()
        yeni_ad = request.form['ad'].strip()
        conn = DatabaseManager.get_db_connection()
        kontrol = conn.execute("SELECT * FROM urunler WHERE barkod = ? AND id != ?", (yeni_barkod, id)).fetchone()
        
        if kontrol:
            conn.close()
            flash(f"HATA: Bu barkod ({yeni_barkod}) zaten '{kontrol['ad']}' ürününe ait.", 'danger')
            return redirect(url_for('main.urun_duzenle', id=id))
        
        conn.close()
        DatabaseManager.update_urun(id, yeni_barkod, yeni_ad)
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
    fatura_no = request.form.get('fatura_no').strip()
    tarih = request.form.get('tarih')
    
    conn = DatabaseManager.get_db_connection()
    mevcut_fatura = conn.execute(
        "SELECT id FROM faturalar WHERE tedarikci_id = ? AND fatura_no = ?", 
        (tedarikci_id, fatura_no)
    ).fetchone()
    conn.close()

    if mevcut_fatura:
        flash(f"HATA: {fatura_no} numaralı fatura bu tedarikçi için zaten daha önce kaydedilmiş!", "danger")
        return redirect(url_for('main.baglanti_yap'))
    
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

@main.route('/hareketler')
@login_required
def hareketler():
    filtre_tedarikci = request.args.get('tedarikci')
    filtre_urun = request.args.get('urun')
    hareket_listesi = DatabaseManager.get_grouped_movements(filtre_tedarikci, filtre_urun)
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    urunler = conn.execute("SELECT * FROM urunler ORDER BY ad").fetchall()
    conn.close()
    return render_template('hareketler.html', hareketler=hareket_listesi, tedarikciler=tedarikciler, urunler=urunler, secili_tedarikci=filtre_tedarikci, secili_urun=filtre_urun)

@main.route('/hareket-sil/<int:id>')
@login_required
def hareket_sil(id):
    success, msg = DatabaseManager.delete_movement(id)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('main.hareketler'))

@main.route('/api/hareket-detay', methods=['POST'])
@login_required
def get_hareket_detay():
    data = request.get_json()
    sevk_no = data.get('sevk_no')
    detaylar = DatabaseManager.get_movement_details_by_sevk(sevk_no)
    return jsonify(detaylar)

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

    base_aktif = 'SELECT f.id, t.ad as tedarikci, u.ad as urun, f.tarih, f.fatura_no, f.net_maliyet, f.toplam_adet, f.kalan_adet as kalan FROM faturalar f JOIN tedarikciler t ON f.tedarikci_id = t.id JOIN urunler u ON f.urun_id = u.id WHERE f.kalan_adet > 0'
    sql_aktif, params_aktif = build_query(base_aktif)
    sql_aktif += " ORDER BY t.ad, u.ad, f.tarih"
    aktif_data = conn.execute(sql_aktif, params_aktif).fetchall()
    
    genel_toplam = sum(r['net_maliyet'] * r['kalan'] for r in aktif_data)
    toplam_alinan = sum(r['toplam_adet'] for r in aktif_data)
    toplam_kalan = sum(r['kalan'] for r in aktif_data)

    base_gecmis = 'SELECT f.id, t.ad as tedarikci, u.ad as urun, f.tarih, f.fatura_no, f.net_maliyet, f.toplam_adet, f.kalan_adet as kalan FROM faturalar f JOIN tedarikciler t ON f.tedarikci_id = t.id JOIN urunler u ON f.urun_id = u.id WHERE f.kalan_adet = 0'
    sql_gecmis, params_gecmis = build_query(base_gecmis)
    sql_gecmis += " ORDER BY f.tarih DESC"
    gecmis_data = conn.execute(sql_gecmis, params_gecmis).fetchall()
    conn.close()
    
    return render_template('rapor.html', aktif_baglantilar=aktif_data, gecmis_baglantilar=gecmis_data, genel_toplam=genel_toplam, toplam_alinan=toplam_alinan, toplam_kalan=toplam_kalan, tedarikciler=tedarikciler, urunler=urunler, secili_tedarikci=filtre_tedarikci, secili_urun=filtre_urun)

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

@main.route('/faturalar')
@login_required
def faturalar():
    tedarikci_id = request.args.get('tedarikci_id')
    tarih_bas = request.args.get('tarih_bas')
    tarih_bit = request.args.get('tarih_bit')
    grouped_invoices = DatabaseManager.get_all_invoices_grouped(tedarikci_id, tarih_bas, tarih_bit)
    conn = DatabaseManager.get_db_connection()
    tedarikciler = conn.execute("SELECT * FROM tedarikciler ORDER BY ad").fetchall()
    conn.close()
    return render_template('faturalar.html', faturalar=grouped_invoices, tedarikciler=tedarikciler, secili_tedarikci=tedarikci_id, tarih_bas=tarih_bas, tarih_bit=tarih_bit)

@main.route('/fatura-sil-komple', methods=['POST'])
@login_required
def fatura_sil_komple():
    tedarikci_id = request.form.get('tedarikci_id')
    fatura_no = request.form.get('fatura_no')
    success, msg = DatabaseManager.delete_invoice_whole(tedarikci_id, fatura_no)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('main.faturalar'))