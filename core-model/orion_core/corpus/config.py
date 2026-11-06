"""derlem-kaynaklar.json okuma + doğrulama (açık kurallar burada denetlenir; testler de bunu çağırır)."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "shared" / "core-model" / "derlem-kaynaklar.json"
TYPES = {"wikidump", "arsiv", "dergipark", "belge_listesi"}
# Bu adlar hiçbir koşulda kaynak olamaz (sahip kararı: ODC-By web taramaları ve model üretimi setler dışarıda)
FORBIDDEN = ("fineweb", "culturax", "oscar", "mc4", "c4", "metamath", "orca", "numina", "gsm8k_tr", "openhermes",
             "alpaca", "sharegpt", "ultrachat")
DEFAULT_CAPS = {"vikipedi": 0.35, "akademik": 0.20, "sozluk": 0.05, "kod": 0.15, "ceviri_metin": 0.45,
                "matematik": 0.10, "genel": None}


class ConfigError(ValueError):
    pass


def load(path: Path | str | None = None) -> dict:
    cfg = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    validate(cfg)
    return cfg


def caps(cfg: dict | None) -> dict:
    raw = (cfg or {}).get("pay_siniri") or DEFAULT_CAPS
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def validate(cfg: dict) -> None:
    allow = set(cfg.get("lisans_izinli") or [])
    if not allow:
        raise ConfigError("lisans_izinli boş")
    if any(("nc" in a.split("-")) or ("nd" in a.split("-")) or a.startswith("odc") for a in allow):
        raise ConfigError("izin listesinde NC/ND/ODC lisansı olamaz")
    c = caps(cfg)
    for k, v in c.items():
        if v is not None and not (0 < float(v) <= 1):
            raise ConfigError(f"pay_siniri.{k} 0-1 arası olmalı")
    for name, s in (cfg.get("kaynaklar") or {}).items():
        low = name.lower() + " " + str(s.get("ad", "")).lower() + " " + str(s.get("url", "")).lower()
        if any(f in low.replace("-", "").replace("_", "") for f in (x.replace("_", "") for x in FORBIDDEN)):
            raise ConfigError(f"{name}: yasak kaynak (ODC-By web taraması ya da model üretimi)")
        if s.get("model_uretimi"):
            raise ConfigError(f"{name}: model üretimi veri kabul edilmez")
        if s.get("tur") not in TYPES:
            raise ConfigError(f"{name}: bilinmeyen tür {s.get('tur')}")
        if s.get("kategori") not in c:
            raise ConfigError(f"{name}: kategori '{s.get('kategori')}' pay_siniri'nda yok")
        lic = s.get("lisans")
        if lic == "kayit-duzeyinde":
            bad = set(s.get("kabul_lisanslar") or []) - allow
            if not s.get("kabul_lisanslar") or bad:
                raise ConfigError(f"{name}: kabul_lisanslar izin listesinde değil: {sorted(bad)}")
        elif lic not in allow:
            raise ConfigError(f"{name}: lisans '{lic}' izin listesinde değil")
        if not isinstance(s.get("enabled"), bool):
            raise ConfigError(f"{name}: enabled true/false olmalı")
        if int(s.get("parca", 1)) < 1:
            raise ConfigError(f"{name}: parca ≥1 olmalı")


def gate(cfg: dict, name: str, report: dict | None) -> str | None:
    """Toplama kapısı: None = geçti; değilse Türkçe sebep. Hem config (enabled) hem keşif raporu (gecti) gerekir."""
    s = (cfg.get("kaynaklar") or {}).get(name)
    if s is None:
        return f"{name}: config'de yok"
    if not s.get("enabled"):
        return f"{name}: enabled=false (sahip keşif raporunu okuyup açmalı)"
    r = ((report or {}).get("kaynaklar") or {}).get(name)
    if not r:
        return f"{name}: keşif raporunda yok (önce kesif çalıştır)"
    if r.get("durum") != "gecti":
        return f"{name}: keşif durumu '{r.get('durum')}' ({'; '.join(r.get('sorunlar', [])[:3])})"
    return None
