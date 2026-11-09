"""Testli kod problemleri: HumanEval (MIT; YALNIZ SINAV), MBPP (google-research deposu, Apache-2.0) ve APPS (MIT).

- humaneval_exam: Orion'un kodlama sınavı (pass@1, açgözlü). Her problemde Orion fonksiyonu yazar, testler kum
  havuzunda çalışır (codeexec). Eğitime GİRMEZ.
- training_dialogs: MBPP/APPS insan yazımı çözümleri → ek diyalog satırları (q: Türkçe yönerge + problem, a: kod).
  Problem metni şimdilik İngilizce kalır (kod İngilizce; çeviri sonraki adım). Bağlama sığmayanlar atılır.
- self_problems: kodla kendi kendine öğrenme için testli problemler (selflearn.run_code)."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

HE_LICENSE = "mit"
MBPP_LICENSE = "apache-2.0"   # google-research/google-research deposunun LICENSE dosyası (README'de ayrıca yok)
APPS_LICENSE = "mit"
Q_PREFIX = "Şu problemi Python ile çöz:\n"


def _jsonl(path: Path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                yield json.loads(ln)


# --------------------------------------------------------------------------- sınav

def humaneval_prompt(p: dict) -> str:
    return "Şu Python fonksiyonunu tamamla:\n```python\n" + p["prompt"].rstrip() + "\n```"


def humaneval_exam(problems: list[dict], solve) -> dict:
    """solve(soru_metni) → cevap metni. Dönen: {puan, gecen, toplam, ornekler}."""
    from .codeexec import extract_code, passes_asserts
    passed, samples = 0, []
    for p in problems:
        reply = solve(humaneval_prompt(p)) or ""
        code = extract_code(reply, p["prompt"])
        ok = passes_asserts(code, p["test"] + f"\ncheck({p['entry_point']})\n")
        passed += ok
        if len(samples) < 5:
            samples.append({"gorev": p["task_id"], "gecti": ok, "cevap": reply[:400]})
    n = len(problems)
    return {"puan": round(passed / n, 4) if n else 0.0, "gecen": passed, "toplam": n, "ornekler": samples}


# --------------------------------------------------------------------------- eğitim diyalogları

def mbpp_rows(path: Path) -> list[dict]:
    out = []
    for r in _jsonl(path):
        out.append({"id": f"mbpp-{r['task_id']}", "soru": r["text"], "kod": r["code"], "testler": "\n".join(r["test_list"]),
                    "kurulum": r.get("test_setup_code", ""), "license": MBPP_LICENSE,
                    "source": "google-research/mbpp", "attribution": "MBPP (Austin ve ark. 2021), google-research, Apache-2.0"})
    return out


def apps_rows(root: Path, split: str = "train", max_chars: int = 1800) -> list[dict]:
    """APPS klasörü (train/<id>/question.txt, solutions.json, input_output.json)."""
    out = []
    for d in sorted((Path(root) / split).iterdir()):
        try:
            q = (d / "question.txt").read_text(encoding="utf-8")
            sols = json.loads((d / "solutions.json").read_text(encoding="utf-8")) if (d / "solutions.json").exists() else []
            io = json.loads((d / "input_output.json").read_text(encoding="utf-8")) if (d / "input_output.json").exists() else {}
        except Exception:
            continue
        if not sols or len(q) > max_chars:
            continue
        sol = min(sols, key=len)
        if len(sol) > max_chars:
            continue
        cases = list(zip(io.get("inputs", []), io.get("outputs", [])))[:5] if not io.get("fn_name") else []
        out.append({"id": f"apps-{split}-{d.name}", "soru": q.strip(), "kod": sol.strip(),
                    "io": [[str(a), str(b)] for a, b in cases if isinstance(a, str) and isinstance(b, str)],
                    "license": APPS_LICENSE, "source": "hendrycks/apps",
                    "attribution": "APPS (Hendrycks ve ark. 2021), MIT; problemler yarışma sitelerinden derlenmiş"})
    return out


def training_dialogs(rows: list[dict], max_chars: int = 2000) -> list[dict]:
    """Ek diyalog biçimi (chat.extra_dialogues): q, a, license, training_allowed."""
    out = []
    for r in rows:
        q = Q_PREFIX + r["soru"].strip()
        a = "```python\n" + r["kod"].strip() + "\n```"
        if len(q) + len(a) > max_chars:
            continue
        out.append({"id": r["id"], "q": q, "a": a, "license": r["license"], "training_allowed": True,
                    "model_uretimi": False, "source": r["source"], "attribution": r["attribution"]})
    return out


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="orion_core.codeprob")
    ap.add_argument("--mbpp", required=True)
    ap.add_argument("--apps", required=True, help="APPS klasörü (train/ test/)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    mb = mbpp_rows(Path(a.mbpp))
    ap_rows = apps_rows(Path(a.apps), "train")
    write_jsonl(training_dialogs(mb + ap_rows), out / "kod-diyalog.jsonl.gz")
    # kodla kendi kendine öğrenme için testli problemler (çözümler yazılmaz; testler var)
    write_jsonl([{k: r[k] for k in ("id", "soru", "testler", "kurulum", "license", "source") if k in r} for r in mb] +
                [{k: r[k] for k in ("id", "soru", "io", "license", "source")} for r in ap_rows if r["io"]],
                out / "kod-problem.jsonl.gz")
    st = {"mbpp": len(mb), "apps": len(ap_rows), "diyalog": len(training_dialogs(mb + ap_rows))}
    (out / "kodprob-stats.json").write_text(json.dumps(st, ensure_ascii=False))
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
