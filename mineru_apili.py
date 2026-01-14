import gradio as gr
import os
import time
import requests
import base64
import zipfile
import io

# ================= AYARLAR =================
# API Keylerinizi buraya tekrar giriniz
GITHUB_TOKEN = "***REMOVED***" 
GITHUB_USER = "tatabey"
GITHUB_REPO = "pdf-depo"
MINERU_API_KEY = "***REMOVED***"

# Proje dizini
BASE_DIR = "/home/tatabey/deneme26/GraduationProject"
INTERMEDIATE_DIR = os.path.join(BASE_DIR, "data/intermediate")
# ===========================================

def main_flow(pdf_file):
    if pdf_file is None:
        return "Dosya seçilmedi.", None, ""

    try:
        # 0. Hazırlık
        if not os.path.exists(INTERMEDIATE_DIR):
            os.makedirs(INTERMEDIATE_DIR, exist_ok=True)

        # 1. ADIM: GitHub'a Yükle
        yield "⬆️ GitHub'a yükleniyor...", None, ""
        file_name = os.path.basename(pdf_file.name)
        # Benzersiz isim (Türkçe karakterleri temizlemek iyi olabilir ama şimdilik kalsın)
        unique_name = f"{int(time.time())}_{file_name}"
        
        github_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{unique_name}"
        
        with open(pdf_file.name, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")

        gh_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        gh_data = {"message": f"Upload for processing: {unique_name}", "content": content}
        
        gh_res = requests.put(github_url, headers=gh_headers, json=gh_data)
        if gh_res.status_code not in [200, 201]:
            yield f"❌ GitHub Yükleme Hatası: {gh_res.text}", None, ""
            return

        yield "⏳ GitHub Pages yayını bekleniyor (bu biraz sürebilir)...", None, ""
        
        # -----------------------------------------------------------
        # ÇÖZÜM: GitHub Pages URL Yapısı
        # Format: https://USER.github.io/REPO/FILE
        # -----------------------------------------------------------
        pages_url = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/{unique_name}"
        
        # GitHub Pages'in dosyayı indexlemesi bazen 30-60 saniye sürebilir.
        # MinerU'ya göndermeden önce linkin çalışıp çalışmadığını kontrol edelim.
        max_retries = 10
        file_ready = False
        
        for i in range(max_retries):
            yield f"⏳ Link kontrol ediliyor ({i+1}/{max_retries})...", None, ""
            try:
                # Sadece başlık bilgisini çekip var mı diye bakıyoruz
                check = requests.head(pages_url)
                if check.status_code == 200:
                    file_ready = True
                    break
            except:
                pass
            time.sleep(5) # 5 saniye bekle tekrar dene
            
        if not file_ready:
            yield "⚠️ Uyarı: Dosya GitHub Pages üzerinde henüz aktifleşmedi ama yine de deneniyor...", None, ""

        # 2. ADIM: MinerU Görevi Başlat
        yield f"🚀 MinerU başlatılıyor... \nLink: {pages_url}", None, ""
        
        m_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {MINERU_API_KEY}"}
        m_payload = {
            "url": pages_url,   # ARTIK GITHUB PAGES LINKI
            "model_version": "vlm", 
            "is_ocr": True, 
            "enable_formula": True, 
            "enable_table": True,
            "lang": "en"
        }
        
        start_res = requests.post("https://mineru.net/api/v4/extract/task", headers=m_headers, json=m_payload).json()
        
        if start_res.get("code") != 0:
            yield f"❌ MinerU Hatası: {start_res.get('msg')}", None, ""
            return

        task_id = start_res["data"].get("task_id") or start_res["data"].get("data_id")
        query_url = f"https://mineru.net/api/v4/extract/task/{task_id}"

        # 3. ADIM: Durum Takibi
        while True:
            time.sleep(5)
            r = requests.get(query_url, headers=m_headers).json()
            state = r.get("data", {}).get("state")
            
            if state == "done":
                zip_url = r["data"].get("full_zip_url")
                yield f"🎉 İşlem bitti! İndiriliyor...", None, ""
                break
            elif state == "failed":
                yield f"❌ MinerU işlemi başarısız: {r}", None, ""
                return
            else:
                yield f"⚙️ Durum: {state}...", None, ""

        # 4. ADIM: ZIP Kaydet
        zip_res = requests.get(zip_url)
        
        output_zip_name = f"{task_id}.zip"
        output_zip_path = os.path.join(INTERMEDIATE_DIR, output_zip_name)
        
        with open(output_zip_path, "wb") as f_zip:
            f_zip.write(zip_res.content)
            
        markdown_content = "⚠️ Markdown içeriği okunamadı."
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
            md_files = [f for f in z.namelist() if f.endswith('.md')]
            if md_files:
                with z.open(md_files[0]) as md_file:
                    markdown_content = md_file.read().decode('utf-8')
                    # MD dosyasını da kaydet
                    clean_name = os.path.splitext(file_name)[0] + ".md"
                    save_path = os.path.join(INTERMEDIATE_DIR, clean_name)
                    with open(save_path, "w", encoding="utf-8") as f_out:
                        f_out.write(markdown_content)
                    final_msg = f"✅ İşlem Başarılı!\nLink: {pages_url}\nDosya: {save_path}"
            else:
                final_msg = "⚠️ ZIP indi ancak içinde .md bulunamadı."

        yield final_msg, output_zip_path, markdown_content

    except Exception as e:
        yield f"❌ Beklenmeyen Hata: {str(e)}", None, ""

# --- Gradio UI ---
with gr.Blocks(title="MinerU - GitHub Pages Fix", theme=gr.themes.Soft()) as demo:
    gr.Markdown("## 📄 MinerU Pipeline (GitHub Pages Yöntemi)")
    gr.Markdown("**Not:** Dosya yüklendikten sonra linkin aktif olması 15-30 saniye sürebilir, sistem otomatik bekleyecektir.")
    
    with gr.Row():
        with gr.Column(scale=1):
            file_input = gr.File(label="PDF Yükle")
            btn = gr.Button("Başlat", variant="primary")
            status_box = gr.Textbox(label="Log", interactive=False, lines=5)
            file_output = gr.File(label="Sonuç (ZIP)")
        with gr.Column(scale=2):
            md_display = gr.Markdown(label="Önizleme", value="...")

    btn.click(fn=main_flow, inputs=[file_input], outputs=[status_box, file_output, md_display])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)