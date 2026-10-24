# QuestionCreate

Bir konu girin (ör. "9. sınıf üslü sayılar"), Google Gemini istediğiniz sayıda soru hazırlasın ve sorular cevap anahtarıyla birlikte PDF olarak kaydedilsin.

## Özellikler
- Modern arayüz (CustomTkinter), koyu / açık tema
- 1–50 arası soru, çoktan seçmeli veya açık uçlu, zorluk seçimi
- Gemini API anahtarı yalnızca ilk kullanımda sorulur (`~/.config/QuestionCreate/config.json`, izin 600)
- Türkçe karakter ve matematik sembolü destekli PDF, ayrı sayfada cevap anahtarı

## Kurulum
```bash
git clone https://github.com/ABK7474/QuestionCreate.git
cd QuestionCreate
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./QuestionCreate.sh
```
Python 3.10+ ve Tk gerekir (Fedora: `sudo dnf install python3-tkinter`).

Ücretsiz Gemini API anahtarı: https://aistudio.google.com/apikey

## Lisans
Yazı tipleri: DejaVu Sans (Bitstream Vera / DejaVu lisansı).
