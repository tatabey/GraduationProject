#!/usr/bin/env python3
"""
Yerel model indirici — ComplAI'nın çalışması için gereken modelleri
config.py'nin beklediği klasörlere indirir.

    python3 system/tools/download_models.py

İndirilenler:
  • BAAI/bge-reranker-base                                  → system/models/bge-reranker-base
      (cross-encoder reranker — TÜM retrieval için gerekli)
  • sentence-transformers/paraphrase-multilingual-mpnet-... → system/models/multilingual-mpnet
      (İngilizce-dışı belgeler için çok-dilli embedding)

Not: İngilizce embedding (BAAI/bge-large-en-v1.5) HF adıyla ilk kullanımda
sentence-transformers tarafından otomatik indirilir; yerel klasör gerektirmez.
İsterseniz --with-bge-large ile onu da önceden indirebilirsiniz.

WSL2 / IPv6 takılması: indirme asılı kalırsa `HF_HUB_ENABLE_HF_TRANSFER=0` deneyin
veya IPv4 zorlayın.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # system/
MODELS_DIR = ROOT / "models"

# (repo_id, hedef klasör adı)
REQUIRED = [
    ("BAAI/bge-reranker-base", "bge-reranker-base"),
    ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "multilingual-mpnet"),
]
OPTIONAL_BGE_LARGE = ("BAAI/bge-large-en-v1.5", "bge-large-en-v1.5")


def _download(repo_id: str, target: Path) -> None:
    from huggingface_hub import snapshot_download
    print(f"\n⏳ {repo_id}\n   → {target}")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        local_dir_use_symlinks=False,
        # ONNX/OpenVINO/TF ağırlıkları gereksiz — yalnız PyTorch + tokenizer/konfig
        ignore_patterns=["*.onnx", "*.h5", "*.tflite", "openvino/*", "onnx/*", "*.msgpack"],
    )
    print(f"   ✅ hazır: {target}")


def main() -> int:
    ap = argparse.ArgumentParser(description="ComplAI yerel modellerini indir")
    ap.add_argument("--with-bge-large", action="store_true",
                    help="İngilizce embedding'i (bge-large-en-v1.5) de yerel klasöre indir")
    args = ap.parse_args()

    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print("❌ huggingface_hub yok. Önce: pip install -r requirements.txt", file=sys.stderr)
        return 1

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = list(REQUIRED)
    if args.with_bge_large:
        jobs.append(OPTIONAL_BGE_LARGE)

    for repo_id, folder in jobs:
        target = MODELS_DIR / folder
        if target.exists() and any(target.iterdir()):
            print(f"↩︎  atlandı (zaten var): {target}")
            continue
        _download(repo_id, target)

    print("\n✅ Tamamlandı. Sunucuyu başlatabilirsiniz: python3 system/server.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
