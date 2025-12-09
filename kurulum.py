import os

# Proje Ana Klasörü
PROJECT_NAME = "stok_projesi_v2"

# Dosya Yapısı ve İçerikleri
files = {
    # 1. Giriş Noktası
    f"{PROJECT_NAME}/run.py": """from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
""",

    # 2. Ayarlar
    f"{PROJECT_NAME}/config.py": """import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'cok-gizli-anahtar-degistirilecek'
    DB_NAME = "stok_takip.db"
""",

    # 3. Uygulama Fabrikası (__init__)
    f"{PROJECT_NAME}/app/__init__.py": """from flask import Flask
from config import Config

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Veritabanı başlatıcıyı import et
    from app.models import DatabaseManager
    DatabaseManager.init_db(app.config['DB_NAME'])

    # Blueprint'leri (Route'ları) kaydet
    from app.routes import main
    app.register_blueprint(main)

    return app
""",

    # 4. Modeller (Veritabanı ve İş Mantığı)
    f"{PROJECT_NAME}/app/models.py": """import sqlite3
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
""",

    # 5. Route'lar (Yönlendirmeler - FİLTRELEME MANTIĞI EKLENDİ)
    f"{PROJECT_NAME}/app/routes.py": """from flask import Blueprint, render_template, request, redirect, url_for, flash
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
""",

    # 6. Gereksinimler
    f"{PROJECT_NAME}/requirements.txt": """Flask
""",

    # 7. Beni Oku (Kurulum Talimatları)
    f"{PROJECT_NAME}/BENI_OKU.txt": """--- KURULUM VE ÇALIŞTIRMA ---

1. Terminali açın ve proje klasörüne girin:
   cd stok_projesi_v2

2. (Opsiyonel ama önerilir) Sanal ortam oluşturun:
   python -m venv venv
   # Windows için:
   venv\\Scripts\\activate
   # Mac/Linux için:
   source venv/bin/activate

3. Gerekli paketleri yükleyin:
   pip install -r requirements.txt

4. Projeyi çalıştırın:
   python run.py

5. Tarayıcınızda şu adresi açın:
   http://127.0.0.1:5000/
""",

    # --- HTML ŞABLONLARI ---

    f"{PROJECT_NAME}/app/templates/base.html": """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tedarikçi Bakiye Takip Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .card { box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: none; margin-bottom: 20px; }
        .navbar { background-color: #2c3e50; }
        .navbar-brand { color: white !important; font-weight: bold; }
        .nav-link { color: rgba(255,255,255,0.8) !important; }
        .nav-link:hover { color: white !important; }
        @media print {
            .btn, .navbar, .no-print { display: none !important; }
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container">
            <a class="navbar-brand" href="/">🍷 Stok Pro v2</a>
            <div class="collapse navbar-collapse">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('main.index') }}">Özet</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('main.tanimlar') }}">Tanımlar</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('main.baglanti_yap') }}">Bağlantı</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('main.mal_cek') }}">Sevkiyat</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('main.rapor') }}">Rapor</a></li>
                </ul>
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
""",

    f"{PROJECT_NAME}/app/templates/dashboard.html": """{% extends "base.html" %}
{% block content %}
<div class="row">
    <div class="col-md-4">
        <div class="card text-white bg-primary h-100">
            <div class="card-body">
                <h5 class="card-title">Bekleyen Stok</h5>
                <h2 class="display-6">{{ toplam_adet }} Adet</h2>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card text-white bg-success h-100">
            <div class="card-body">
                <h5 class="card-title">Toplam Değer</h5>
                <h2 class="display-6">{{ "{:,.2f}".format(toplam_tutar) }} TL</h2>
            </div>
        </div>
    </div>
</div>
<div class="row mt-4">
    <div class="col-md-12">
        <div class="card">
            <div class="card-header">Tedarikçi Özeti</div>
            <div class="card-body">
                <table class="table">
                    <thead><tr><th>Tedarikçi</th><th>Adet</th><th>Değer</th><th>İşlem</th></tr></thead>
                    <tbody>
                        {% for row in ozet %}
                        <tr>
                            <td>{{ row[0] }}</td>
                            <td>{{ row[1] }}</td>
                            <td>{{ "{:,.2f}".format(row[2]) }} TL</td>
                            <td><a href="{{ url_for('main.mal_cek', tedarikci_id=row[3]) }}" class="btn btn-sm btn-outline-primary">Mal Çek</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",

    f"{PROJECT_NAME}/app/templates/tanimlar.html": """{% extends "base.html" %}
{% block content %}
<div class="row">
    <!-- Tedarikçi Ekleme -->
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">Yeni Tedarikçi Tanımla</div>
            <div class="card-body">
                <form action="{{ url_for('main.tedarikci_ekle') }}" method="POST">
                    <div class="mb-3">
                        <label>Firma Adı</label>
                        <input type="text" name="ad" class="form-control" required placeholder="Örn: Mey İçki">
                    </div>
                    <button type="submit" class="btn btn-success">Kaydet</button>
                </form>
            </div>
        </div>
        
        <h6 class="mt-4">Mevcut Tedarikçiler</h6>
        <ul class="list-group">
            {% for t in tedarikciler %}
            <li class="list-group-item d-flex justify-content-between align-items-center">
                {{ t['ad'] }}
            </li>
            {% endfor %}
        </ul>
    </div>

    <!-- Ürün Ekleme -->
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">Yeni Ürün Tanımla</div>
            <div class="card-body">
                <form action="{{ url_for('main.urun_ekle') }}" method="POST">
                    <div class="mb-3">
                        <label>Barkod</label>
                        <input type="text" name="barkod" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label>Ürün Adı</label>
                        <input type="text" name="ad" class="form-control" required placeholder="Örn: X Votka 70cl">
                    </div>
                    <button type="submit" class="btn btn-primary">Kaydet</button>
                </form>
            </div>
        </div>
        
        <h6 class="mt-4">Kayıtlı Ürünler</h6>
        <div style="max-height: 300px; overflow-y: auto;">
            <ul class="list-group">
                {% for u in urunler %}
                <li class="list-group-item">
                    <small class="text-muted">{{ u['barkod'] }}</small><br>
                    <strong>{{ u['ad'] }}</strong>
                </li>
                {% endfor %}
            </ul>
        </div>
    </div>
</div>
{% endblock %}
""",

    f"{PROJECT_NAME}/app/templates/baglanti.html": """{% extends "base.html" %}
{% block content %}
<div class="card">
    <div class="card-header bg-primary text-white">
        <h4 class="mb-0">Yeni Bağlantı Girişi (Mal Alımı)</h4>
    </div>
    <div class="card-body">
        <div class="alert alert-info">
            <small>💡 Buraya girdiğin mallar <b>Tedarikçi Bakiyesine</b> eklenecektir. Fiziksel stoğa henüz girmez.</small>
        </div>
        <form action="{{ url_for('main.baglanti_kaydet') }}" method="POST">
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label>Tedarikçi Seç</label>
                    <select name="tedarikci_id" class="form-select" required>
                        <option value="">Seçiniz...</option>
                        {% for t in tedarikciler %}
                        <option value="{{ t['id'] }}">{{ t['ad'] }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="col-md-6 mb-3">
                    <label>Fatura No / Belge No</label>
                    <input type="text" name="fatura_no" class="form-control" required>
                </div>
            </div>
            
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label>Ürün Seç</label>
                    <select name="urun_id" class="form-select" required>
                        <option value="">Seçiniz...</option>
                        {% for u in urunler %}
                        <option value="{{ u['id'] }}">{{ u['barkod'] }} - {{ u['ad'] }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="col-md-6 mb-3">
                    <label>Fatura Tarihi</label>
                    <input type="date" name="tarih" class="form-control" value="{{ bugun }}" required>
                </div>
            </div>

            <hr>
            <h6>Maliyet Hesaplama</h6>
            <div class="row">
                <div class="col-md-3 mb-3">
                    <label>Adet (Miktar)</label>
                    <input type="number" name="adet" class="form-control" required min="1">
                </div>
                <div class="col-md-3 mb-3">
                    <label>Birim Fiyat (KDV Hariç)</label>
                    <input type="number" step="0.01" name="fiyat" class="form-control" required>
                </div>
                <div class="col-md-3 mb-3">
                    <label>İskonto (%)</label>
                    <input type="number" step="0.01" name="iskonto" class="form-control" value="0">
                </div>
                <div class="col-md-3 mb-3">
                    <label>KDV (%)</label>
                    <input type="number" step="0.01" name="kdv" class="form-control" value="20">
                </div>
            </div>

            <button type="submit" class="btn btn-lg btn-success w-100">Bağlantıyı Kaydet</button>
        </form>
    </div>
</div>
{% endblock %}
""",

    f"{PROJECT_NAME}/app/templates/mal_cek.html": """{% extends "base.html" %}
{% block content %}
<div class="card">
    <div class="card-header bg-danger text-white">
        <h4 class="mb-0">Mal Çekimi (Sevkiyat Girişi)</h4>
    </div>
    <div class="card-body">
        <div class="alert alert-warning">
            <small>⚠️ <b>FIFO Modu Aktif:</b> Çekeceğiniz miktar, otomatik olarak en eski tarihli faturadan başlayarak düşülecektir.</small>
        </div>
        
        <form action="{{ url_for('main.mal_cek_kaydet') }}" method="POST">
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label>Hangi Tedarikçiden?</label>
                    <select name="tedarikci_id" class="form-select" onchange="window.location.href='{{ url_for('main.mal_cek') }}?tedarikci_id=' + this.value" required>
                        <option value="">Seçiniz...</option>
                        {% for t in tedarikciler %}
                        <option value="{{ t['id'] }}" {% if secili_tedarikci == t['id'] %}selected{% endif %}>{{ t['ad'] }}</option>
                        {% endfor %}
                    </select>
                </div>
                
                <div class="col-md-6 mb-3">
                    <label>Hangi Ürünü Çekiyorsun?</label>
                    <select name="urun_id" class="form-select" required>
                        <option value="">Seçiniz...</option>
                        {% for u in urunler %}
                            <option value="{{ u['id'] }}">{{ u['barkod'] }} - {{ u['ad'] }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>

            <div class="row">
                <div class="col-md-4 mb-3">
                    <label>Çekilecek Miktar</label>
                    <input type="number" name="adet" class="form-control" required min="1">
                </div>
                <div class="col-md-4 mb-3">
                    <label>Sevk Fişi / İrsaliye No</label>
                    <input type="text" name="sevk_no" class="form-control" required>
                </div>
                <div class="col-md-4 mb-3">
                    <label>Teslim Alan Personel</label>
                    <input type="text" name="teslim_alan" class="form-control" required>
                </div>
            </div>

            <div class="row">
                <div class="col-md-6 mb-3">
                    <label>İneceği Depo</label>
                    <select name="depo" class="form-select" required>
                        <option value="Magaza">Mağaza</option>
                        <option value="Depo1">Depo 1</option>
                        <option value="Depo2">Depo 2</option>
                    </select>
                </div>
                <div class="col-md-6 mb-3">
                    <label>İşlem Tarihi</label>
                    <input type="date" name="tarih" class="form-control" value="{{ bugun }}" required>
                </div>
            </div>

            <button type="submit" class="btn btn-lg btn-danger w-100">Stoktan Düş ve Kaydet</button>
        </form>
    </div>
</div>
{% endblock %}
""",

    # 8. Rapor Şablonu (FİLTRE FORMU EKLENDİ)
    f"{PROJECT_NAME}/app/templates/rapor.html": """{% extends "base.html" %}
{% block content %}

<!-- FİLTRELEME ALANI -->
<div class="card mb-4 no-print">
    <div class="card-body bg-light">
        <form action="{{ url_for('main.rapor') }}" method="GET" class="row g-3 align-items-end">
            <div class="col-md-4">
                <label class="form-label">Tedarikçi Filtresi</label>
                <select name="tedarikci" class="form-select">
                    <option value="">Tümü</option>
                    {% for t in tedarikciler %}
                    <option value="{{ t['id'] }}" {% if secili_tedarikci|string == t['id']|string %}selected{% endif %}>{{ t['ad'] }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-4">
                <label class="form-label">Ürün Filtresi</label>
                <select name="urun" class="form-select">
                    <option value="">Tümü</option>
                    {% for u in urunler %}
                    <option value="{{ u['id'] }}" {% if secili_urun|string == u['id']|string %}selected{% endif %}>{{ u['ad'] }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-4">
                <button type="submit" class="btn btn-primary w-100">Filtrele</button>
            </div>
        </form>
    </div>
</div>

<div class="card mb-4">
    <div class="card-header bg-dark text-white d-flex justify-content-between align-items-center">
        <h4 class="mb-0">Aktif (Bekleyen) Bakiyeler</h4>
        <button class="btn btn-sm btn-light" onclick="window.print()">Yazdır / PDF</button>
    </div>
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-bordered table-striped">
                <thead class="table-dark">
                    <tr>
                        <th>Tedarikçi</th>
                        <th>Ürün</th>
                        <th>Fatura No / Tarih</th>
                        <th>Toplam Alınan</th>
                        <th>Birim Maliyet (Net)</th>
                        <th>Kalan (Alacak)</th>
                        <th>Bakiye Değeri</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in aktif_baglantilar %}
                    <tr>
                        <td>{{ row['tedarikci'] }}</td>
                        <td>{{ row['urun'] }}</td>
                        <td>
                            <div>{{ row['fatura_no'] }}</div>
                            <small class="text-muted">{{ row['tarih'] }}</small>
                        </td>
                        <td class="text-center">{{ row['toplam_adet'] }}</td>
                        <td class="text-end">{{ "{:,.2f}".format(row['net_maliyet']) }} TL</td>
                        <td class="text-center fw-bold text-danger">{{ row['kalan'] }}</td>
                        <td class="text-end fw-bold">{{ "{:,.2f}".format(row['net_maliyet'] * row['kalan']) }} TL</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="text-center">Filtre kriterlerine uygun aktif bakiye bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
                <tfoot class="table-secondary">
                    <tr>
                        <th colspan="6" class="text-end">GENEL TOPLAM DEĞER:</th>
                        <th class="text-end">{{ "{:,.2f}".format(genel_toplam) }} TL</th>
                    </tr>
                </tfoot>
            </table>
        </div>
    </div>
</div>

<div class="card mb-4">
    <div class="card-header bg-secondary text-white">
        <h5 class="mb-0">Tamamlanan (Geçmiş) Bağlantılar</h5>
    </div>
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-bordered table-sm text-muted">
                <thead class="table-light">
                    <tr>
                        <th>Tedarikçi</th>
                        <th>Ürün</th>
                        <th>Fatura No</th>
                        <th>Tarih</th>
                        <th>Alınan</th>
                        <th>Kalan</th>
                        <th>Durum</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in gecmis_baglantilar %}
                    <tr>
                        <td>{{ row['tedarikci'] }}</td>
                        <td>{{ row['urun'] }}</td>
                        <td>{{ row['fatura_no'] }}</td>
                        <td>{{ row['tarih'] }}</td>
                        <td>{{ row['toplam_adet'] }}</td>
                        <td>{{ row['kalan'] }}</td>
                        <td><span class="badge bg-success">Tamamlandı</span></td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="text-center">Geçmiş kayıt bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-header">Son Sevk Hareketleri (Log)</div>
    <div class="card-body">
         <table class="table table-sm">
            <thead>
                <tr>
                    <th>Tarih</th>
                    <th>Tedarikçi</th>
                    <th>Ürün</th>
                    <th>Çekilen Adet</th>
                    <th>Sevk No</th>
                    <th>Depo</th>
                    <th>Teslim Alan</th>
                </tr>
            </thead>
            <tbody>
                {% for log in hareketler %}
                <tr>
                    <td>{{ log['tarih'] }}</td>
                    <td>{{ log['tedarikci'] }}</td>
                    <td>{{ log['urun'] }}</td>
                    <td class="text-danger fw-bold">-{{ log['adet'] }}</td>
                    <td>{{ log['sevk_no'] }}</td>
                    <td>{{ log['depo'] }}</td>
                    <td>{{ log['alan'] }}</td>
                </tr>
                {% endfor %}
            </tbody>
         </table>
    </div>
</div>
{% endblock %}
"""
}

def create_project():
    if not os.path.exists(PROJECT_NAME):
        os.makedirs(PROJECT_NAME)
        
    # Alt klasörleri oluştur
    os.makedirs(os.path.join(PROJECT_NAME, "app"), exist_ok=True)
    os.makedirs(os.path.join(PROJECT_NAME, "app", "templates"), exist_ok=True)
    os.makedirs(os.path.join(PROJECT_NAME, "app", "static"), exist_ok=True)

    # Dosyaları yaz
    for path, content in files.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            print(f"Oluşturuldu: {path}")

    print(f"\n✅ Proje '{PROJECT_NAME}' klasöründe hazır!")
    print(f"👉 İlk adım: Klasöre girip BENI_OKU.txt dosyasını oku.")

if __name__ == "__main__":
    create_project()