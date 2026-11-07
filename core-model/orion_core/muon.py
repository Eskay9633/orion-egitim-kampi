"""Muon optimizer (yardımcı AdamW ile), KellerJordan/Muon (MIT) ve modded-nanogpt'nin "speedrun" çalışmasından
uyarlanmıştır. Lisans: MIT — Copyright (c) 2024 Keller Jordan. Kaynak: https://github.com/KellerJordan/Muon

Fikir: transformer bloklarındaki 2 boyutlu ağırlık matrislerinin momentum güncellemesi Newton–Schulz yinelemesiyle
yaklaşık "dik"leştirilir (orthogonalize); aynı öğrenme daha az adımda gelir. Gömme, LayerNorm ve sapmalar her zamanki
gibi AdamW ile güncellenir. Kaggle'ın P100/T4 kartları bf16'yı iyi desteklemediği için Newton–Schulz fp32 çalışır.

Kullanım: param_groups'ta her grubun "use_muon" bayrağı vardır; "base_lr" öğrenme hızı takviminin çarpanıdır."""
from __future__ import annotations

import torch


def zeropower_via_newtonschulz5(G: torch.Tensor, steps: int = 5) -> torch.Tensor:
    """G'nin yaklaşık dik (U·Vᵀ benzeri) karşılığı; beşinci dereceden Newton–Schulz (katsayılar Muon'dan)."""
    assert G.ndim >= 2
    a, b, c = (3.4445, -4.7750, 2.0315)
    X = G.float()
    if G.size(-2) > G.size(-1):
        X = X.mT
    X = X / (X.norm(dim=(-2, -1), keepdim=True) + 1e-7)
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * A @ A
        X = a * X + B @ X
    if G.size(-2) > G.size(-1):
        X = X.mT
    return X


def muon_update(grad, momentum, beta=0.95, ns_steps=5, nesterov=True):
    momentum.lerp_(grad, 1 - beta)
    update = grad.lerp_(momentum, beta) if nesterov else momentum
    update = zeropower_via_newtonschulz5(update, steps=ns_steps)
    update *= max(1, grad.size(-2) / grad.size(-1)) ** 0.5
    return update


def adam_update(grad, buf1, buf2, step, betas, eps):
    buf1.lerp_(grad, 1 - betas[0])
    buf2.lerp_(grad.square(), 1 - betas[1])
    buf1c = buf1 / (1 - betas[0] ** step)
    buf2c = buf2 / (1 - betas[1] ** step)
    return buf1c / (buf2c.sqrt() + eps)


class MuonWithAuxAdam(torch.optim.Optimizer):
    """Tek cihazlı Muon + AdamW. Gruplar: {"params", "use_muon": True, "lr", "momentum", "weight_decay"} ya da
    {"params", "use_muon": False, "lr", "betas", "eps", "weight_decay"}."""

    def __init__(self, param_groups):
        for g in param_groups:
            if g["use_muon"]:
                g.setdefault("lr", 0.02)
                g.setdefault("momentum", 0.95)
                g.setdefault("weight_decay", 0.0)
            else:
                g.setdefault("lr", 3e-4)
                g.setdefault("betas", (0.9, 0.95))
                g.setdefault("eps", 1e-10)
                g.setdefault("weight_decay", 0.0)
            g.setdefault("base_lr", g["lr"])
        super().__init__(param_groups, dict())

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                state = self.state[p]
                if group["use_muon"]:
                    if len(state) == 0:
                        state["momentum_buffer"] = torch.zeros_like(p)
                    update = muon_update(p.grad, state["momentum_buffer"], beta=group["momentum"])
                    p.mul_(1 - group["lr"] * group["weight_decay"])
                    p.add_(update.reshape(p.shape).to(p.dtype), alpha=-group["lr"])
                else:
                    if len(state) == 0:
                        state["exp_avg"] = torch.zeros_like(p)
                        state["exp_avg_sq"] = torch.zeros_like(p)
                        state["step"] = 0
                    state["step"] += 1
                    update = adam_update(p.grad, state["exp_avg"], state["exp_avg_sq"], state["step"],
                                         group["betas"], group["eps"])
                    p.mul_(1 - group["lr"] * group["weight_decay"])
                    p.add_(update, alpha=-group["lr"])
        return loss


MUON_KEYS = ("qkv.weight", "proj.weight", "fc1.weight", "fc2.weight")


def build(model, lr: float, muon_lr: float = 0.02, weight_decay: float = 0.1) -> MuonWithAuxAdam:
    """Blok içi 2B ağırlıklar Muon; gömme/LN/sapmalar (paylaşımlı çıkış dahil) AdamW."""
    mu, rest = [], []
    for n, p in model.named_parameters():
        (mu if n.startswith("blocks.") and n.endswith(MUON_KEYS) and p.ndim == 2 else rest).append(p)
    return MuonWithAuxAdam([
        dict(params=mu, use_muon=True, lr=muon_lr, momentum=0.95, weight_decay=0.01),
        dict(params=rest, use_muon=False, lr=lr, betas=(0.9, 0.95), weight_decay=weight_decay),
    ])
