"""Orion'un ilk görsel üreticisi (sahibin onayı 2026-11-09): Türkçe açıklamadan küçük emoji tarzı ikon.

Yöntem: görsel 16x16'ya küçültülür ve sabit bir palete indirilir (216 renk = kanal başına 6 düzey + saydam); her piksel
bir "belirteç" olur. Model, sohbet beyniyle AYNI mimari (model.TinyGpt): [BOS] açıklama harfleri [SEP] 256 piksel [EOS].
Kayıp yalnız piksel + EOS konumlarında. Telefonda aynı çalışma zamanıyla (TinyGpt.kt) çalışır; piksele dönüş palet
tablosuyla. Sınır: yalnız emoji/ikon tarzı; fotoğraf DEĞİL.

Veri: gorsel-ikon Release'i (Twemoji CC BY 4.0, OpenMoji CC BY-SA 4.0, Türkçe adlar Unicode CLDR). Kodlar (emoji) %3'ü
doğrulama için ayrılır (eğitime girmez)."""
from __future__ import annotations

import base64
import gzip
import io
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from .model import GptConfig, TinyGpt

SIZE = 16
LEVELS = [0, 51, 102, 153, 204, 255]
PAD, BOS, SEP, EOS = 0, 1, 2, 3
CHARS = list("abcçdefgğhıijklmnoöpqrsştuüvwxyz0123456789 :,.-'&()!?/")
CHAR0 = 4
PIX0 = CHAR0 + len(CHARS)          # ilk piksel belirteci = saydam
N_PIX = 1 + len(LEVELS) ** 3       # saydam + 216 renk
VOCAB = PIX0 + N_PIX
MAX_CAP = 48
CTX = 320  # [BOS] + en çok 48 harf + [SEP] + 256 piksel + [EOS] = 307
DEFAULT_CFG = dict(vocab_size=VOCAB, ctx=CTX, d_model=256, n_layer=6, n_head=8, d_ff=1024, dropout=0.0)
# Renk sınavı (yalnız rapor): renk sözcüğü içeren istemde baskın rengin tonu doğru mu
COLOR_PROMPTS = ["kırmızı kalp", "yeşil daire", "mavi kare", "sarı daire", "turuncu kalp", "mor daire", "kırmızı daire",
                 "yeşil kalp", "mavi kalp", "mor kalp", "sarı kalp", "turuncu daire", "kahverengi daire", "yeşil kare"]
SAMPLE_PROMPTS = ["kırmızı kalp", "sırıtan yüz", "yeşil daire", "güneş", "kedi yüzü", "pizza", "otomobil", "yıldız",
                  "ağlayan yüz", "ateş", "elma", "roket"]


def lower_tr(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def encode_caption(s: str) -> list[int]:
    ids = [CHAR0 + CHARS.index(c) for c in lower_tr(s) if c in CHARS]
    return ids[:MAX_CAP]


def quantize(png: bytes) -> list[int]:
    """PNG → SIZE*SIZE piksel belirteci (satır satır)."""
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGBA").resize((SIZE, SIZE), Image.BOX)
    a = np.asarray(im).astype(np.int32)
    idx = np.rint(a[..., :3] / 51.0).clip(0, 5).astype(np.int32)
    col = 1 + idx[..., 0] * 36 + idx[..., 1] * 6 + idx[..., 2]
    tok = np.where(a[..., 3] < 128, 0, col)
    return [PIX0 + int(t) for t in tok.reshape(-1)]


def to_rgba(pix: list[int]) -> np.ndarray:
    """Piksel belirteçleri → SIZE x SIZE x 4 (uint8)."""
    out = np.zeros((SIZE * SIZE, 4), dtype=np.uint8)
    for i, t in enumerate(pix[:SIZE * SIZE]):
        p = t - PIX0
        if 1 <= p < N_PIX:
            p -= 1
            out[i] = (LEVELS[p // 36], LEVELS[(p // 6) % 6], LEVELS[p % 6], 255)
    return out.reshape(SIZE, SIZE, 4)


def load_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for ln in f:
                r = json.loads(ln)
                if r.get("training_allowed") is not True:
                    continue
                caps = [r["ad_tr"]] + [k for k in r.get("anahtar_tr", []) if k != r["ad_tr"]]
                caps = [c for c in caps if encode_caption(c)]
                if caps:
                    rows.append({"kod": r["kod"], "kaynak": r["kaynak"], "caps": caps,
                                 "pix": quantize(base64.b64decode(r["png_b64"]))})
    return rows


def split(rows: list[dict], val_frac: float = 0.03, seed: int = 1) -> tuple[list[dict], list[dict]]:
    """Doğrulama: emoji kodlarının %3'ü (iki kaynaktaki aynı emoji de doğrulamada kalır)."""
    kods = sorted({r["kod"] for r in rows})
    random.Random(seed).shuffle(kods)
    val = set(kods[:max(1, int(len(kods) * val_frac))])
    return [r for r in rows if r["kod"] not in val], [r for r in rows if r["kod"] in val]


def make_batch(rows: list[dict], n: int, rng: random.Random) -> tuple[torch.Tensor, torch.Tensor]:
    xs, ys = [], []
    for _ in range(n):
        r = rng.choice(rows)
        cap = r["caps"][0] if rng.random() < 0.5 else rng.choice(r["caps"])
        seq = [BOS] + encode_caption(cap) + [SEP] + r["pix"] + [EOS]
        tgt = [-100] * (len(encode_caption(cap)) + 1) + r["pix"] + [EOS] + [-100]
        seq += [PAD] * (CTX + 1 - len(seq))
        tgt += [-100] * (CTX + 1 - len(tgt))
        xs.append(seq[:CTX])
        ys.append(tgt[:CTX])
    return torch.tensor(xs), torch.tensor(ys)


@torch.no_grad()
def val_loss(model: TinyGpt, rows: list[dict], n: int = 128) -> float:
    model.eval()
    x, y = make_batch(rows, n, random.Random(0))
    loss = F.cross_entropy(model(x).reshape(-1, VOCAB), y.reshape(-1), ignore_index=-100)
    model.train()
    return float(loss)


@torch.no_grad()
def generate(model: TinyGpt, caption: str, temperature: float = 0.8, top_k: int = 20, seed: int = 0) -> list[int]:
    """Açıklama → SIZE*SIZE piksel belirteci. Yalnız piksel belirteçleri arasından örneklenir."""
    model.eval()
    g = torch.Generator().manual_seed(seed)
    ids = torch.tensor([[BOS] + encode_caption(caption) + [SEP]])
    logits, past = model.forward_kv(ids)
    out = []
    for _ in range(SIZE * SIZE):
        lg = logits[0, -1, PIX0:PIX0 + N_PIX] / max(temperature, 1e-4)
        if top_k:
            v, _ = torch.topk(lg, top_k)
            lg[lg < v[-1]] = -float("inf")
        t = PIX0 + int(torch.multinomial(F.softmax(lg, -1), 1, generator=g))
        out.append(t)
        logits, past = model.forward_kv(torch.tensor([[t]]), past)
    return out


HUES = {"kırmızı": (345, 15), "turuncu": (15, 45), "sarı": (45, 70), "yeşil": (70, 170), "mavi": (190, 255),
        "mor": (255, 320)}


def dominant(rgba: np.ndarray) -> str:
    """Saydam olmayan piksellerin baskın rengi (ton aralığı; siyah/beyaz/gri ayrı)."""
    import colorsys
    px = rgba.reshape(-1, 4)
    px = px[px[:, 3] > 0][:, :3] / 255.0
    if len(px) == 0:
        return "boş"
    votes: dict[str, int] = {}
    for r, g, b in px:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if v < 0.25:
            c = "siyah"
        elif s < 0.2:
            c = "beyaz" if v > 0.8 else "gri"
        else:
            deg = h * 360
            c = next((k for k, (lo, hi) in HUES.items() if (lo <= deg < hi if lo < hi else deg >= lo or deg < hi)), "?")
        votes[c] = votes.get(c, 0) + 1
    return max(votes, key=votes.get)


def color_exam(model: TinyGpt, rows: list[dict], seeds: int = 3) -> dict:
    """Beklenen renk, aynı adlı GERÇEK görselin baskın rengidir (palet ve ton sınırları iki tarafta aynı; sözcükten
    tahmin edilmez). Verisetinde bulunmayan istem atlanır."""
    ref = {}
    for r in rows:
        ref.setdefault(r["caps"][0], dominant(to_rgba(r["pix"])))
    ok = tot = 0
    det = {}
    for p in COLOR_PROMPTS:
        want = ref.get(p)
        if want is None:
            continue
        got = [dominant(to_rgba(generate(model, p, seed=s))) for s in range(seeds)]
        hit = sum(g == want for g in got)
        ok += hit
        tot += seeds
        det[p] = {"beklenen": want, "uretilen": got}
    return {"puan": round(ok / tot, 4) if tot else None, "ayrinti": det}


def sample_grid(model: TinyGpt, path: Path, scale: int = 4) -> None:
    from PIL import Image, ImageDraw
    n = len(SAMPLE_PROMPTS)
    cell = SIZE * scale
    im = Image.new("RGBA", (n * (cell + 8), cell + 24), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    for i, p in enumerate(SAMPLE_PROMPTS):
        g = Image.fromarray(to_rgba(generate(model, p, seed=i)), "RGBA").resize((cell, cell), Image.NEAREST)
        im.alpha_composite(g, (i * (cell + 8), 0))
        d.text((i * (cell + 8), cell + 4), p[:10], fill=(0, 0, 0, 255))
    im.save(path)


def train(rows: list[dict], out: Path, steps: int, budget_min: float, batch: int = 32, lr: float = 3e-4,
          cfg: dict | None = None, log_every: int = 200) -> dict:
    torch.manual_seed(0)
    out.mkdir(parents=True, exist_ok=True)
    tr, va = split(rows)
    c = GptConfig(**(cfg or DEFAULT_CFG))
    model = TinyGpt(c)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.05, betas=(0.9, 0.95))
    rng = random.Random(1)
    t0, step, hist = time.time(), 0, []
    while step < steps and (time.time() - t0) < budget_min * 60:
        cur = lr * min(1.0, (step + 1) / 300) * 0.5 * (1 + math.cos(math.pi * min(step / steps, 1.0)))
        for gp in opt.param_groups:
            gp["lr"] = max(cur, lr * 0.05)
        x, y = make_batch(tr, batch, rng)
        loss = F.cross_entropy(model(x).reshape(-1, c.vocab_size), y.reshape(-1), ignore_index=-100)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        step += 1
        if step % log_every == 0:
            vl = val_loss(model, va)
            lv = float(loss.detach())
            hist.append({"adim": step, "egitim": round(lv, 4), "dogrulama": round(vl, 4)})
            print(f"adım {step} kayıp {lv:.3f} doğrulama {vl:.3f} ({time.time() - t0:.0f} sn)", flush=True)
    torch.save({"config": c.to_dict(), "model": model.state_dict(), "step": step}, out / "ckpt.pt")
    st = {"adim": step, "dogrulama_kaybi": round(val_loss(model, va), 4), "egitim_ornek": len(tr),
          "dogrulama_ornek": len(va), "params": model.n_params(), "sure_sn": round(time.time() - t0), "gecmis": hist}
    return st


def main(argv=None) -> None:
    import argparse
    from .export import export
    ap = argparse.ArgumentParser(prog="orion_core.imagegen")
    ap.add_argument("--data", action="append", required=True, help="gorsel-*.jsonl.gz")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--budget-min", type=float, default=300)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args(argv)
    if a.threads:
        torch.set_num_threads(a.threads)
    out = Path(a.out)
    rows = load_rows([Path(p) for p in a.data])
    print(f"{len(rows)} görsel yüklendi", flush=True)
    st = train(rows, out / "run", a.steps, a.budget_min, a.batch)
    ex = out / "export"
    ex.mkdir(parents=True, exist_ok=True)
    meta = export(out / "run" / "ckpt.pt", ex / "model.bin")
    ck = torch.load(out / "run" / "ckpt.pt", map_location="cpu", weights_only=False)
    model = TinyGpt(GptConfig(**ck["config"]))
    model.load_state_dict(meta["deq_state"])  # telefondakiyle aynı (int8) ağırlıklarla sınav ve örnekler
    st["renk_sinavi"] = color_exam(model, rows)
    sample_grid(model, ex / "ornekler.png")
    (ex / "vocab.json").write_text(json.dumps({"size": SIZE, "levels": LEVELS, "pad": PAD, "bos": BOS, "sep": SEP,
                                               "eos": EOS, "char0": CHAR0, "chars": "".join(CHARS), "pix0": PIX0,
                                               "n_pix": N_PIX}, ensure_ascii=False), encoding="utf-8")
    man = {"kind": "gorsel", "sha256": meta["sha256"], "bytes": meta["bytes"], "config": ck["config"], **st,
           "veri": "gorsel-ikon: Twemoji (CC BY 4.0), OpenMoji (CC BY-SA 4.0), Türkçe adlar Unicode CLDR (Unicode License v3)",
           "lisans_notu": "OpenMoji CC BY-SA 4.0: bu modelden üretilen görseller için atıf önerilir (doğrulanmadı: model "
                          "ağırlıklarının lisans durumu hukuken netleşmedi)"}
    (ex / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in man.items() if k != "gecmis"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
