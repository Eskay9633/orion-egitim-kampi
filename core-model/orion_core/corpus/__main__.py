"""python -m orion_core.corpus <komut>

  discover   --out kesif.json [--only a,b] [--journals N]
  plan       --kesif kesif.json [--only a,b]          → GitHub Actions matris JSON'u (yalnız kapıdan geçen kaynaklar)
  collect    --source S --shard K --out DIR --state DIR --work DIR --kesif kesif.json --budget-min M
  openstax   --tar a.tar.gz [--tar ...] --out DIR [--shards N]
  dmmath     --out dmmath.jsonl.gz [--per-module N] [--filter algebra__linear_1d,...]
  kod        --tar depo.tar.gz --repo sahip/ad --license SPDX --out DIR --seen tekil.txt.gz --stats kod.jsonl
  tatoeba    --tsv tur_sentences_detailed.tsv.bz2 --terms sartlar.html --out DIR
  ud         --repo UniversalDependencies/UD_Turkish-BOUN --license LICENSE.txt --dir CONLLU_KLASORU --out DIR
  commonvoice --dir TXT_KLASORU --doc lisans_belgesi.md --out DIR
  simplewiki --dump simplewiki-latest-pages-articles.xml.bz2 --out DIR --shards N --max-chars M
  kod-liste  [--lang python]                             → "dil depo" satırları (iş akışı için)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import collectors, config, discover as D


def _report(path: str | None) -> dict | None:
    return json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).exists() else None


def plan_matrix(cfg: dict, report: dict | None, only: list[str] | None = None) -> tuple[list[dict], dict]:
    jobs, skipped = [], {}
    for name, spec in cfg["kaynaklar"].items():
        if only and name not in only:
            continue
        why = config.gate(cfg, name, report)
        if why:
            skipped[name] = why
            continue
        jobs += [{"kaynak": name, "parca": k} for k in range(int(spec.get("parca", 1)))]
    return jobs, skipped


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="orion_core.corpus")
    ap.add_argument("--config", default=None, help="derlem-kaynaklar.json (varsayılan: shared/core-model/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--out", required=True)
    d.add_argument("--only")
    d.add_argument("--journals", type=int)
    p = sub.add_parser("plan")
    p.add_argument("--kesif")
    p.add_argument("--only")
    p.add_argument("--out")
    c = sub.add_parser("collect")
    c.add_argument("--source", required=True)
    c.add_argument("--shard", type=int, default=0)
    c.add_argument("--out", required=True)
    c.add_argument("--state", required=True)
    c.add_argument("--work", required=True)
    c.add_argument("--kesif", required=True)
    c.add_argument("--budget-min", type=float, default=320)
    o = sub.add_parser("openstax")
    o.add_argument("--tar", action="append", required=True)
    o.add_argument("--repo", action="append")
    o.add_argument("--out", required=True)
    o.add_argument("--shards", type=int, default=2)
    m = sub.add_parser("dmmath")
    m.add_argument("--out", required=True)
    m.add_argument("--per-module", type=int, default=2000)
    m.add_argument("--filter", default="arithmetic,algebra__linear,numbers__gcd,numbers__lcm,numbers__is_prime,"
                                          "numbers__div_remainder,numbers__round_number,comparison__pair,"
                                          "polynomials__evaluate,calculus__differentiate")
    m.add_argument("--seed", type=int, default=1)
    k = sub.add_parser("kod")
    k.add_argument("--tar", required=True)
    k.add_argument("--repo", required=True)
    k.add_argument("--license", required=True, help="GitHub API license.spdx_id")
    k.add_argument("--out", required=True)
    k.add_argument("--seen", required=True)
    k.add_argument("--stats", required=True)
    kl = sub.add_parser("kod-liste")
    kl.add_argument("--lang")
    t = sub.add_parser("tatoeba")
    t.add_argument("--tsv", required=True)
    t.add_argument("--terms", required=True)
    t.add_argument("--out", required=True)
    u = sub.add_parser("ud")
    u.add_argument("--repo", required=True)
    u.add_argument("--license", required=True)
    u.add_argument("--dir", required=True)
    u.add_argument("--out", required=True)
    cv = sub.add_parser("commonvoice")
    cv.add_argument("--dir", required=True)
    cv.add_argument("--doc", required=True)
    cv.add_argument("--out", required=True)
    sw = sub.add_parser("simplewiki")
    sw.add_argument("--dump", required=True)
    sw.add_argument("--out", required=True)
    sw.add_argument("--shards", type=int, default=20)
    sw.add_argument("--max-chars", type=int, default=60_000_000)
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    only = [x for x in (getattr(a, "only", None) or "").split(",") if x] or None
    if a.cmd == "discover":
        from .collectors import pdftotext
        import shutil
        rep = D.discover(cfg, only=only, n_journals=a.journals, pdf_to_text=pdftotext if shutil.which("pdftotext") else None)
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(rep["ozet"], ensure_ascii=False, indent=1))
    elif a.cmd == "plan":
        jobs, skipped = plan_matrix(cfg, _report(a.kesif), only)
        res = {"matris": jobs, "atlanan": skipped}
        if a.out:
            Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(res, ensure_ascii=False, indent=1), file=sys.stderr)
        print(json.dumps(jobs))
    elif a.cmd == "collect":
        try:
            st = collectors.run(cfg, a.source, a.shard, Path(a.out), Path(a.state), Path(a.work), a.budget_min,
                                _report(a.kesif))
        except collectors.GateError as e:
            print(f"HATA (kapı): {e}", file=sys.stderr)
            sys.exit(2)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / f"ozet-{a.source}-{a.shard:02d}.json").write_text(json.dumps(st, ensure_ascii=False, indent=1))
        print(json.dumps(st, ensure_ascii=False, indent=1))
    elif a.cmd == "openstax":
        from . import openstax
        print(json.dumps(openstax.collect([Path(x) for x in a.tar], Path(a.out), a.shards, a.repo), ensure_ascii=False, indent=1))
    elif a.cmd == "kod":
        from . import code
        st = code.main_one(a.tar, a.repo, a.license, cfg["kod"], a.out, a.seen, a.stats)
        print(json.dumps(st, ensure_ascii=False))
    elif a.cmd in ("tatoeba", "ud", "commonvoice", "simplewiki"):
        from . import extra
        try:
            if a.cmd == "tatoeba":
                st = extra.tatoeba(Path(a.tsv), Path(a.terms).read_text(encoding="utf-8", errors="replace"), Path(a.out))
            elif a.cmd == "ud":
                files = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(Path(a.dir).rglob("*.conllu"))}
                st = extra.ud_bank(a.repo, Path(a.license).read_text(encoding="utf-8", errors="replace"), files, Path(a.out))
            elif a.cmd == "commonvoice":
                files = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(Path(a.dir).rglob("*.txt"))}
                st = extra.common_voice(files, Path(a.doc).read_text(encoding="utf-8", errors="replace"), Path(a.out))
            else:
                st = extra.simplewiki_shards(collectors.iter_pages(Path(a.dump)), Path(a.out), a.shards, a.max_chars)
        except extra.LicenseError as e:
            print(f"HATA (lisans): {e}", file=sys.stderr)
            sys.exit(3)
        print(json.dumps(st, ensure_ascii=False))
    elif a.cmd == "kod-liste":
        for lang, repos in cfg["kod"]["depolar"].items():
            if not a.lang or a.lang == lang:
                for r in repos:
                    print(lang, r)
    elif a.cmd == "dmmath":
        from . import dmmath
        st = dmmath.build(dmmath.dm_problems(a.per_module, [x for x in a.filter.split(",") if x], a.seed), Path(a.out))
        print(json.dumps(st, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
