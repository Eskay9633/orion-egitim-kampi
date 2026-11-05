"""Toplayıcılar. Her biri yalnız kendi parçasını (shard) işler, süre bütçesi dolunca imleci kaydedip çıkar; sonraki iş
kaldığı yerden sürer. Her belge: kaynak, kategori, lisans, atıf, adres alanlarıyla yazılır (training_allowed=true yalnız
lisans kapısından geçmiş kaynaklarda)."""
from __future__ import annotations

import bz2
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from xml.etree import ElementTree as ET

from . import config as C
from .net import Polite, RobotsDisallowed
from .shards import ShardWriter, State
from .text import (clean_pdf_text, doc_hash, html_to_text, is_turkish, norm, para_hashes, quality_reason,
                   scrub_personal, strip_wikitext)


class GateError(RuntimeError):
    pass


class CaptchaError(RuntimeError):
    pass


def stable_part(key: str, n: int) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % n


def pdftotext(data: bytes) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.pdf"
        p.write_bytes(data)
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", "-q", str(p), "-"], capture_output=True, timeout=120)
        return r.stdout.decode("utf-8", "replace")


@dataclass
class Ctx:
    name: str
    spec: dict
    cfg: dict
    net: Polite
    writer: ShardWriter
    state: State
    work: Path
    shard: int
    n_shards: int
    deadline: float
    report: dict = field(default_factory=dict)
    pdf_to_text: Callable[[bytes], str] = pdftotext
    clock: Callable[[], float] = time.time
    stats: Counter = field(default_factory=Counter)

    def time_up(self) -> bool:
        return self.clock() > self.deadline

    def emit(self, text: str, **meta) -> bool:
        s = self.spec
        text = norm(text)
        if s.get("kisisel_veri_temizle"):
            text = scrub_personal(text)
        if s.get("kategori") == "meclis":  # tutanaklar: kaynaklar arası/oturumlar arası paragraf tekrarı
            paras = [p for p in text.split("\n") if p.strip()]
            keep = []
            for p in paras:
                h = "p" + doc_hash(p)
                if len(p) >= 80 and h in self.state.seen:
                    self.stats["paragraf_tekrar"] += 1
                    continue
                if len(p) >= 80:
                    self.state.seen.add(h)
                keep.append(p)
            text = "\n".join(keep)
        why = quality_reason(text, int(s.get("en_az_karakter", 300)))
        if why:
            self.stats["nitelik_" + why] += 1
            return False
        if not is_turkish(text):
            self.stats["turkce_degil"] += 1
            return False
        h = doc_hash(text)
        if h in self.state.seen:
            self.stats["tekrar"] += 1
            return False
        self.state.seen.add(h)
        lic = meta.pop("license", None) or s["lisans"]
        att = meta.pop("attribution", None) or s.get("atif", s.get("ad"))
        for i, part in enumerate(split_long(text)):
            rec = {"id": f"{self.name}-{h}" + (f"-{i}" if i else ""), "text": part, "kaynak": self.name,
                   "source": s.get("ad", self.name), "kategori": s["kategori"], "license": lic, "attribution": att,
                   "training_allowed": True, "model_uretimi": False}
            rec.update({k: v for k, v in meta.items() if v})
            self.writer.write(rec)
        self.stats["belge"] += 1
        return True


def split_long(text: str, limit: int = 100_000) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, cur, n = [], [], 0
    for p in text.split("\n"):
        if n + len(p) > limit and cur:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += len(p) + 1
    if cur:
        out.append("\n".join(cur))
    return out


# --------------------------------------------------------------------------- Wikimedia dökümleri

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def iter_pages(path: Path):
    """(başlık, ad alanı, metin, yönlendirme mi) — bz2 XML dökümünü akışla okur."""
    op = bz2.open if str(path).endswith(".bz2") else open
    with op(path, "rb") as f:
        title = ns = text = None
        redirect = False
        for ev, el in ET.iterparse(f, events=("end",)):
            t = _local(el.tag)
            if t == "title":
                title = el.text
            elif t == "ns":
                ns = el.text
            elif t == "redirect":
                redirect = True
            elif t == "text":
                text = el.text or ""
            elif t == "page":
                yield title, ns, text or "", redirect
                title = ns = text = None
                redirect = False
                el.clear()


def wiki_domain(name: str) -> str:
    return f"{name[:2]}.{name[2:]}.org"


def c_wikidump(ctx: Ctx) -> bool:
    dump = ctx.work / Path(ctx.spec["url"]).name
    if not dump.exists():
        ctx.net.download(ctx.spec["url"], dump)
    start = ctx.state["imlec"] or 0
    for i, (title, ns, text, redirect) in enumerate(iter_pages(dump)):
        if i < start or i % ctx.n_shards != ctx.shard:
            continue
        if ns != "0" or redirect or text.lstrip().lower().startswith("#yönlendir") or text.lstrip().lower().startswith("#redirect"):
            ctx.stats["ad_alani_ya_da_yonlendirme"] += 1
            continue
        ctx.emit(strip_wikitext(text), title=title, url=f"https://{wiki_domain(ctx.name)}/wiki/{quote((title or '').replace(' ', '_'))}")
        if ctx.time_up():
            ctx.state["imlec"] = i + 1
            return False
    return True


# --------------------------------------------------------------------------- arşivler (TBMM Corpus, ParlaMint-TR)

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def tei_text(data: bytes) -> str:
    root = ET.fromstring(data)
    segs = [("".join(el.itertext())).strip() for el in root.iter() if _local(el.tag) in ("seg",)]
    if not segs:
        segs = [("".join(el.itertext())).strip() for el in root.iter() if _local(el.tag) in ("u", "p")]
    return "\n".join(s for s in segs if s)


def plain_text(data: bytes) -> str:
    t = data.decode("utf-8", "replace")
    lines = []
    for ln in t.split("\n"):
        if "\t" in ln:   # ParlaMint .txt: "<konuşma kimliği>\t<metin>"
            ln = ln.split("\t")[-1]
        lines.append(ln)
    return "\n".join(lines)


def iter_archive(path: Path):
    """(üye adı, bayt) — tar/tgz/zip ya da tek dosya."""
    p = str(path)
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            for n in sorted(z.namelist()):
                if not n.endswith("/"):
                    yield n, z.read(n)
    elif tarfile.is_tarfile(p):
        with tarfile.open(p) as t:
            for m in t:
                if m.isfile():
                    yield m.name, t.extractfile(m).read()
    else:
        yield path.name, Path(p).read_bytes()


def archive_urls(ctx: Ctx) -> list[str]:
    urls = list(ctx.spec.get("indir_url") or [])
    if not urls:  # keşif raporunun bulduğu indirme adayları (uye_deseni ile süzülür)
        pat = ctx.spec.get("uye_deseni") or ""
        urls = [u for u in (ctx.report.get("indirme_adaylari") or []) if pat in u.rsplit("/", 1)[-1]]
    if not urls:
        raise GateError(f"{ctx.name}: indirme adresi yok (indir_url boş ve keşif raporunda aday yok)")
    return urls


def c_arsiv(ctx: Ctx) -> bool:
    after = ctx.spec.get("tarih_sonra")
    pat = ctx.spec.get("uye_deseni")
    cur = ctx.state["imlec"] or [0, 0]
    for ui, url in enumerate(archive_urls(ctx)):
        if ui < cur[0]:
            continue
        local = ctx.work / f"{ctx.name}-{ui}-{Path(url.split('?')[0]).name or 'arsiv'}"
        if not local.exists():
            ctx.net.download(url, local)
        for mi, (member, data) in enumerate(iter_archive(local)):
            if (ui == cur[0] and mi < cur[1]) or mi % ctx.n_shards != ctx.shard:
                continue
            base = member.rsplit("/", 1)[-1]
            if pat and pat not in member:
                continue
            if ".ana." in base or base.endswith(("-ana.xml", ".conllu", ".vert")):  # dilbilimsel işaretli kopyalar
                continue
            m = DATE_RE.search(base)
            date = "-".join(m.groups()) if m else None
            if after and date and date < after:
                ctx.stats["tarih_oncesi"] += 1
                continue
            if base.endswith(".xml"):
                try:
                    text = tei_text(data)
                except ET.ParseError:
                    ctx.stats["xml_bozuk"] += 1
                    continue
            elif base.endswith((".txt", ".text")):
                text = plain_text(data)
            else:
                continue
            ctx.emit(text, title=base, date=date, url=url)
            if ctx.time_up():
                ctx.state["imlec"] = [ui, mi + 1]
                return False
        cur = [ui + 1, 0]
        ctx.state["imlec"] = cur
    return True


# --------------------------------------------------------------------------- DergiPark OAI-PMH

OAI = "{http://www.openarchives.org/OAI/2.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
TR_LANG = {"tr", "tur", "turkish", "türkçe", "turkce", "tr-tr"}
PDF_LINK = re.compile(r"https?://dergipark\.org\.tr/(?:tr|en)/download/article-file/\d+")
PDF_REL = re.compile(r"/(?:tr|en)/download/article-file/\d+")


def classify_rights(values: list[str]) -> str | None:
    """dc:rights değerlerinden lisans; yalnız AÇIK ve TEK anlamlı olanı döner (sürümsüz 'CC BY' → None)."""
    found = set()
    for v in values:
        s = (v or "").lower()
        for m in re.finditer(r"creativecommons\.org/licenses/([a-z\-]+)/(\d\.\d)", s):
            found.add(f"cc-{m.group(1)}-{m.group(2)}")
        if "creativecommons.org/publicdomain/zero" in s or re.search(r"\bcc0\b", s):
            found.add("cc0-1.0")
        for m in re.finditer(r"\bcc[ \-]?(by(?:[ \-](?:nc|sa|nd))*)[ \-]?(\d\.\d)?(?![\w.])", s):
            kind = re.sub(r"[ \-]+", "-", m.group(1))
            found.add(f"cc-{kind}-{m.group(2)}" if m.group(2) else f"cc-{kind}")
        for m in re.finditer(r"attribution(?:[ \-]+(noncommercial|sharealike|noderivatives|no derivatives))*[ \-]+(\d\.\d)", s):
            kind = {"noncommercial": "by-nc", "sharealike": "by-sa"}.get(m.group(1) or "", "by" if not m.group(1) else "by-nd")
            found.add(f"cc-{kind}-{m.group(2)}")
    found = {f for f in found if f}
    return found.pop() if len(found) == 1 else None


def parse_oai(xml: bytes) -> tuple[list[dict], str | None]:
    root = ET.fromstring(xml)
    err = root.find(f"{OAI}error")
    if err is not None and err.get("code") != "noRecordsMatch":
        raise RuntimeError(f"OAI hata: {err.get('code')} {err.text}")
    recs = []
    for r in root.iter(f"{OAI}record"):
        h = r.find(f"{OAI}header")
        if h is not None and h.get("status") == "deleted":
            continue
        md = {}
        for el in r.iter():
            if el.tag.startswith(DC):
                md.setdefault(el.tag[len(DC):], []).append((el.text or "").strip())
        md["_id"] = (h.findtext(f"{OAI}identifier") if h is not None else "") or ""
        recs.append(md)
    tok = root.find(f".//{OAI}resumptionToken")
    return recs, (tok.text.strip() if tok is not None and tok.text and tok.text.strip() else None)


def journals(ctx: Ctx) -> list[str]:
    js = sorted(set(ctx.spec.get("dergiler") or []) | set(ctx.report.get("dergi_listesi") or []))
    return [j for j in js if stable_part(j, ctx.n_shards) == ctx.shard]


def c_dergipark(ctx: Ctx) -> bool:
    base = ctx.spec["oai_kok"]
    ok = set(ctx.spec["kabul_lisanslar"])
    st = ctx.state["imlec"] or {}
    for j in journals(ctx):
        js = st.setdefault(j, {"token": None, "bitti": False})
        while not js["bitti"]:
            q = (f"?verb=ListRecords&resumptionToken={quote(js['token'])}" if js["token"]
                 else "?verb=ListRecords&metadataPrefix=oai_dc")
            r = ctx.net.get(f"{base}{j}/{q}")
            if r.status != 200:
                ctx.stats[f"oai_http_{r.status}"] += 1
                js["bitti"] = True
                break
            recs, tok = parse_oai(r.body)
            for k, md in enumerate(recs):
                if k < js.get("i", 0):
                    continue
                if ctx.time_up():
                    js["i"] = k     # aynı sayfa sonraki işte bu kayıttan sürer
                    ctx.state["imlec"] = st
                    return False
                lic = classify_rights(md.get("rights", []))
                if lic is None:
                    ctx.stats["lisans_acik_degil"] += 1
                    continue
                if lic not in ok:
                    ctx.stats["lisans_izinsiz:" + lic] += 1
                    continue
                langs = {x.lower() for x in md.get("language", []) if x}
                if langs and not langs & TR_LANG:
                    ctx.stats["dil"] += 1
                    continue
                pdf = next((m.group(0) for v in md.get("identifier", []) + md.get("relation", [])
                            for m in [PDF_LINK.search(v or "")] if m), None)
                page = next((v for v in md.get("identifier", []) if v.startswith("http") and "/pub/" in v), None)
                try:
                    if not pdf and page:
                        pr = ctx.net.get(page)
                        m = PDF_REL.search(pr.text()) if pr.status == 200 else None
                        pdf = ("https://dergipark.org.tr" + m.group(0)) if m else None
                    if not pdf:
                        ctx.stats["pdf_yok"] += 1
                        continue
                    pr = ctx.net.get(pdf)
                except RobotsDisallowed:
                    ctx.stats["robots"] += 1
                    continue
                if pr.status != 200 or not pr.body.startswith(b"%PDF"):
                    ctx.stats["pdf_alinamadi"] += 1
                    continue
                text = clean_pdf_text(ctx.pdf_to_text(pr.body))
                title = (md.get("title") or [""])[0]
                authors = "; ".join(a for a in md.get("creator", []) if a)
                date = (md.get("date") or [""])[0]
                ctx.emit(text, license=lic, url=page or pdf, title=title, yazarlar=authors, dergi=j, date=date,
                         attribution=f"{authors or 'Yazar(lar)'}, “{title}”, {j} (DergiPark) {date}, {lic}, {page or pdf}")
            js["token"], js["i"] = tok, 0
            js["bitti"] = tok is None
            ctx.state["imlec"] = st
            ctx.state.save()
    return True


# --------------------------------------------------------------------------- belge listesi (mevzuat, kararlar)

def doc_urls(ctx: Ctx) -> list[str]:
    s = ctx.spec
    if s.get("url_sablonu"):
        a, b = s.get("aralik") or [1, 1]
        return [s["url_sablonu"].format(n=n) for n in range(int(a), int(b) + 1)]
    src = s.get("url_listesi")
    if not src:
        raise GateError(f"{ctx.name}: url_sablonu ya da url_listesi yok")
    if str(src).startswith("http"):
        body = ctx.net.get(src).text()
    else:
        body = Path(src).read_text(encoding="utf-8")
    return [ln.strip() for ln in body.splitlines() if ln.strip().startswith("http")]


def c_belge_listesi(ctx: Ctx) -> bool:
    start = ctx.state["imlec"] or 0
    for i, url in enumerate(doc_urls(ctx)):
        if i < start or i % ctx.n_shards != ctx.shard:
            continue
        try:
            r = ctx.net.get(url)
        except RobotsDisallowed:
            ctx.stats["robots"] += 1
            continue
        if r.status != 200:
            ctx.stats[f"http_{r.status}"] += 1
        else:
            if b"captcha" in r.body[:200000].lower():
                ctx.state["imlec"] = i
                raise CaptchaError(f"{url}: CAPTCHA görüldü; toplama durduruldu (otomatik aşılmaz)")
            if r.body.startswith(b"%PDF"):
                text = ctx.pdf_to_text(r.body)
            else:
                text = html_to_text(r.text())
            ctx.emit(text, url=url)
        if ctx.time_up():
            ctx.state["imlec"] = i + 1
            return False
    return True


COLLECTORS = {"wikidump": c_wikidump, "arsiv": c_arsiv, "dergipark": c_dergipark, "belge_listesi": c_belge_listesi}


def run(cfg: dict, name: str, shard: int, out: Path, state_dir: Path, work: Path, budget_min: float,
        report: dict | None, net: Polite | None = None, pdf_to_text=None, clock=time.time) -> dict:
    """Bir kaynağın bir parçasını toplar. Kapı: config enabled + keşif durum=gecti."""
    why = C.gate(cfg, name, report)
    if why:
        raise GateError(why)
    spec = cfg["kaynaklar"][name]
    n = int(spec.get("parca", 1))
    if not (0 <= shard < n):
        raise GateError(f"{name}: parça {shard} geçersiz (0..{n - 1})")
    gap = float(cfg.get("istek_araligi_sn", 1.0))
    if spec["tur"] in ("dergipark", "belge_listesi"):
        gap *= n   # paralel parçalar aynı sunucuya: toplam hız ≤ 1/aralık
    net = net or Polite(cfg["user_agent"], gap)
    state = State(Path(state_dir) / f"durum-{name}-{shard:02d}.json")
    out, work = Path(out), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stats = {"kaynak": name, "parca": shard}
    if state["bitti"]:
        return {**stats, "bitti": True, "yeni_belge": 0, "dosyalar": []}
    writer = ShardWriter(out, f"{name}-{shard:02d}", int(cfg.get("parca_bayt", 1_800_000_000)), start_seq=state["sira"])
    ctx = Ctx(name, spec, cfg, net, writer, state, work, shard, n, clock() + budget_min * 60,
              report=((report or {}).get("kaynaklar") or {}).get(name, {}),
              pdf_to_text=pdf_to_text or pdftotext, clock=clock)
    done, err = False, None
    try:
        done = COLLECTORS[spec["tur"]](ctx)
    except CaptchaError as e:
        err = str(e)
    finally:
        had_open = writer._gz is not None
        writer.close()
        state["sira"] = writer.seq + (1 if had_open else 0)
        state["bitti"] = bool(done)
        state["belge"] += ctx.stats["belge"]
        state["karakter"] += writer.chars
        state["calisma"] += 1
        at = Counter(state["atilan"])
        at.update({k: v for k, v in ctx.stats.items() if k != "belge"})
        state["atilan"] = dict(at)
        if err:
            state["hata"] = err
        state.save()
    return {**stats, "bitti": bool(done), "yeni_belge": ctx.stats["belge"], "yeni_karakter": writer.chars,
            "dosyalar": [p.name for p in writer.files], "atilan": dict(ctx.stats), "hata": err,
            "toplam_belge": state["belge"], "istek": len(net.log)}
