"""Orion çekirdek: makine dili, veri üretici, tokenizer, küçük model, eğitim ve damıtma."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "shared"

# Kaggle bekletmesi (sahibin kararı 2026-11-21): Kaggle API'si sıradaki oturumu dışarıdan iptal ettirmiyor. Oturum kodu
# bu depodan klonladığı için, depoda kaggle/beklet.txt varsa Kaggle'da çalışan her orion_core komutu hemen durur;
# oturum ilk adımda biter, kota harcanmaz. Yalnız Kaggle'da (/kaggle/working) etkilidir; CI ve yerel çalışma etkilenmez.
_BEKLET = REPO_ROOT / "kaggle" / "beklet.txt"
if Path("/kaggle/working").is_dir() and _BEKLET.exists():
    raise SystemExit("ORION: bekletme var (kaggle/beklet.txt); Kaggle oturumu durduruldu: "
                     + _BEKLET.read_text(encoding="utf-8").strip()[:200])
