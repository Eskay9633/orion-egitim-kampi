"""Muon (speedrun, MIT): eğitim kaybı düşer, checkpoint'te optimizer türü saklanır, AdamW → Muon geçişi çökmez."""
import torch
import torch.nn.functional as F

from orion_core import muon
from orion_core.model import GptConfig, TinyGpt


def test_newton_schulz_near_orthogonal():
    g = torch.randn(64, 32)
    x = muon.zeropower_via_newtonschulz5(g)
    s = torch.linalg.svdvals(x)
    assert x.shape == g.shape and 0.5 < float(s.min()) and float(s.max()) < 1.5


def test_muon_groups_and_loss_drops():
    torch.manual_seed(0)
    m = TinyGpt(GptConfig(vocab_size=50, ctx=16, d_model=32, n_layer=2, n_head=4, d_ff=64))
    opt = muon.build(m, lr=3e-3)
    mu, ad = opt.param_groups
    assert mu["use_muon"] and all(p.ndim == 2 for p in mu["params"]) and len(mu["params"]) == 8
    assert m.tok.weight in ad["params"]
    x = torch.randint(0, 50, (8, 16))
    losses = []
    for _ in range(30):
        loss = F.cross_entropy(m(x[:, :-1]).reshape(-1, 50), x[:, 1:].reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step(); losses.append(loss.item())
    assert losses[-1] < losses[0] * 0.7, losses[::10]


def test_train_with_muon_and_switch(tmp_path):
    from orion_core import chat
    texts = [("Kullanıcı: merhaba\nOrion: merhaba, nasılsın? " * 5) + str(i) for i in range(40)]
    chat.prepare(tmp_path / "d", 10**6, vocab=300, texts=texts, open_data=False)
    cfg = dict(ctx=32, d_model=32, n_layer=2, n_head=4, d_ff=64)
    chat.train(tmp_path / "d", tmp_path / "r", steps=6, budget_min=5, batch=4, lr=1e-3, dialog_frac=0.5, config=cfg)
    ck = torch.load(tmp_path / "r" / "ckpt.pt", weights_only=False)
    assert ck.get("optim", "adamw") == "adamw"
    chat.train(tmp_path / "d", tmp_path / "r", steps=12, budget_min=5, batch=4, lr=1e-3, dialog_frac=0.5, config=cfg,
               optim="muon")
    ck = torch.load(tmp_path / "r" / "ckpt.pt", weights_only=False)
    assert ck["optim"] == "muon" and ck["step"] == 12
