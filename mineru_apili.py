import gradio as gr
import os
import time
import requests
import base64
import zipfile
import io

# ================= AYARLAR =================
GITHUB_TOKEN = "***REMOVED***"
GITHUB_USER = "tatabey"
GITHUB_REPO = "pdf-depo"
MINERU_API_KEY = "***REMOVED***"

# Proje dizini ve kayıt klasörü
BASE_DIR = "/home/tatabey/deneme26/GraduationProject"
INTERMEDIATE_DIR = os.path.join(BASE_DIR, "data/intermediate")
# ===========================================

def main_flow(pdf_file):
    if pdf_file is None:
        return "Dosya seçilmedi.", None, ""

    try:
        # 0. Hazırlık: Kayıt klasörünü kontrol et
        if not os.path.exists(INTERMEDIATE_DIR):
            os.makedirs(INTERMEDIATE_DIR, exist_ok=True)

        # 1. ADIM: GitHub'a Yükle
        yield "⬆️ GitHub'a yükleniyor...", None, ""
        file_name = os.path.basename(pdf_file.name)
        unique_name = f"{int(time.time())}_{file_name}"
        github_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{unique_name}"
        
        with open(pdf_file.name, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")

        gh_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        gh_data = {"message": f"Pipeline Upload: {unique_name}", "content": content}
        
        gh_res = requests.put(github_url, headers=gh_headers, json=gh_data)
        if gh_res.status_code not in [200, 201]:
            yield f"❌ GitHub Hatası: {gh_res.text}", None, ""
            return

        # GitHub'ın dosyayı 'Raw' olarak sunması için kısa bir süre tanıyalım
        yield "⏳ GitHub senkronizasyonu bekleniyor (5 sn)...", None, ""
        time.sleep(5)

        raw_url = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/{unique_name}"
        
        # DOSYA ERİŞİLEBİLİR Mİ KONTROLÜ
        test_res = requests.head(raw_url)
        if test_res.status_code != 200:
             yield "⚠️ GitHub linki henüz hazır değil, tekrar deneniyor...", None, ""
             time.sleep(5)

        # 2. ADIM: MinerU Görevi Başlat (Dil Sabit: "en")
        yield "🚀 MinerU (VLM) başlatılıyor...", None, ""
        m_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {MINERU_API_KEY}"}
        m_payload = {
            "url": raw_url,
            "model_version": "vlm", 
            "is_ocr": True, 
            "enable_formula": True, 
            "enable_table": True,
            "lang": "en"  # Dil burada "en" (İngilizce) olarak sabitlendi
        }
        
        start_res = requests.post("https://mineru.net/api/v4/extract/task", headers=m_headers, json=m_payload).json()
        
        if start_res.get("code") != 0:
            yield f"❌ MinerU Başlatma Hatası: {start_res.get('msg')}", None, ""
            return

        task_id = start_res["data"].get("task_id") or start_res["data"].get("data_id")
        query_url = f"https://mineru.net/api/v4/extract/task/{task_id}"

        # 3. ADIM: MinerU Durum Takibi
        while True:
            time.sleep(5)
            r = requests.get(query_url, headers=m_headers).json()
            state = r.get("data", {}).get("state")
            
            if state == "done":
                zip_url = r["data"].get("full_zip_url")
                yield f"🎉 İşlem bitti! ZIP indiriliyor...", None, ""
                break
            elif state == "failed":
                yield f"❌ MinerU işlemi başarısız: {r}", None, ""
                return
            else:
                yield f"⚙️ Durum: {state} (Bekleniyor...)", None, ""

        # 4. ADIM: ZIP'i İndir, Oku ve Local Klasöre Kaydet
        zip_res = requests.get(zip_url)
        markdown_content = "⚠️ Markdown dosyası bulunamadı."
        
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
            md_files = [f for f in z.namelist() if f.endswith('.md')]
            if md_files:
                with z.open(md_files[0]) as md_file:
                    markdown_content = md_file.read().decode('utf-8')
                    
                    # Yerel kayıt ismi
                    clean_name = os.path.splitext(file_name)[0] + ".md"
                    save_path = os.path.join(INTERMEDIATE_DIR, clean_name)
                    
                    with open(save_path, "w", encoding="utf-8") as f_out:
                        f_out.write(markdown_content)
                    
                    final_msg = f"✅ Tamamlandı!\n📂 Şuraya kaydedildi: {save_path}"
            else:
                final_msg = "⚠️ ZIP içinde .md bulunamadı."

        output_zip = f"{task_id}.zip"
        with open(output_zip, "wb") as f_zip:
            f_zip.write(zip_res.content)
            
        yield final_msg, output_zip, markdown_content

    except Exception as e:
        yield f"❌ Kritik Hata: {str(e)}", None, ""

# --- Gradio UI ---
with gr.Blocks(title="MinerU Pipeline PoC", theme=gr.themes.Soft()) as demo:
    gr.Markdown("## 📄 MinerU -> Local Storage Pipeline (İngilizce)")
    gr.Markdown(f"Sistem dosyaları otomatik olarak `{INTERMEDIATE_DIR}` klasörüne İngilizce OCR ile işleyip kaydeder.")
    
    with gr.Row():
        with gr.Column(scale=1):
            file_input = gr.File(label="PDF Dosyası Yükle", file_types=[".pdf"])
            btn = gr.Button("Pipeline'ı Başlat", variant="primary")
            status_box = gr.Textbox(label="İşlem Durumu", interactive=False, lines=4)
            file_output = gr.File(label="MinerU Çıktısı (ZIP)")
            
        with gr.Column(scale=2):
            md_display = gr.Markdown(label="Markdown Önizleme", value="### PDF işlendikten sonra sonuç burada belirecek...")

    btn.click(
        fn=main_flow, 
        inputs=[file_input], 
        outputs=[status_box, file_output, md_display]
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)