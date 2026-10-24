#!/usr/bin/env python3
"""QuestionCreate - Gemini ile konu bazlı soru üretip PDF'e döken masaüstü uygulaması."""

import json
import os
import re
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional

import customtkinter as ctk
import httpx
from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "QuestionCreate"
CONFIG_FILE = CONFIG_DIR / "config.json"
FALLBACK_MODEL = "gemini-2.5-flash"


class Question(BaseModel):
    question: str
    options: List[str]  # çoktan seçmeli değilse boş liste
    answer: str
    explanation: str


class QuestionSet(BaseModel):
    title: str
    questions: List[Question]


# ---------------------------------------------------------------- config

def load_api_key() -> Optional[str]:
    try:
        return json.loads(CONFIG_FILE.read_text()).get("gemini_api_key")
    except (OSError, ValueError):
        return None


def save_api_key(key: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"gemini_api_key": key}))
    os.chmod(CONFIG_FILE, 0o600)


# ---------------------------------------------------------------- AI

def pick_model(client: genai.Client) -> str:
    """Hesapta erişilebilen en yeni kararlı 'gemini-X-flash' modelini seçer."""
    best, best_ver = FALLBACK_MODEL, 0.0
    try:
        for m in client.models.list():
            name = (m.name or "").removeprefix("models/")
            match = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", name)
            if match and "generateContent" in (m.supported_actions or []) and float(match.group(1)) > best_ver:
                best, best_ver = name, float(match.group(1))
    except genai_errors.ServerError:
        pass
    return best


def generate_questions(api_key: str, topic: str, count: int, qtype: str, difficulty: str) -> QuestionSet:
    client = genai.Client(api_key=api_key)
    if qtype == "Çoktan seçmeli":
        type_rule = "Her soru tam 5 şıklı (A-E) çoktan seçmeli olsun; options alanına şıkları 'A) ...' biçiminde yaz, answer alanına doğru şıkkın harfini yaz."
    else:
        type_rule = "Sorular açık uçlu olsun; options alanını boş liste bırak, answer alanına kısa doğru cevabı yaz."

    prompt = (
        f"Konu: {topic}\n"
        f"Bu konu hakkında Türkçe, {count} adet özgün sınav sorusu hazırla.\n"
        f"Zorluk: {difficulty}.\n"
        f"{type_rule}\n"
        "Sorular müfredata uygun, birbirinden farklı ve tek doğru cevaplı olsun. "
        "explanation alanına kısa bir çözüm açıklaması yaz. "
        "Matematiksel ifadelerde LaTeX kullanma; düz metin ve Unicode (², ³, √, ×, ÷, ⁻¹ gibi) kullan. "
        "title alanına konuyu anlatan kısa bir başlık yaz."
    )
    response = client.models.generate_content(
        model=pick_model(client),
        contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": QuestionSet},
    )
    finish = response.candidates[0].finish_reason.name if response.candidates else None
    if finish == "MAX_TOKENS":
        raise RuntimeError("Yanıt çok uzun oldu. Daha az soru isteyin.")
    if response.parsed is None:
        raise RuntimeError("Model geçerli bir yanıt döndürmedi. Konuyu farklı ifade edip tekrar deneyin.")
    return response.parsed


# ---------------------------------------------------------------- PDF

def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def build_pdf(qset: QuestionSet, path: Path) -> None:
    pdfmetrics.registerFont(TTFont("DejaVu", str(APP_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(APP_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

    title = ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=16, alignment=TA_CENTER, spaceAfter=6)
    sub = ParagraphStyle("sub", fontName="DejaVu", fontSize=9, alignment=TA_CENTER, textColor="#666666", spaceAfter=14)
    q_style = ParagraphStyle("q", fontName="DejaVu", fontSize=11, leading=15, spaceAfter=4)
    opt = ParagraphStyle("opt", fontName="DejaVu", fontSize=10.5, leading=14, leftIndent=18)
    ans = ParagraphStyle("ans", fontName="DejaVu", fontSize=10, leading=14, spaceAfter=8)

    story = [
        Paragraph(_esc(qset.title), title),
        Paragraph(f"{len(qset.questions)} soru · {datetime.now():%d.%m.%Y}", sub),
    ]
    for i, q in enumerate(qset.questions, 1):
        block = [Paragraph(f"<b>{i}.</b> {_esc(q.question)}", q_style)]
        block += [Paragraph(_esc(o), opt) for o in q.options]
        block.append(Spacer(1, 12))
        story.append(KeepTogether(block))

    story += [PageBreak(), Paragraph("Cevap Anahtarı", title), Spacer(1, 8)]
    for i, q in enumerate(qset.questions, 1):
        story.append(Paragraph(f"<b>{i}. {_esc(q.answer)}</b> — {_esc(q.explanation)}", ans))

    def footer(canvas, doc):
        canvas.setFont("DejaVu", 8)
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, str(doc.page))

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm, title=qset.title
                      ).build(story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------- UI

ACCENT = ("#4F46E5", "#6366F1")
ACCENT_HOVER = ("#4338CA", "#4F46E5")
CARD = ("#FFFFFF", "#1E1F26")
BG = ("#F1F2F7", "#13141A")
MUTED = ("#6B7280", "#9CA3AF")
FONT = "DejaVu Sans"


class KeyDialog(ctk.CTkToplevel):
    """API anahtarı girişi için modal pencere."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result: Optional[str] = None
        self.title("API Anahtarı")
        self.geometry("420x230")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(parent)

        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=16)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(card, text="🔑  Gemini API anahtarı", font=(FONT, 16, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card, text="Bir kez sorulur, bu bilgisayarda saklanır.",
                     font=(FONT, 12), text_color=MUTED).pack(anchor="w", padx=20)
        self.entry = ctk.CTkEntry(card, show="•", height=38, corner_radius=10, placeholder_text="AIza...")
        self.entry.pack(fill="x", padx=20, pady=(14, 12))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=20)
        ctk.CTkButton(row, text="Kaydet", height=36, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self._ok).pack(side="right")
        ctk.CTkButton(row, text="İptal", height=36, corner_radius=10, fg_color="transparent",
                      border_width=1, text_color=("gray20", "gray85"), command=self.destroy).pack(side="right", padx=8)
        self.entry.bind("<Return>", lambda e: self._ok())
        self.after(100, self._grab)

    def _grab(self):
        self.entry.focus()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _ok(self):
        val = self.entry.get().strip()
        if val:
            self.result = val
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_default_color_theme("blue")
        self.title("QuestionCreate")
        self.geometry("560x640")
        self.minsize(500, 620)
        self.configure(fg_color=BG)

        # --- başlık
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 8))
        ctk.CTkLabel(header, text="QuestionCreate", font=(FONT, 26, "bold")).pack(side="left")
        self.theme_switch = ctk.CTkSwitch(header, text="Koyu", command=self._toggle_theme,
                                          progress_color=ACCENT, font=(FONT, 12))
        self.theme_switch.pack(side="right")
        if ctk.get_appearance_mode() == "Dark":
            self.theme_switch.select()
        ctk.CTkLabel(self, text="Bir konu yaz, yapay zekâ sorularını hazırlasın ve PDF olarak sunsun.",
                     font=(FONT, 13), text_color=MUTED, anchor="w").pack(fill="x", padx=28)

        # --- form kartı
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=18)
        card.pack(fill="both", expand=True, padx=24, pady=18)
        pad = {"padx": 24}

        self._label(card, "Konu").pack(anchor="w", pady=(22, 6), **pad)
        self.topic = ctk.CTkEntry(card, height=44, corner_radius=12, font=(FONT, 14),
                                  placeholder_text="örn. 9. sınıf üslü sayılar")
        self.topic.pack(fill="x", **pad)

        count_row = ctk.CTkFrame(card, fg_color="transparent")
        count_row.pack(fill="x", pady=(20, 4), **pad)
        self._label(count_row, "Soru sayısı").pack(side="left")
        self.count_lbl = ctk.CTkLabel(count_row, text="10", font=(FONT, 14, "bold"), text_color=ACCENT)
        self.count_lbl.pack(side="right")
        self.count = ctk.CTkSlider(card, from_=1, to=50, number_of_steps=49, button_color=ACCENT,
                                   button_hover_color=ACCENT_HOVER, progress_color=ACCENT,
                                   command=lambda v: self.count_lbl.configure(text=str(int(v))))
        self.count.set(10)
        self.count.pack(fill="x", **pad)

        self._label(card, "Soru tipi").pack(anchor="w", pady=(20, 6), **pad)
        self.qtype = self._segmented(card, ["Çoktan seçmeli", "Açık uçlu"])
        self.qtype.pack(fill="x", **pad)

        self._label(card, "Zorluk").pack(anchor="w", pady=(18, 6), **pad)
        self.diff = self._segmented(card, ["Kolay", "Orta", "Zor", "Karışık"])
        self.diff.set("Orta")
        self.diff.pack(fill="x", **pad)

        self.btn = ctk.CTkButton(card, text="✨  Soruları Oluştur", height=50, corner_radius=14,
                                 font=(FONT, 15, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                 command=self.on_generate)
        self.btn.pack(fill="x", pady=(28, 12), **pad)

        self.progress = ctk.CTkProgressBar(card, mode="indeterminate", height=6, progress_color=ACCENT)
        self.status = ctk.CTkLabel(card, text="", font=(FONT, 12), text_color=MUTED)
        self.status.pack(**pad)

        # --- alt bilgi
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkLabel(footer, text="Model: Google Gemini", font=(FONT, 11), text_color=MUTED).pack(side="left")
        ctk.CTkButton(footer, text="🔑 API anahtarını değiştir", width=10, height=28, fg_color="transparent",
                      hover_color=CARD, text_color=MUTED, font=(FONT, 11), command=self.ask_key).pack(side="right")

        self.bind("<Return>", lambda e: self.on_generate())
        self.topic.focus()

    @staticmethod
    def _label(parent, text):
        return ctk.CTkLabel(parent, text=text, font=(FONT, 13, "bold"))

    @staticmethod
    def _segmented(parent, values):
        seg = ctk.CTkSegmentedButton(parent, values=values, height=38, corner_radius=10, font=(FONT, 13),
                                     selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        seg.set(values[0])
        return seg

    def _toggle_theme(self):
        ctk.set_appearance_mode("dark" if self.theme_switch.get() else "light")

    def ask_key(self) -> Optional[str]:
        dlg = KeyDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            save_api_key(dlg.result)
            self._set_status("API anahtarı kaydedildi.")
        return dlg.result

    def _set_status(self, text, error=False):
        self.status.configure(text=text, text_color=("#DC2626", "#F87171") if error else MUTED)

    def on_generate(self):
        if self.btn.cget("state") == "disabled":
            return
        topic = self.topic.get().strip()
        if not topic:
            self._set_status("Lütfen bir konu girin.", error=True)
            self.topic.focus()
            return
        key = load_api_key() or self.ask_key()
        if not key:
            return
        count = int(self.count.get())

        self.btn.configure(state="disabled", text="Hazırlanıyor…")
        self.progress.pack(fill="x", padx=24, pady=(0, 8), before=self.status)
        self.progress.start()
        self._set_status(f"{count} soru üretiliyor, bu biraz sürebilir…")
        args = (key, topic, count, self.qtype.get(), self.diff.get())
        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _worker(self, key, topic, count, qtype, diff):
        try:
            qset = generate_questions(key, topic, count, qtype, diff)
            self.after(0, self._done, qset, None)
        except genai_errors.ClientError as e:
            if e.code in (401, 403) or "API_KEY_INVALID" in str(e) or "API key not valid" in str(e):
                msg = "API anahtarı geçersiz. Alttaki butonla yeniden girin."
            elif e.code == 429:
                msg = "İstek limiti / kota aşıldı, biraz sonra tekrar deneyin."
            else:
                msg = f"API hatası ({e.code}): {e.message}"
            self.after(0, self._done, None, msg)
        except genai_errors.ServerError:
            self.after(0, self._done, None, "Gemini sunucusu şu an yanıt vermiyor, biraz sonra tekrar deneyin.")
        except httpx.TransportError:
            self.after(0, self._done, None, "Bağlantı hatası. İnternet bağlantınızı kontrol edin.")
        except Exception as e:
            self.after(0, self._done, None, str(e))

    def _done(self, qset: Optional[QuestionSet], error: Optional[str]):
        self.progress.stop()
        self.progress.pack_forget()
        self.btn.configure(state="normal", text="✨  Soruları Oluştur")
        if error:
            self._set_status(error, error=True)
            messagebox.showerror("Hata", error, parent=self)
            return

        safe = "".join(c if c.isalnum() else "_" for c in self.topic.get().strip())[:40]
        path = filedialog.asksaveasfilename(
            parent=self, title="PDF'i kaydet", defaultextension=".pdf",
            initialdir=str(APP_DIR), initialfile=f"{safe}_sorular.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            self._set_status("Kaydetme iptal edildi.")
            return
        try:
            build_pdf(qset, Path(path))
        except Exception as e:
            self._set_status(f"PDF oluşturulamadı: {e}", error=True)
            return
        self._set_status(f"✅  Kaydedildi: {Path(path).name}")
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    ctk.set_appearance_mode("system")
    App().mainloop()
