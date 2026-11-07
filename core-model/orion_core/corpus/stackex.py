"""StackExchange programlama siteleri (CC BY-SA 4.0, archive.org dökümü) → translate-longform girdisi.

Her soru için: başlık + soru gövdesi + en iyi cevap (kabul edilen, yoksa en yüksek puanlı; puan ≥ 1). HTML parçalanır:
düz yazı paragrafları {"en": …} (çevrilir), kod blokları {"kod": …} (OLDUĞU GİBİ kalır). Atıf: soru ve cevabın adresi
ve yazar profili (site/users/<id>). Model üretimi yok."""
from __future__ import annotations

import html as H
import json
import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

PRE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S | re.I)
BLOCK = re.compile(r"</?(p|li|h[1-6]|blockquote|ul|ol|br)\b[^>]*>", re.I)
TAG = re.compile(r"<[^>]+>")


def segments(body: str, max_code: int = 4000) -> list[dict]:
    """HTML gövde → [{"en": paragraf} | {"kod": kod}] sırayla."""
    out: list[dict] = []
    pos = 0
    for m in PRE.finditer(body or ""):
        out += _prose(body[pos:m.start()])
        code = H.unescape(TAG.sub("", m.group(1))).strip("\n")
        if code.strip():
            out.append({"kod": code[:max_code]})
        pos = m.end()
    out += _prose((body or "")[pos:])
    return out


def _prose(s: str) -> list[dict]:
    s = BLOCK.sub("\n", s)
    # satır içi kod `x` olarak kalır (çevirmen genelde dokunmaz; tr_reject sayı/biçim denetler)
    s = re.sub(r"<code>(.*?)</code>", lambda m: "`" + TAG.sub("", m.group(1)) + "`", s, flags=re.S)
    s = H.unescape(TAG.sub("", s))
    return [{"en": p.strip()} for p in s.split("\n") if len(p.strip()) >= 20]


def build(posts_xml: Path, site: str, out_dir: Path, n_shards: int, min_score: int = 1, max_docs: int = 0) -> dict:
    """Posts.xml (tek geçiş; sorular cevaplardan önce gelir) → out_dir/se-<site>-KK.jsonl."""
    base = f"https://{site}"
    qs: dict[str, dict] = {}
    best: dict[str, tuple[int, str, str, str]] = {}  # soru → (puan, cevap id, gövde, yazar)
    st = Counter()
    for _, el in ET.iterparse(str(posts_xml), events=("end",)):
        if el.tag != "row":
            continue
        a = el.attrib
        t, score = a.get("PostTypeId"), int(a.get("Score", "0"))
        if t == "1" and score >= min_score and a.get("AnswerCount", "0") != "0":
            qs[a["Id"]] = {"title": a.get("Title", ""), "body": a.get("Body", ""), "acc": a.get("AcceptedAnswerId"),
                           "user": a.get("OwnerUserId", ""), "tags": a.get("Tags", "")}
        elif t == "2" and score >= min_score and a.get("ParentId") in qs:
            pid = a["ParentId"]
            accepted = qs[pid]["acc"] == a["Id"]
            key = (10**9 if accepted else score)
            if pid not in best or key > best[pid][0]:
                best[pid] = (key, a["Id"], a.get("Body", ""), a.get("OwnerUserId", ""))
        el.clear()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = site.split(".")[0]
    fs = [open(out_dir / f"se-{slug}-{k:02d}.jsonl", "w", encoding="utf-8") for k in range(n_shards)]
    for i, (qid, q) in enumerate(qs.items()):
        if max_docs and st["belge"] >= max_docs:
            break
        if qid not in best:
            st["cevapsiz"] += 1
            continue
        _, aid, abody, auser = best[qid]
        paras = [{"en": H.unescape(q["title"])}] + segments(q["body"]) + [{"en": "Answer:"}] + segments(abody)
        if sum(1 for p in paras if "en" in p) < 3:
            st["kisa"] += 1
            continue
        qurl, aurl = f"{base}/q/{qid}", f"{base}/a/{aid}"
        authors = ", ".join(f"{base}/users/{u}" for u in (q["user"], auser) if u)
        rec = {"id": f"se-{slug}-{qid}", "kaynak": f"stackexchange-{slug}", "source": f"{site} — {H.unescape(q['title'])}",
               "kategori": "kod_soru", "license": "cc-by-sa-4.0", "title": H.unescape(q["title"]), "url": qurl,
               "paras": paras,
               "attribution": f"Stack Exchange ({site}) soru {qurl} ve cevap {aurl}; yazarlar {authors or 'bilinmiyor'}; "
                              f"CC BY-SA 4.0; açıklamalar İngilizceden Türkçeye makine çevirisi (kod değiştirilmedi)"}
        fs[i % n_shards].write(json.dumps(rec, ensure_ascii=False) + "\n")
        st["belge"] += 1
        st["kod_blok"] += sum(1 for p in paras if "kod" in p)
    for f in fs:
        f.close()
    return {"site": site, "soru": len(qs), **dict(st)}


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="orion_core.corpus.stackex")
    ap.add_argument("--posts", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shards", type=int, default=5)
    a = ap.parse_args(argv)
    print(json.dumps(build(Path(a.posts), a.site, Path(a.out), a.shards), ensure_ascii=False))


if __name__ == "__main__":
    main()
