# BelgeOCR

ABBYY FineReader benzeri, Windows için masaüstü OCR ve PDF uygulaması.

## Özellikler

- **Metin tanıma (OCR):** PDF ve resimlerden (PNG, JPG, TIFF, BMP, WEBP) metin çıkarır. Türkçe ve İngilizce dahil. Eğik taramaları otomatik düzeltir. Tanınan metin uygulama içinde düzenlenebilir.
- **Aranabilir PDF:** Taranmış PDF'ye görünmez bir metin katmanı ekler. Orijinal görüntü kalitesi korunur, metin aranabilir ve kopyalanabilir.
- **Word'e aktarma (DOCX):** Paragrafları, yaklaşık yazı boyutlarını ve başlıkları korur.
- **Tabloları Excel'e aktarma (XLSX):** Çizgili tabloları (birleştirilmiş hücreler dahil) ve çizgisiz tabloları tanır. Türkçe sayı biçimlerini (`1.250,75`) sayıya çevirir.
- **Sayfa düzenleme:** Soldaki sayfa panelinde tek tıkla sola/sağa 90° döndürme, seçili sayfaları silme, sürükleyerek sıralama, başka dosyalardan sayfa ekleme, seçili sayfaları ayrı PDF olarak kaydetme ve geri alma (Ctrl+Z).
- **Tablo düzenleyici:** Tanınan tablolar Excel'e aktarılmadan önce düzenlenebilir (hücre, satır, sütun). Sayfalara bölünmüş tablolar (aynı sütun sayısı) tek tabloda birleştirilir, tekrarlanan başlık satırı atılır.
- **Yapay zekâ ile analiz (F7):** Sayfa görüntüsü seçilen servise (Google Gemini, OpenAI veya Anthropic Claude) gönderilir, metin ve tablolar yüksek doğrulukla çıkarılır. API anahtarı Ayarlar > Yapay Zekâ bölümüne girilir. Belgeler seçilen servisin sunucularına gönderilir.

## Kurulum (son kullanıcı)

GitHub Actions'ın ürettiği `BelgeOCR-Setup-x.y.z.exe` dosyasını çalıştırın. Tesseract OCR motoru pakete dahildir, ayrıca kurmanız gerekmez. Kurulum istemiyorsanız `BelgeOCR-portable-x.y.z.zip` dosyasını açıp `BelgeOCR.exe`'yi çalıştırın.

## Geliştirme

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python run_belgeocr.py
pytest -q
```

Geliştirme ortamında Tesseract'ın kurulu olması gerekir:

- Windows: [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) kurulumu (Türkçe dil paketini seçin)
- Ubuntu: `sudo apt install tesseract-ocr tesseract-ocr-tur`

Tesseract standart bir konumda değilse yolunu `BELGEOCR_TESSERACT` ortam değişkenine yazın.

## Windows paketi oluşturma

`.github/workflows/build.yml` her push'ta testleri çalıştırır, Windows kurulum dosyasını ve taşınabilir zip'i artifact olarak yükler. `v*` etiketi (ör. `v0.1.0`) push'landığında bunları bir GitHub Release'e ekler.

Elle derlemek için (Windows, PowerShell):

```powershell
pip install -r requirements-dev.txt
./packaging/fetch_tesseract.ps1 -Destination packaging\tesseract
pyinstaller --noconfirm packaging/belgeocr.spec
Copy-Item packaging\tesseract dist\BelgeOCR\tesseract -Recurse
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

## Mimari

| Modül | Görev |
|---|---|
| `belgeocr/loader.py` | PDF sayfalarını (pypdfium2) ve resimleri yükler |
| `belgeocr/ocr.py` | Ön işleme (eğiklik düzeltme), OCR, aranabilir PDF |
| `belgeocr/export_docx.py` | Word ve TXT çıktısı |
| `belgeocr/tables.py` | Tablo algılama (OpenCV), hücre OCR, Excel çıktısı |
| `belgeocr/pdf_tools.py` | Birleştirme, bölme, döndürme, sayfa işlemleri (pypdf) |
| `belgeocr/document.py` | Düzenlenebilir sayfa listesi (döndür/sil/sırala/geri al) ve PDF yazma |
| `belgeocr/ai.py` | Yapay zekâ sağlayıcıları (Gemini, OpenAI, Claude) ile sayfa analizi |
| `belgeocr/gui/` | PySide6 arayüzü |

Tüm bağımlılıklar ticari kullanıma izin veren lisanslara sahiptir: Tesseract (Apache 2.0), PySide6 (LGPL), pypdf (BSD), pypdfium2 (Apache/BSD), OpenCV (Apache 2.0), python-docx, openpyxl ve QtAwesome (MIT).
