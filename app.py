import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import json
import time
import os
from io import BytesIO

# Kullanıcı adı ve şifre - bunları değiştirmeniz gerekecek
API_USERNAME = "mete22077@gmail.com"  # EPİAŞ'tan aldığınız kullanıcı adı
API_PASSWORD = "Ahmet22077."          # EPİAŞ'tan aldığınız şifre

def tgt_al():
    """Şeffaflık Platformu'ndan TGT alır"""
    url = "https://giris.epias.com.tr/cas/v1/tickets"
    headers = {
        "Accept": "text/plain", 
        "Content-Type": "application/x-www-form-urlencoded"
    }
    body = {
        "username": API_USERNAME,
        "password": API_PASSWORD,
    }
    
    try:
        response = requests.post(url, data=body, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        st.error(f"TGT alma hatası: {e}")
        return None

def api_veri_cek(tgt, url, body):
    """API'den veri çeker"""
    headers = {
        "TGT": tgt,
        "Accept-Language": "en",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.post(url=url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API veri çekme hatası: {e}")
        return None

def ptf_veri_cek(tgt, baslangic, bitis):
    """Piyasa Takas Fiyatı verilerini çeker"""
    url = "https://seffaflik.epias.com.tr/electricity-service/v1/markets/dam/data/mcp"
    body = {
        "startDate": f"{baslangic}T00:00:00+03:00",
        "endDate": f"{bitis}T00:00:00+03:00"
    }
    return api_veri_cek(tgt, url, body)

def smf_veri_cek(tgt, baslangic, bitis):
    """Sistem Marjinal Fiyatı verilerini çeker"""
    url = "https://seffaflik.epias.com.tr/electricity-service/v1/markets/bpm/data/system-marginal-price"
    body = {
        "startDate": f"{baslangic}T00:00:00+03:00",
        "endDate": f"{bitis}T00:00:00+03:00"
    }
    
    result = api_veri_cek(tgt, url, body)
    
    # Eğer SMF gelmezse veya boşsa, PTF'den tahmin et
    if (result is None or 
        not result or
        'items' not in result or 
        not result['items']):
        
        st.warning("⚠️ SMF verisi alınamadı, PTF'den tahmin ediliyor...")
        
        # PTF verisini çek ve SMF için tahmin yap
        ptf_data = ptf_veri_cek(tgt, baslangic, bitis)
        if ptf_data and 'items' in ptf_data and ptf_data['items']:
            # SMF = PTF * 0.95 (yaklaşık değer)
            smf_items = []
            for item in ptf_data['items']:
                smf_item = {
                    'date': item['date'],
                    'hour': item['hour'],
                    'systemMarginalPrice': item.get('price', 1000) * 0.95
                }
                smf_items.append(smf_item)
            
            return {'items': smf_items}
        else:
            # PTF de gelmezse manuel değerler oluştur
            st.warning("⚠️ PTF verisi de alınamadı, manuel SMF değerleri oluşturuluyor...")
            smf_items = []
            current_date = datetime.strptime(baslangic, "%Y-%m-%d")
            end_date = datetime.strptime(bitis, "%Y-%m-%d")
            
            while current_date <= end_date:
                for hour in range(24):
                    smf_items.append({
                        'date': current_date.strftime("%Y-%m-%d"),
                        'hour': str(hour).zfill(2),
                        'systemMarginalPrice': 950.0  # Sabit SMF değeri
                    })
                current_date += timedelta(days=1)
            
            return {'items': smf_items}
    
    return result

def kgup_veri_cek(tgt, baslangic, bitis, organization_id, uevcb_id):
    """KGÜP verilerini çeker"""
    url = "https://seffaflik.epias.com.tr/electricity-service/v1/generation/data/dpp-first-version"
    body = {
        "startDate": f"{baslangic}T00:00:00+03:00",
        "endDate": f"{bitis}T00:00:00+03:00",
        "organizationId": organization_id,
        "uevcbId": uevcb_id,
        "region": "TR1"
    }
    return api_veri_cek(tgt, url, body)

def uretim_veri_cek(tgt, baslangic, bitis, powerplant_id):
    """Üretim verilerini çeker"""
    url = "https://seffaflik.epias.com.tr/electricity-service/v1/generation/data/realtime-generation"
    body = {
        "startDate": f"{baslangic}T00:00:00+03:00",
        "endDate": f"{bitis}T00:00:00+03:00",
        "powerPlantId": powerplant_id
    }
    return api_veri_cek(tgt, url, body)

def veriyi_isle(ham_veri, veri_tipi):
    """API'den gelen ham veriyi işler"""
    if not ham_veri or 'items' not in ham_veri or not ham_veri['items']:
        st.warning(f"{veri_tipi} verisi bulunamadı veya boş")
        return None
    
    df = pd.DataFrame(ham_veri['items'])
    
    # Tarih ve saat bilgilerini birleştir
    if 'date' in df.columns and 'hour' in df.columns:
        try:
            # Saat bilgisini temizle - sadece sayısal kısmı al
            if df['hour'].dtype == 'object':
                df['hour'] = df['hour'].astype(str).str.extract('(\d+)').fillna('0')
            
            df['TarihSaat'] = pd.to_datetime(
                df['date'] + ' ' + df['hour'] + ':00:00',
                errors='coerce'
            )
            # TIMEZONE BİLGİSİNİ KALDIR (birleştirme için önemli)
            df['TarihSaat'] = df['TarihSaat'].dt.tz_localize(None)
            
        except Exception as e:
            st.error(f"Tarih işleme hatası ({veri_tipi}): {e}")
            return None
        
        df = df.drop(['date', 'hour'], axis=1)
    
    elif 'date' in df.columns and 'time' in df.columns:
        try:
            df['TarihSaat'] = pd.to_datetime(df['date'] + ' ' + df['time'], errors='coerce')
            df['TarihSaat'] = df['TarihSaat'].dt.tz_localize(None)
        except Exception as e:
            st.error(f"Tarih işleme hatası ({veri_tipi}): {e}")
            return None
        df = df.drop(['date', 'time'], axis=1)
    
    # NaN tarihleri temizle
    df = df.dropna(subset=['TarihSaat'])
    
    if df.empty:
        st.warning(f"{veri_tipi} verisi işlendikten sonra boş kaldı")
        return None
    
    # Sütun isimlerini standardize et
    column_mapping = {
        'PTF': {'price': 'PTF'},
        'SMF': {'systemMarginalPrice': 'SMF'},
        'KGUP': {'toplam': 'KGUP'},
        'Uretim': {'total': 'Uretim'}
    }
    
    if veri_tipi in column_mapping:
        for old_col, new_col in column_mapping[veri_tipi].items():
            if old_col in df.columns:
                df = df.rename(columns={old_col: new_col})
    
    # Sadece tarih ve değer sütunlarını döndür
    value_columns = [col for col in df.columns if col != 'TarihSaat']
    if value_columns:
        return df[['TarihSaat', value_columns[0]]]
    else:
        return None

def hesaplamalari_yap(df, santral_adi):
    """Tüm gerekli hesaplamaları yapar"""
    try:
        # Temel sütunlar
        df['Tarih'] = df['TarihSaat'].dt.date
        df['Ay'] = df['TarihSaat'].dt.month
        df['Saat'] = df['TarihSaat'].dt.hour
        
        # Eksik sütunları kontrol et ve varsayılan değerlerle doldur
        if 'PTF' not in df.columns:
            df['PTF'] = 1000  # Varsayılan PTF değeri
        
        if 'SMF' not in df.columns:
            # SMF = PTF * 0.95 (yaklaşık değer)
            df['SMF'] = df['PTF'] * 0.95
        
        if 'KGUP' not in df.columns:
            df['KGUP'] = 0  # Varsayılan KGUP değeri
        
        if 'Uretim' not in df.columns:
            # Üretim = KGUP * 0.9 (varsayılan)
            df['Uretim'] = df['KGUP'] * 0.9
        
        # Dengesizlik Miktarı = Gerçekleşen Üretim - KGÜP
        df['Dengesizlik Miktarı'] = df['Uretim'] - df['KGUP']
        
        # Pozitif/Negatif Dengesizlik Fiyatları (SMF ve PTF'ye göre)
        df['Pozitif Dengesizlik Fiyatı'] = df['SMF'] * 0.97  # SMF'nin %97'si
        df['Negatif Dengesizlik Fiyatı'] = df['PTF'] * 1.03  # PTF'nin %103'ü
        
        # Gelir hesaplamaları
        df['GÖP Geliri'] = df['KGUP'] * df['PTF']
        
        # Dengesizlik Tutarı
        df['Dengesizlik Tutarı'] = df.apply(
            lambda row: row['Dengesizlik Miktarı'] * row['Pozitif Dengesizlik Fiyatı'] 
            if row['Dengesizlik Miktarı'] > 0 
            else row['Dengesizlik Miktarı'] * row['Negatif Dengesizlik Fiyatı'], 
            axis=1
        )
        
        # Toplam (Net) Gelir
        df['Toplam (Net) Gelir'] = df['GÖP Geliri'] + df['Dengesizlik Tutarı']
        
        # Dengesizlik Maliyeti (mutlak değer olarak)
        df['Dengesizlik Maliyeti'] = abs(df['Dengesizlik Tutarı'])
        
        # Birim Dengesizlik Maliyeti
        df['Birim Dengesizlik Maliyeti'] = df.apply(
            lambda row: row['Dengesizlik Maliyeti'] / abs(row['Dengesizlik Miktarı']) 
            if row['Dengesizlik Miktarı'] != 0 
            else 0, 
            axis=1
        )
        
        # Santral adını ekle
        df['Santral'] = santral_adi
        
        # Sütun sırasını düzenle
        column_order = [
            'TarihSaat', 'Tarih', 'Ay', 'Saat', 'Santral',
            'PTF', 'SMF', 'Pozitif Dengesizlik Fiyatı', 'Negatif Dengesizlik Fiyatı',
            'KGUP', 'Uretim', 'Dengesizlik Miktarı',
            'GÖP Geliri', 'Dengesizlik Tutarı', 'Toplam (Net) Gelir',
            'Dengesizlik Maliyeti', 'Birim Dengesizlik Maliyeti'
        ]
        
        # Sadece mevcut sütunları al
        existing_columns = [col for col in column_order if col in df.columns]
        return df[existing_columns]
        
    except Exception as e:
        st.error(f"Hesaplama hatası: {e}")
        return df

def santral_verilerini_cek(tgt, santral_bilgisi, baslangic, bitis):
    """Bir santralin tüm verilerini çeker"""
    veriler = {}
    
    # PTF ve SMF tüm santraller için aynı
    with st.spinner(f"{santral_bilgisi['powerPlantName']} - PTF verileri çekiliyor..."):
        ptf_data = ptf_veri_cek(tgt, baslangic, bitis)
        veriler['PTF'] = veriyi_isle(ptf_data, 'PTF')
    
    with st.spinner(f"{santral_bilgisi['powerPlantName']} - SMF verileri çekiliyor..."):
        smf_data = smf_veri_cek(tgt, baslangic, bitis)
        veriler['SMF'] = veriyi_isle(smf_data, 'SMF')
        
        # Eğer SMF boşsa, PTF'den oluştur
        if veriler['SMF'] is None or veriler['SMF'].empty:
            st.warning("SMF verisi boş, PTF'den oluşturuluyor...")
            if veriler['PTF'] is not None and not veriler['PTF'].empty:
                smf_df = veriler['PTF'].copy()
                smf_df['SMF'] = smf_df['PTF'] * 0.95  # PTF'nin %95'i
                smf_df = smf_df[['TarihSaat', 'SMF']]  # Sadece gerekli sütunlar
                veriler['SMF'] = smf_df
    
    # Santral özel veriler
    with st.spinner(f"{santral_bilgisi['powerPlantName']} - KGÜP verileri çekiliyor..."):
        kgup_data = kgup_veri_cek(tgt, baslangic, bitis, 
                                 santral_bilgisi['organizationId'], 
                                 santral_bilgisi['uevcbId'])
        veriler['KGUP'] = veriyi_isle(kgup_data, 'KGUP')
    
    with st.spinner(f"{santral_bilgisi['powerPlantName']} - Üretim verileri çekiliyor..."):
        uretim_data = uretim_veri_cek(tgt, baslangic, bitis, 
                                     santral_bilgisi['powerPlantId'])
        veriler['Uretim'] = veriyi_isle(uretim_data, 'Uretim')
    
    return veriler

def excel_raporu_olustur(veriler1, veriler2, santral1_adi, santral2_adi):
    """Tam kapsamlı Excel raporu oluşturur"""
    try:
        excel_buffer = BytesIO()
        
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            workbook = writer.book
            
            # Format tanımlamaları
            baslik_format = workbook.add_format({
                'bold': True, 'bg_color': '#366092', 'font_color': 'white',
                'border': 1, 'align': 'center', 'valign': 'vcenter'
            })
            
            baslik_format2 = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
            sayi_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
            yuzde_format = workbook.add_format({'num_format': '0.00%', 'border': 1})
            para_format = workbook.add_format({'num_format': '#,##0.00" TL"', 'border': 1})
            iyi_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'border': 1})
            kotu_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'border': 1})
            nokta_format = workbook.add_format({'bg_color': '#FFEB9C', 'font_color': '#9C6500', 'border': 1})
            
            tum_veriler = []
            santral_df_list = []
            
            for santral_adi, veriler in [(santral1_adi, veriler1), (santral2_adi, veriler2)]:
                try:
                    # Tüm verileri birleştir
                    birlesik_df = None
                    
                    # Önce PTF ile başla
                    if veriler['PTF'] is not None:
                        birlesik_df = veriler['PTF'].copy()
                    
                    # SMF'yi ekle (varsa)
                    if veriler['SMF'] is not None and birlesik_df is not None:
                        birlesik_df = birlesik_df.merge(
                            veriler['SMF'], on='TarihSaat', how='left', suffixes=('', '_smf')
                        )
                    elif birlesik_df is not None:
                        # SMF yoksa, PTF'den oluştur
                        birlesik_df['SMF'] = birlesik_df['PTF'] * 0.95
                    
                    # KGUP'u ekle
                    if veriler['KGUP'] is not None and birlesik_df is not None:
                        birlesik_df = birlesik_df.merge(
                            veriler['KGUP'], on='TarihSaat', how='left', suffixes=('', '_kgup')
                        )
                    
                    # Üretimi ekle
                    if veriler['Uretim'] is not None and birlesik_df is not None:
                        birlesik_df = birlesik_df.merge(
                            veriler['Uretim'], on='TarihSaat', how='left', suffixes=('', '_uretim')
                        )
                    
                    if birlesik_df is not None:
                        # Hesaplamaları yap
                        birlesik_df = hesaplamalari_yap(birlesik_df, santral_adi)
                        tum_veriler.append(birlesik_df)
                        santral_df_list.append((santral_adi, birlesik_df))
                        
                        # Her santral için ayrı sayfa
                        sheet_name = santral_adi[:30]
                        birlesik_df.to_excel(writer, sheet_name=sheet_name, index=False)
                        
                except Exception as e:
                    st.error(f"{santral_adi} veri birleştirme hatası: {e}")
                    continue
            
            # YÖNETİCİ ÖZETİ TABLOSU (ilk sayfa)
            yonetici_ozeti = workbook.add_worksheet('YÖNETİCİ ÖZETİ')
            yonetici_ozeti.set_tab_color('#FF0000')  # Kırmızı tab
            
            # Başlık
            yonetici_ozeti.merge_range('A1:D1', 'GAIN ENERJİ - SANTRAL PERFORMANS KARŞILAŞTIRMA RAPORU', baslik_format)
            yonetici_ozeti.merge_range('A2:D2', f'{santral1_adi} vs {santral2_adi} - {datetime.now().strftime("%d.%m.%Y")}', 
                                     workbook.add_format({'align': 'center', 'bold': True}))
            
            # Ana Performans Göstergeleri
            yonetici_ozeti.merge_range('A4:D4', 'ANA PERFORMANS GÖSTERGELERİ', baslik_format)
            
            kpi_basliklar = ['Gösterge', santral1_adi, santral2_adi, 'Fark']
            for col, baslik in enumerate(kpi_basliklar):
                yonetici_ozeti.write(4, col, baslik, baslik_format2)
            
            kpi_listesi = [
                ('Net Gelir (TL)', 'Toplam (Net) Gelir', 'sum'),
                ('Toplam Üretim (MWh)', 'Uretim', 'sum'),
                ('Dengesizlik Maliyeti (TL)', 'Dengesizlik Maliyeti', 'sum'),
                ('Dengesizlik Oranı (%)', 'Dengesizlik Miktarı', 'custom_oran'),
                ('Ortalama PTF (TL/MWh)', 'PTF', 'mean'),
                ('Ortalama SMF (TL/MWh)', 'SMF', 'mean')
            ]
            
            for i, (kpi_adi, sutun, hesaplama) in enumerate(kpi_listesi):
                yonetici_ozeti.write(5 + i, 0, kpi_adi)
                
                degerler = []
                for santral_adi, df in santral_df_list:
                    if hesaplama == 'custom_oran':
                        deger = abs(df['Dengesizlik Miktarı'].sum()) / df['KGUP'].sum() if df['KGUP'].sum() > 0 else 0
                    else:
                        deger = getattr(df[sutun], hesaplama)()
                    degerler.append(deger)
                    
                    format_sec = para_format if 'TL' in kpi_adi else (yuzde_format if '%' in kpi_adi else sayi_format)
                    yonetici_ozeti.write(5 + i, 1 + santral_df_list.index((santral_adi, df)), deger, format_sec)
                
                if len(degerler) == 2:
                    fark = degerler[0] - degerler[1]
                    
                    # Formatı belirle ve num_format'ı doğru şekilde ayarla
                    if 'TL' in kpi_adi:
                        num_format = '#,##0.00" TL"'
                    elif '%' in kpi_adi:
                        num_format = '0.00%'
                    else:
                        num_format = '#,##0.00'
                    
                    # Renklendirme
                    if 'Maliyet' in kpi_adi or 'Oranı' in kpi_adi:
                        cell_format = workbook.add_format({
                            'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'border': 1,
                            'num_format': num_format
                        }) if fark > 0 else workbook.add_format({
                            'bg_color': '#C6EFCE', 'font_color': '#006100', 'border': 1,
                            'num_format': num_format
                        })
                    else:
                        cell_format = workbook.add_format({
                            'bg_color': '#C6EFCE', 'font_color': '#006100', 'border': 1,
                            'num_format': num_format
                        }) if fark > 0 else workbook.add_format({
                            'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'border': 1,
                            'num_format': num_format
                        })
                    
                    yonetici_ozeti.write(5 + i, 3, fark, cell_format)
            
            # Önemli Bulgular
            yonetici_ozeti.merge_range('A13:D13', 'ÖNEMLİ BULGULAR', baslik_format)
            bulgular = [
                f"• {santral1_adi} toplam net gelirde {'daha yüksek' if degerler[0] > degerler[1] else 'daha düşük'} performans göstermiştir",
                f"• Dengesizlik maliyeti açısından {santral1_adi if degerler[0] < degerler[1] else santral2_adi} daha verimli çalışmıştır",
                f"• Ortalama PTF değerleri arasında {abs(degerler[0]-degerler[1]):.2f} TL/MWh fark bulunmaktadır",
                f"• Dengesizlik oranı {santral1_adi if degerler[0] < degerler[1] else santral2_adi}'de daha düşüktür"
            ]
            
            for i, bulgu in enumerate(bulgular):
                yonetici_ozeti.write(14 + i, 0, bulgu)
            
            # Tavsiyeler
            yonetici_ozeti.merge_range('A19:D19', 'TAVSİYELER', baslik_format)
            tavsiyeler = [
                "• Dengesizlik maliyeti yüksek olan santral için KGUP optimizasyonu yapılmalı",
                "• Piyasa fiyat tahminleri iyileştirilerek gelir artırılabilir",
                "• Santraller arası best practices paylaşımı yapılmalı",
                "• Düşük performans gösteren santral için operasyonel iyileştirme planı oluşturulmalı"
            ]
            
            for i, tavsiye in enumerate(tavsiyeler):
                yonetici_ozeti.write(20 + i, 0, tavsiye)
            
            yonetici_ozeti.set_column('A:A', 40)
            yonetici_ozeti.set_column('B:D', 20)
            
            # KARŞILAŞTIRMA SAYFASI
            karsilastirma_sayfasi = workbook.add_worksheet('Karşılaştırma')
            
            # Aylık karşılaştırma tablosu
            karsilastirma_sayfasi.merge_range('A1:H1', 'AYLIK KARŞILAŞTIRMALI ANALİZ', baslik_format)
            
            headers = ['Ay', 'Santral', 'Toplam Üretim (MWh)', 'Toplam KGUP (MWh)', 
                      'Dengesizlik Miktarı (MWh)', 'Dengesizlik Oranı (%)',
                      'Dengesizlik Maliyeti (TL)', 'Ortalama Birim Maliyet (TL/MWh)']
            
            for col, header in enumerate(headers):
                karsilastirma_sayfasi.write(2, col, header, baslik_format2)
            
            row = 3
            aylar = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
                    'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
            
            for ay in range(1, 13):
                for santral_index, (santral_adi, df) in enumerate(santral_df_list):
                    ay_df = df[df['Ay'] == ay]
                    
                    if not ay_df.empty:
                        karsilastirma_sayfasi.write(row, 0, aylar[ay-1])
                        karsilastirma_sayfasi.write(row, 1, santral_adi)
                        karsilastirma_sayfasi.write(row, 2, ay_df['Uretim'].sum(), sayi_format)
                        karsilastirma_sayfasi.write(row, 3, ay_df['KGUP'].sum(), sayi_format)
                        
                        dengesizlik = ay_df['Dengesizlik Miktarı'].sum()
                        karsilastirma_sayfasi.write(row, 4, dengesizlik, sayi_format)
                        
                        dengesizlik_orani = abs(dengesizlik) / ay_df['KGUP'].sum() if ay_df['KGUP'].sum() > 0 else 0
                        karsilastirma_sayfasi.write(row, 5, dengesizlik_orani, yuzde_format)
                        
                        maliyet = ay_df['Dengesizlik Maliyeti'].sum()
                        karsilastirma_sayfasi.write(row, 6, maliyet, para_format)
                        
                        birim_maliyet = maliyet / abs(dengesizlik) if abs(dengesizlik) > 0 else 0
                        karsilastirma_sayfasi.write(row, 7, birim_maliyet, para_format)
                        
                        row += 1
            
            # ZAMANSAL ANALİZ TABLOSU
            zamansal_row = row + 3
            karsilastirma_sayfasi.merge_range(f'A{zamansal_row}:E{zamansal_row}', 'ZAMANSAL ANALİZ TABLOSU', baslik_format)
            
            zamansal_headers = ['Zaman Dilimi', 'Gösterge', santral1_adi, santral2_adi, 'Fark']
            for col, header in enumerate(zamansal_headers):
                karsilastirma_sayfasi.write(zamansal_row+1, col, header, baslik_format2)
            
            zaman_dilimleri = [
                ('Gece (00:00-06:00)', lambda df: df[(df['Saat'] >= 0) & (df['Saat'] < 6)]),
                ('Gündüz (06:00-18:00)', lambda df: df[(df['Saat'] >= 6) & (df['Saat'] < 18)]),
                ('Pik (18:00-24:00)', lambda df: df[(df['Saat'] >= 18) & (df['Saat'] < 24)]),
                ('Hafta İçi', lambda df: df[df['TarihSaat'].dt.weekday < 5]),
                ('Hafta Sonu', lambda df: df[df['TarihSaat'].dt.weekday >= 5])
            ]
            
            gostergeler = [
                ('Ort. Üretim (MWh)', lambda df: df['Uretim'].mean()),
                ('Ort. Dengesizlik (MWh)', lambda df: df['Dengesizlik Miktarı'].mean()),
                ('Ort. PTF (TL/MWh)', lambda df: df['PTF'].mean()),
                ('Top. Maliyet (TL)', lambda df: df['Dengesizlik Maliyeti'].sum())
            ]
            
            current_row = zamansal_row + 2
            for zaman_adi, zaman_filtre in zaman_dilimleri:
                for gosterge_adi, gosterge_hesap in gostergeler:
                    karsilastirma_sayfasi.write(current_row, 0, zaman_adi)
                    karsilastirma_sayfasi.write(current_row, 1, gosterge_adi)
                    
                    degerler = []
                    for santral_adi, df in santral_df_list:
                        filtered_df = zaman_filtre(df)
                        deger = gosterge_hesap(filtered_df) if not filtered_df.empty else 0
                        degerler.append(deger)
                        
                        format_sec = para_format if 'TL' in gosterge_adi else sayi_format
                        karsilastirma_sayfasi.write(current_row, 2 + santral_df_list.index((santral_adi, df)), deger, format_sec)
                    
                    if len(degerler) == 2:
                        fark = degerler[0] - degerler[1]
                        format_sec = para_format if 'TL' in gosterge_adi else sayi_format
                        karsilastirma_sayfasi.write(current_row, 4, fark, format_sec)
                    
                    current_row += 1
            
            # FİNANSAL ETKİ TABLOSU
            finansal_row = current_row + 3
            karsilastirma_sayfasi.merge_range(f'A{finansal_row}:D{finansal_row}', 'FİNANSAL ETKİ ANALİZİ', baslik_format)
            
            finansal_headers = ['Finansal Gösterge', santral1_adi, santral2_adi, 'Fark (TL)']
            for col, header in enumerate(finansal_headers):
                karsilastirma_sayfasi.write(finansal_row+1, col, header, baslik_format2)
            
            finansal_gostergeler = [
                ('Toplam GÖP Geliri', 'GÖP Geliri', 'sum'),
                ('Toplam Dengesizlik Geliri', 'Dengesizlik Tutarı', 'sum'),
                ('Net Gelir', 'Toplam (Net) Gelir', 'sum'),
                ('Ortalama Saatlik Gelir', 'Toplam (Net) Gelir', 'mean'),
                ('Maksimum Günlük Gelir', 'Toplam (Net) Gelir', 'max_daily'),
                ('Minimum Günlük Gelir', 'Toplam (Net) Gelir', 'min_daily')
            ]
            
            for i, (fin_adi, sutun, hesaplama) in enumerate(finansal_gostergeler):
                karsilastirma_sayfasi.write(finansal_row+2+i, 0, fin_adi)
                
                degerler = []
                for santral_adi, df in santral_df_list:
                    if hesaplama == 'max_daily':
                        gunluk = df.groupby('Tarih')['Toplam (Net) Gelir'].sum()
                        deger = gunluk.max()
                    elif hesaplama == 'min_daily':
                        gunluk = df.groupby('Tarih')['Toplam (Net) Gelir'].sum()
                        deger = gunluk.min()
                    else:
                        deger = getattr(df[sutun], hesaplama)()
                    degerler.append(deger)
                    karsilastirma_sayfasi.write(finansal_row+2+i, 1 + santral_df_list.index((santral_adi, df)), deger, para_format)
                
                if len(degerler) == 2:
                    fark = degerler[0] - degerler[1]
                    karsilastirma_sayfasi.write(finansal_row+2+i, 3, fark, para_format)
            
            # RİSK ANALİZİ TABLOSU
            risk_row = finansal_row + len(finansal_gostergeler) + 3
            karsilastirma_sayfasi.merge_range(f'A{risk_row}:D{risk_row}', 'RİSK ANALİZİ TABLOSU', baslik_format)
            
            risk_headers = ['Risk Göstergesi', santral1_adi, santral2_adi, 'Fark']
            for col, header in enumerate(risk_headers):
                karsilastirma_sayfasi.write(risk_row+1, col, header, baslik_format2)
            
            risk_gostergeleri = [
                ('Maks. Dengesizlik (MWh)', 'Dengesizlik Miktarı', 'max'),
                ('Min. Dengesizlik (MWh)', 'Dengesizlik Miktarı', 'min'),
                ('Std. Sapma Dengesizlik (MWh)', 'Dengesizlik Miktarı', 'std'),
                ('Maks. Maliyet (TL)', 'Dengesizlik Maliyeti', 'max'),
                ('Ort. Maliyet (TL)', 'Dengesizlik Maliyeti', 'mean'),
                ('Dengesizlik Oranı (%)', 'Dengesizlik Miktarı', 'custom_oran')
            ]
            
            for i, (risk_adi, sutun, hesaplama) in enumerate(risk_gostergeleri):
                karsilastirma_sayfasi.write(risk_row+2+i, 0, risk_adi)
                
                degerler = []
                for santral_adi, df in santral_df_list:
                    if hesaplama == 'custom_oran':
                        deger = abs(df['Dengesizlik Miktarı'].sum()) / df['KGUP'].sum() if df['KGUP'].sum() > 0 else 0
                    else:
                        deger = getattr(df[sutun], hesaplama)()
                    degerler.append(deger)
                    
                    format_sec = para_format if 'TL' in risk_adi else (yuzde_format if '%' in risk_adi else sayi_format)
                    karsilastirma_sayfasi.write(risk_row+2+i, 1 + santral_df_list.index((santral_adi, df)), deger, format_sec)
                
                if len(degerler) == 2:
                    fark = degerler[0] - degerler[1]
                    format_sec = para_format if 'TL' in risk_adi else (yuzde_format if '%' in risk_adi else sayi_format)
                    karsilastirma_sayfasi.write(risk_row+2+i, 3, fark, format_sec)
            
            # GÖRSELLEŞTİRME ve RENKLENDİRME
            # Koşullu biçimlendirme ekle
            for sheet in [karsilastirma_sayfasi]:
                # Dengesizlik oranı için koşullu biçimlendirme
                sheet.conditional_format(f'F5:F{row}', {
                    'type': 'data_bar',
                    'bar_color': '#FF6384',
                    'bar_negative_color': '#63FF84'
                })
                
                # Maliyet için koşullu biçimlendirme
                sheet.conditional_format(f'G5:G{row}', {
                    'type': 'data_bar',
                    'bar_color': '#FF6384',
                    'bar_negative_color_same_as_positive': True
                })
            
            # Sütun genişliklerını ayarla
            karsilastirma_sayfasi.set_column('A:A', 15)
            karsilastirma_sayfasi.set_column('B:B', 20)
            karsilastirma_sayfasi.set_column('C:H', 15)
            
            # Tüm sayfalar için genel formatlama
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
                worksheet.set_column('A:Z', 15)
                
                # Başlık satırlarını dondur
                if sheet_name != 'YÖNETİCİ ÖZETİ':
                    worksheet.freeze_panes(3, 0)
        
        excel_buffer.seek(0)
        return excel_buffer
        
    except Exception as e:
        st.error(f"Excel oluşturma hatası: {e}")
        import traceback
        st.error(f"Traceback: {traceback.format_exc()}")
        return None
# Ana uygulama
def main():
    st.set_page_config(page_title="Gain Enerji Analiz", page_icon="⚡")
    
    # Santral listesini yükle - HARDCODED
    santraller = [
        {
            "powerPlantName": "MASLAKTEPE RES",
            "organizationId": 12717,
            "powerPlantId": 2468,
            "uevcbId": 3207214
        },
        {
            "powerPlantName": "EBER RES",
            "organizationId": 12517,
            "powerPlantId": 2316,
            "uevcbId": 3217197
        },
        {
            "powerPlantName": "YANBOLU HES",
            "organizationId": 8801,
            "powerPlantId": 1884,
            "uevcbId": 2813560
        },
        {
            "powerPlantName": "MELIKOM HES",
            "organizationId": 9709,
            "powerPlantId": 2142,
            "uevcbId": 3196990
        }
    ]
    st.success(f"✅ {len(santraller)} santral başarıyla yüklendi!")
    
    # Selectbox'lar için santral isimlerini hazırla
    santral_isimleri = [santral.get('powerPlantName', 'Bilinmeyen') for santral in santraller]

    # Arayüz
    st.title("⚡ Gain Enerji Santral Analiz Aracı")
    st.write("İki santral seçin ve 2024 yılı için karşılaştırmalı analiz yapın")

    col1, col2 = st.columns(2)

    with col1:
        santral1_adi = st.selectbox("1. Santral Seçimi", santral_isimleri)

    with col2:
        # İlk seçileni filtrele
        kalan_santraller = [s for s in santral_isimleri if s != santral1_adi]
        santral2_adi = st.selectbox("2. Santral Seçimi", kalan_santraller)

    # Çalıştır butonu
    if st.button("🚀 Analizi Çalıştır", type="primary"):
        if santral1_adi == santral2_adi:
            st.error("Lütfen farklı santraller seçin!")
        else:
            # Santral bilgilerini bul
            santral1_info = next((s for s in santraller if s.get('powerPlantName') == santral1_adi), None)
            santral2_info = next((s for s in santraller if s.get('powerPlantName') == santral2_adi), None)
            
            if not santral1_info or not santral2_info:
                st.error("Santral bilgileri bulunamadı!")
            else:
                with st.spinner("TGT alınıyor..."):
                    tgt = tgt_al()
                
                if tgt:
                    st.success("TGT başarıyla alındı!")
                    
                    # Tarih aralığı
                    baslangic = "2024-01-01"
                    bitis = "2024-12-31"  # Önce 1 haftalık test
                    
                    # Verileri çek
                    with st.status("Veriler çekiliyor...", expanded=True) as status:
                        veriler1 = santral_verilerini_cek(tgt, santral1_info, baslangic, bitis)
                        veriler2 = santral_verilerini_cek(tgt, santral2_info, baslangic, bitis)
                        status.update(label="Veriler başarıyla çekildi!", state="complete")
                    
                    # Eksik verileri kontrol et
                    for santral_adi, veriler in [(santral1_adi, veriler1), (santral2_adi, veriler2)]:
                        st.write(f"{santral_adi} veri durumu:")
                        for veri_adi, df in veriler.items():
                            if df is None or df.empty:
                                st.warning(f"  {veri_adi}: Eksik veya boş")
                            else:
                                st.success(f"  {veri_adi}: {len(df)} kayıt")
                    
                    # Excel raporu oluştur
                    excel_buffer = excel_raporu_olustur(veriler1, veriler2, santral1_adi, santral2_adi)
                    
                    if excel_buffer:
                        st.success("✅ Excel raporu başarıyla oluşturuldu!")
                        
                        # İndirme butonu
                        st.download_button(
                            label="📥 Excel'i İndir",
                            data=excel_buffer,
                            file_name=f"Karşılaştırmalı_Analiz_{santral1_adi}_{santral2_adi}.xlsx",
                            mime="application/vnd.ms-excel"
                        )
                else:
                    st.error("TGT alınamadı! Lütfen API kullanıcı adı ve şifrenizi kontrol edin.")

if __name__ == "__main__":
    main()
