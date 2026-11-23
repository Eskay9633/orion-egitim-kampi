"""Telefon motoru (sahibin kararı 2026-11-22: "telefon için motor şart; sohbet ve komut beynini aynı anda denemek isterim").

ORN1 model dosyasını (export.py; int8 ağırlık + satır ölçeği) llama.cpp'nin GGUF biçimine çevirir. Komut beyni ve sohbet
beyni aynı yapıdadır (TinyGpt = GPT-2 düzeni: LayerNorm, birleşik qkv + sapma, GELU-tanh, öğrenilmiş konum, bağlı çıkış
ağırlığı), bu yüzden llama.cpp'nin hazır "gpt2" mimarisiyle birebir çalışır; yeni katman yazılmaz.

Belirteç ayırma motorda YAPILMAZ: uygulama kendi BPE'siyle (Kotlin BpeTokenizer) belirteç numaralarını verir, motor
yalnız sayı dizisi işler. GGUF'taki sözlük bu yüzden yalnız yer tutucudur ("t0", "t1", ...; sayısı modelin sözlüğüyle aynı).
Ağırlıklar int8'den geri açılıp (deq) yazılır; isteğe göre Q8_0'a (yaklaşık aynı boyut, NEON hızlı) ya da F16'ya sıkıştırılır.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np

from .bpe import BOS, EOS


def read_orn1(path: Path) -> tuple[dict, dict[str, np.ndarray]]:
    raw = path.read_bytes()
    if raw[:4] != b"ORN1":
        raise ValueError(f"{path}: ORN1 değil")
    hlen = struct.unpack("<I", raw[4:8])[0]
    header = json.loads(raw[8:8 + hlen])
    base = 8 + hlen
    base += (-base) % 4
    out: dict[str, np.ndarray] = {}
    for t in header["tensors"]:
        shape = t["shape"]
        n = int(np.prod(shape))
        if t["dtype"] == "f32":
            out[t["name"]] = np.frombuffer(raw, "<f4", n, base + t["offset"]).reshape(shape).astype(np.float32)
        else:
            rows = shape[0]
            s = np.frombuffer(raw, "<f4", rows, base + t["scale_offset"]).astype(np.float32)
            q = np.frombuffer(raw, np.int8, n, base + t["offset"]).reshape(shape).astype(np.float32)
            out[t["name"]] = q * s[:, None]
    return header["config"], out


def to_gguf(model_bin: Path, out: Path, qtype: str = "q8_0", name: str = "orion") -> dict:
    import gguf
    cfg, w = read_orn1(model_bin)
    d, L = cfg["d_model"], cfg["n_layer"]
    wr = gguf.GGUFWriter(str(out), "gpt2")
    wr.add_name(name)
    wr.add_context_length(cfg["ctx"])
    wr.add_embedding_length(d)
    wr.add_block_count(L)
    wr.add_feed_forward_length(cfg["d_ff"])
    wr.add_head_count(cfg["n_head"])
    wr.add_layer_norm_eps(1e-5)  # torch.nn.LayerNorm varsayılanı
    wr.add_file_type({"f32": 0, "f16": 1, "q4_0": 2, "q8_0": 7}[qtype])
    # Yer tutucu sözlük: belirteç ayırma uygulamada; motor yalnız numara işler
    vocab = cfg["vocab_size"]
    wr.add_tokenizer_model("gpt2")
    wr.add_tokenizer_pre("default")
    wr.add_token_list([f"t{i}" for i in range(vocab)])
    wr.add_token_types([gguf.TokenType.NORMAL] * vocab)
    wr.add_token_merges(["t 0"])
    wr.add_bos_token_id(BOS)
    wr.add_eos_token_id(EOS)
    wr.add_add_bos_token(False)

    # q4_0 (2026-11-23, "motor hâlâ hantal"): katman ağırlıkları 4 bit (dosya ~yarı, telefonda bellek bant genişliği
    # yarıya iner); belirteç gömmesi ve bağlı çıkış ağırlığı kaliteye duyarlı olduğu için 8 bitte kalır.
    def put(gname: str, arr: np.ndarray, keep8: bool = False) -> None:
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        if arr.ndim == 2 and qtype != "f32":
            t = {"q8_0": gguf.GGMLQuantizationType.Q8_0, "q4_0": gguf.GGMLQuantizationType.Q4_0}.get(qtype)
            if t is not None and keep8:
                t = gguf.GGMLQuantizationType.Q8_0
            if t is not None and arr.shape[1] % 32 == 0:
                qa = gguf.quants.quantize(arr, t)
                wr.add_tensor(gname, qa, raw_shape=qa.shape, raw_dtype=t)
                return
            arr = arr.astype(np.float16)
        wr.add_tensor(gname, arr)

    put("token_embd.weight", w["tok.weight"], keep8=True)
    put("position_embd.weight", w["pos.weight"])
    for i in range(L):
        p = f"blocks.{i}."
        put(f"blk.{i}.attn_norm.weight", w[p + "ln1.weight"]); put(f"blk.{i}.attn_norm.bias", w[p + "ln1.bias"])
        put(f"blk.{i}.attn_qkv.weight", w[p + "qkv.weight"]); put(f"blk.{i}.attn_qkv.bias", w[p + "qkv.bias"])
        put(f"blk.{i}.attn_output.weight", w[p + "proj.weight"]); put(f"blk.{i}.attn_output.bias", w[p + "proj.bias"])
        put(f"blk.{i}.ffn_norm.weight", w[p + "ln2.weight"]); put(f"blk.{i}.ffn_norm.bias", w[p + "ln2.bias"])
        put(f"blk.{i}.ffn_up.weight", w[p + "fc1.weight"]); put(f"blk.{i}.ffn_up.bias", w[p + "fc1.bias"])
        put(f"blk.{i}.ffn_down.weight", w[p + "fc2.weight"]); put(f"blk.{i}.ffn_down.bias", w[p + "fc2.bias"])
    put("output_norm.weight", w["ln_f.weight"]); put("output_norm.bias", w["ln_f.bias"])
    put("output.weight", w["tok.weight"], keep8=True)  # bağlı çıkış ağırlığı: açıkça yazılır
    wr.write_header_to_file()
    wr.write_kv_data_to_file()
    wr.write_tensors_to_file()
    wr.close()
    return {"config": cfg, "qtype": qtype, "bytes": out.stat().st_size}


def reference_logits(model_bin: Path, ids: list[int]) -> np.ndarray:
    """Aynı (geri açılmış) ağırlıklarla numpy ileri geçiş: son konumun logitleri (motor doğrulaması için)."""
    cfg, w = read_orn1(model_bin)
    d, h = cfg["d_model"], cfg["n_head"]
    x = w["tok.weight"][ids] + w["pos.weight"][: len(ids)]

    def ln(v, g, b):
        m = v.mean(-1, keepdims=True); s = ((v - m) ** 2).mean(-1, keepdims=True)
        return (v - m) / np.sqrt(s + 1e-5) * g + b

    def gelu(v):
        return 0.5 * v * (1 + np.tanh(np.sqrt(2 / np.pi) * (v + 0.044715 * v ** 3)))

    t = len(ids)
    mask = np.triu(np.full((t, t), -np.inf), 1)
    for i in range(cfg["n_layer"]):
        p = f"blocks.{i}."
        a = ln(x, w[p + "ln1.weight"], w[p + "ln1.bias"]) @ w[p + "qkv.weight"].T + w[p + "qkv.bias"]
        q, k, v = np.split(a, 3, axis=-1)
        hd = d // h
        q = q.reshape(t, h, hd).transpose(1, 0, 2); k = k.reshape(t, h, hd).transpose(1, 0, 2); v = v.reshape(t, h, hd).transpose(1, 0, 2)
        att = q @ k.transpose(0, 2, 1) / np.sqrt(hd) + mask
        att = np.exp(att - att.max(-1, keepdims=True)); att /= att.sum(-1, keepdims=True)
        y = (att @ v).transpose(1, 0, 2).reshape(t, d)
        x = x + y @ w[p + "proj.weight"].T + w[p + "proj.bias"]
        f = gelu(ln(x, w[p + "ln2.weight"], w[p + "ln2.bias"]) @ w[p + "fc1.weight"].T + w[p + "fc1.bias"])
        x = x + f @ w[p + "fc2.weight"].T + w[p + "fc2.bias"]
    x = ln(x, w["ln_f.weight"], w["ln_f.bias"])
    return x[-1] @ w["tok.weight"].T


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="ORN1 model.bin")
    ap.add_argument("--out", required=True)
    ap.add_argument("--qtype", default="q8_0", choices=["f32", "f16", "q8_0", "q4_0"])
    ap.add_argument("--name", default="orion")
    a = ap.parse_args(argv)
    print(json.dumps(to_gguf(Path(a.model), Path(a.out), a.qtype, a.name), ensure_ascii=False))


if __name__ == "__main__":
    main()
