"""Telefon motoru dönüştürücüsü: ORN1 → GGUF (gpt2). Numpy ileri geçişi torch modeliyle aynı olmalı; gguf paketi
kuruluysa dosya yazılır ve tensör adları/şekilleri llama.cpp'nin gpt2 düzenine uyar."""
from pathlib import Path

import numpy as np
import pytest
import torch

from orion_core.export import export, load_quantized
from orion_core.gguf_export import reference_logits, to_gguf
from orion_core.model import GptConfig, TinyGpt


@pytest.fixture()
def small_bin(tmp_path):
    torch.manual_seed(0)
    cfg = GptConfig(vocab_size=96, ctx=32, d_model=64, n_layer=2, n_head=4, d_ff=128)
    m = TinyGpt(cfg)
    torch.save({"config": cfg.to_dict(), "model": m.state_dict(), "step": 1}, tmp_path / "ckpt.pt")
    export(tmp_path / "ckpt.pt", tmp_path / "model.bin")
    return tmp_path / "model.bin"


def test_reference_matches_torch(small_bin):
    m = load_quantized(small_bin)  # telefondakiyle aynı (int8'den açılmış) ağırlıklar
    ids = [1, 5, 9, 33, 70]
    with torch.no_grad():
        ref = m(torch.tensor([ids]))[0, -1].numpy()
    got = reference_logits(small_bin, ids)
    assert np.abs(got - ref).max() < 1e-3


def test_gguf_layout(small_bin, tmp_path):
    gguf = pytest.importorskip("gguf")
    out = tmp_path / "m.gguf"
    to_gguf(small_bin, out, "f32")
    r = gguf.GGUFReader(str(out))
    names = {t.name for t in r.tensors}
    for n in ("token_embd.weight", "position_embd.weight", "blk.0.attn_qkv.weight", "blk.1.ffn_down.bias",
              "output_norm.weight", "output.weight"):
        assert n in names
    arch = r.fields["general.architecture"]
    assert bytes(arch.parts[arch.data[0]]).decode() == "gpt2"
