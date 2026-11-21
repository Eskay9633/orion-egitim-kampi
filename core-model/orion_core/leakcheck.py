"""Otomatik sızıntı denetleyici (2026-11-21): her eğitimin manifest'ine "eğitim verisi ölçüm kümelerine ne kadar
benziyor" raporu yazar. Eğitim akışından örnek (dış veri satırlarının tamamı + üreticiden n örnek) alınır, her ölçüm
kümesi için iki sayı verilir:
  exact  — normalize hâli (massive.norm_key) eğitimde de geçen ölçüm cümlesi sayısı (0 olmalı; eğitim zaten atar)
  near   — sözcük-Jaccard ≥ 0.8 olan en az bir eğitim cümlesi bulunan ölçüm cümlesi sayısı (yakın kopya)
Rapor yalnız bilgidir, kapıya girmez; sıçrayan bir ölçüm sonucunu açıklamaya yarar."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from . import datagen
from .massive import EVAL_FILES, EXTRA_TRAIN_FILES, SHARED, TRAIN_FILE, norm_key

REPO_SETS = ("handwritten-eval.jsonl", "blind-eval.jsonl", "ajan-sinavi.jsonl", "ajan-sinavi-2.jsonl")
NEAR = 0.8


def _read(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _toks(s: str) -> frozenset[str]:
    return frozenset(norm_key(s).split())


def eval_sets(ext_dir: Path | None) -> dict[str, list[str]]:
    out = {}
    for name in REPO_SETS:
        p = SHARED / "core-model" / name
        if p.exists():
            out[name.removesuffix(".jsonl")] = [r["src"] for r in _read(p)]
    if ext_dir:
        for key, name in EVAL_FILES.items():
            if (ext_dir / name).exists():
                out[key] = [r["src"] for r in _read(ext_dir / name)]
    return out


def train_sample(ext_dir: Path | None, n_gen: int, seed: int) -> list[str]:
    srcs = [e["src"] for e in datagen.generate(n_gen, "train", seed=seed)]
    if ext_dir:
        for name in (TRAIN_FILE, *EXTRA_TRAIN_FILES):
            if (ext_dir / name).exists():
                srcs += [r["src"] for r in _read(ext_dir / name) if r.get("training_allowed", True) is True]
    return srcs


def check(train: list[str], sets: dict[str, list[str]], near: float = NEAR) -> dict:
    keys = {norm_key(s) for s in train}
    # Ters dizin: her eğitim cümlesi yalnız en seyrek sözcüğünün altına yazılır değil, tüm sözcüklerine — aday kümesi
    # ölçüm cümlesinin en seyrek sözcüğünü paylaşanlardır (Jaccard ≥ 0.8 için ortak sözcük şart).
    tok_sets = list({t for t in (_toks(s) for s in train) if t})
    index: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(tok_sets):
        for w in t:
            index[w].append(i)
    rep = {}
    for name, srcs in sets.items():
        exact = sum(1 for s in srcs if norm_key(s) in keys)
        n_near, examples = 0, []
        for s in srcs:
            t = _toks(s)
            if not t:
                continue
            # Jaccard ≥ 0.8 ise ölçüm cümlesinin sözcüklerinin en az %80'i ortak: en seyrek iki sözcükten biri mutlaka
            # ortaktır (|t| ≥ 2 iken) — adaylar o ikisinin listelerinden
            rare = sorted(t, key=lambda w: len(index.get(w, ())))[:max(1, len(t) - int(near * len(t)) + 1)]
            cand = {i for w in rare for i in index.get(w, ())}
            if any(len(t & tok_sets[i]) / len(t | tok_sets[i]) >= near for i in cand):
                n_near += 1
                if len(examples) < 5:
                    examples.append(s)
        rep[name] = {"n": len(srcs), "exact": exact, "near": n_near, "near_frac": round(n_near / max(1, len(srcs)), 4),
                     "near_examples": examples}
    return rep


def run(ext_dir: Path | None, n_gen: int = 20000, seed: int = 7) -> dict:
    train = train_sample(ext_dir, n_gen, seed)
    return {"train_sample": len(train), "near_jaccard": NEAR, "sets": check(train, eval_sets(ext_dir))}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ext-data")
    ap.add_argument("--n-gen", type=int, default=20000)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = run(Path(a.ext_data) if a.ext_data else None, a.n_gen)
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
