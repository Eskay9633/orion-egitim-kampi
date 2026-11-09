"""Görsel üretici: palet dönüşümü, toplu iş maskesi, kısa eğitim + int8 dışa aktarma + üretim uçtan uca."""
import base64
import gzip
import io
import json

import numpy as np

from orion_core import imagegen as g


def _png(rgb, alpha=255):
    from PIL import Image
    a = np.zeros((72, 72, 4), dtype=np.uint8)
    a[18:54, 18:54] = (*rgb, alpha)
    b = io.BytesIO()
    Image.fromarray(a, "RGBA").save(b, "PNG")
    return b.getvalue()


def test_quantize_roundtrip_and_dominant():
    pix = g.quantize(_png((255, 0, 0)))
    assert len(pix) == g.SIZE * g.SIZE and all(g.PIX0 <= t < g.PIX0 + g.N_PIX for t in pix)
    rgba = g.to_rgba(pix)
    assert rgba[0, 0, 3] == 0 and tuple(rgba[8, 8]) == (255, 0, 0, 255)  # köşe saydam, orta kırmızı
    assert g.dominant(rgba) == "kırmızı" and g.dominant(g.to_rgba(g.quantize(_png((0, 200, 0))))) == "yeşil"


def test_batch_masks_caption(tmp_path):
    import random
    rows = [{"kod": "x", "kaynak": "t", "caps": ["kırmızı kare"], "pix": g.quantize(_png((255, 0, 0)))}]
    x, y = g.make_batch(rows, 2, random.Random(0))
    assert x.shape == (2, g.CTX)
    n = 1 + len(g.encode_caption("kırmızı kare"))
    assert (y[0, :n] == -100).all() and int(y[0, n]) >= g.PIX0  # açıklamada kayıp yok, ilk hedef piksel


def test_tiny_train_export_generate(tmp_path):
    p = tmp_path / "g.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for i, (name, rgb) in enumerate([("kırmızı kare", (255, 0, 0)), ("yeşil kare", (0, 204, 0)),
                                         ("mavi kare", (0, 0, 255))] * 10):
            f.write(json.dumps({"kod": f"k{i}", "kaynak": "t", "ad_tr": name, "anahtar_tr": [], "training_allowed": True,
                                "png_b64": base64.b64encode(_png(rgb)).decode()}, ensure_ascii=False) + "\n")
    rows = g.load_rows([p])
    tiny = dict(vocab_size=g.VOCAB, ctx=g.CTX, d_model=32, n_layer=1, n_head=2, d_ff=64, dropout=0.0)
    st = g.train(rows, tmp_path / "run", steps=20, budget_min=2, batch=4, cfg=tiny, log_every=10)
    assert st["adim"] == 20 and st["dogrulama_kaybi"] == st["dogrulama_kaybi"]
    from orion_core.export import export, load_quantized
    meta = export(tmp_path / "run" / "ckpt.pt", tmp_path / "model.bin")
    m = load_quantized(tmp_path / "model.bin")  # telefon biçimi geri yüklenir
    pix = g.generate(m, "kırmızı kare")
    assert len(pix) == g.SIZE * g.SIZE and meta["bytes"] > 0
    ex = g.color_exam(m, rows, seeds=1)
    assert ex["puan"] is None or 0 <= ex["puan"] <= 1
