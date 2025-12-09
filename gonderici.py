import requests
import time
import random
from datetime import datetime

# --- AYARLAR ---
# Buraya kendi PythonAnywhere kullanıcı adını yaz
KULLANICI_ADI = "baglanti" 
URL = f"https://{baglanti}.pythonanywhere.com/api/veri-gonder"

def rapor_gonder():
    print(f"--- Bağlantı Başlatılıyor: {URL} ---")
    
    while True:
        # 1. Gönderilecek veriyi hazırla (Senin projen ne üretiyorsa buraya o gelecek)
        sicaklik = random.randint(20, 50)
        enerji = random.randint(80, 100)
        
        mesaj_icerigi = f"Sıcaklık: {sicaklik}C | Enerji: %{enerji}"
        
        veri_paketi = {"mesaj": mesaj_icerigi}

        # 2. Veriyi gönder
        try:
            cevap = requests.post(URL, json=veri_paketi)
            
            if cevap.status_code == 200:
                print(f"✅ [GÖNDERİLDİ] {mesaj_icerigi}")
            else:
                print(f"⚠️ [HATA] Sunucu kabul etmedi: {cevap.status_code}")
                
        except Exception as hata:
            print(f"❌ [BAĞLANTI YOK] İnternet veya adres hatası: {hata}")

        # 3. Bekle (Örnek: 10 saniyede bir gönder)
        time.sleep(10)

if __name__ == "__main__":
    rapor_gonder()