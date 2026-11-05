"""Kendi kendine öğrenme (sahibin onayı 2026-11-05): Orion cevabı otomatik denetlenebilen problemleri (kodla üretilen
matematik, GSM8K/AQuA/SVAMP çevirisi "final" alanlı) kendisi çözer; yalnızca son cevabı DOĞRU olan çözümleri bir
sonraki eğitimin ek diyalog verisine yazar. Başka model yok: veri Orion'un kendi çıktısı + kod denetimi.

Çıktı satırı: {"id", "q", "a", "final", "license": "orion-kendi", "source", "training_allowed": true,
"model_uretimi": false, "orion_kendi": true}. chat.extra_dialogues bu lisansı kabul eder."""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import re
import time
from pathlib import Path

LICENSE = "orion-kendi"
NUM = re.compile(r"-?\d+(?:[.,]\d+)?(?:/\d+)?")


def _num(s: str):
    s = s.strip().replace(" ", "")
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a.replace(",", ".")) / float(b)
        except (ValueError, ZeroDivisionError):
            return None
    s = s.replace(",", ".") if s.count(",") == 1 and s.count(".") == 0 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def final_answer(text: str) -> str | None:
    """Cevaptaki son sayı (Türkçe "Cevap: 12" ya da metnin sonundaki sayı)."""
    m = re.search(r"(?:cevap|sonuç|yanıt)\w*\s*[:=]?\s*(" + NUM.pattern + ")", text, re.I)
    if m:
        return m.group(1)
    nums = NUM.findall(text)
    return nums[-1] if nums else None


def is_correct(answer: str, gold: str) -> bool:
    a, g = final_answer(answer), final_answer(str(gold)) or str(gold)
    if a is None:
        return False
    x, y = _num(a), _num(g)
    if x is None or y is None:
        return a.strip().lower() == g.strip().lower()
    return abs(x - y) <= 1e-6 * max(1.0, abs(y))


def good_reasoning(answer: str) -> bool:
    """Yalnız sonuç değil çözüm adımı da olmalı; tekrar/bozuk metin olmamalı."""
    from .dialogs import _degenerate
    return len(answer) >= 25 and not _degenerate(answer.lower()) and (
        answer.count(".") + answer.count("=") + answer.count("\n") >= 2)


def load_problems(paths: list[Path], limit: int, seed: int = 1) -> list[dict]:
    """dmmath (q, a) ve çeviri (turns + final) satırları → {q, gold, src}."""
    out = []
    for p in paths:
        op = gzip.open if str(p).endswith(".gz") else open
        with op(p, "rt", encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if r.get("training_allowed") is not True:
                    continue
                if r.get("final") is not None and r.get("turns"):
                    out.append({"q": r["turns"][0][0], "gold": str(r["final"]), "src": r.get("source", "")})
                elif r.get("q") and r.get("a") and str(r.get("source", "")).startswith("google-deepmind/mathematics"):
                    g = final_answer(r["a"])
                    if g is not None:
                        out.append({"q": r["q"], "gold": g, "src": r["source"]})
    random.Random(seed).shuffle(out)
    return out[:limit]


def run(model, bpe, problems: list[dict], out: Path, k: int = 4, budget_min: float = 60, max_new: int = 160,
        generate=None, prompt_for=None) -> dict:
    """Her problem için k örnek (sıcaklık 0.8); doğru ve adımlı ilk çözüm yazılır."""
    if generate is None or prompt_for is None:
        from .chat import generate as _g, prompt_for as _p
        generate, prompt_for = generate or _g, prompt_for or _p
    t0, tried, solved, kept = time.time(), 0, 0, 0
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for i, pr in enumerate(problems):
            if budget_min and time.time() - t0 > budget_min * 60:
                break
            tried += 1
            hit = None
            any_ok = False
            for s in range(k):
                ans = generate(model, bpe, prompt_for(pr["q"]), max_new=max_new, temperature=0.8, seed=i * 31 + s)
                if is_correct(ans, pr["gold"]):
                    any_ok = True
                    if good_reasoning(ans):
                        hit = ans
                        break
            solved += any_ok
            if hit:
                kept += 1
                h = hashlib.sha1((pr["q"] + "|" + hit).encode()).hexdigest()[:14]
                f.write(json.dumps({"id": f"orion-kendi-{h}", "q": pr["q"], "a": hit, "final": pr["gold"],
                                    "license": LICENSE, "training_allowed": True, "model_uretimi": False,
                                    "orion_kendi": True, "source": "Orion kendi çözümü (son cevap kodla doğrulandı)",
                                    "problem_kaynak": pr["src"],
                                    "attribution": "Orion'un kendi çözümü; problem kaynağı: " + pr["src"]},
                                   ensure_ascii=False) + "\n")
    st = {"denenen": tried, "cozulen": solved, "yazilan": kept, "oran": round(solved / tried, 4) if tried else 0.0,
          "k": k, "sure_sn": round(time.time() - t0)}
    Path(str(out) + ".stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def main(argv=None) -> None:
    import argparse
    import torch
    from .bpe import BPE
    from .export import load_quantized
    ap = argparse.ArgumentParser(prog="orion_core.selflearn")
    ap.add_argument("--model", required=True, help="dışa aktarılmış klasör (model.bin + tokenizer.json)")
    ap.add_argument("--problems", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--budget-min", type=float, default=60)
    a = ap.parse_args(argv)
    m = load_quantized(Path(a.model) / "model.bin")
    if torch.cuda.is_available():
        m = m.to("cuda")
    bpe = BPE.load(Path(a.model) / "tokenizer.json")
    st = run(m, bpe, load_problems([Path(p) for p in a.problems], a.limit), Path(a.out), a.k, a.budget_min)
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
