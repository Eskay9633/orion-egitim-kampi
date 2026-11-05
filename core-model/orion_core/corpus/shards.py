"""Parçalı jsonl.gz yazıcı (Release varlığı başına <2GB) + işler arası sürdürülebilir durum dosyası."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

RELEASE_LIMIT = 2_000_000_000


class ShardWriter:
    """<önek>-<parça>-<sıra>.jsonl.gz; sıkıştırılmış boyut max_bytes'ı aşınca yeni dosya. Sıra durumdan sürer, böylece
    önceki işlerin Release'teki dosyalarının üzerine yazılmaz."""

    def __init__(self, out_dir: Path, prefix: str, max_bytes: int = 1_800_000_000, start_seq: int = 0,
                 flush_every: int = 16 << 20):
        if max_bytes >= RELEASE_LIMIT:
            raise ValueError("parça boyutu 2GB Release sınırının altında olmalı")
        self.dir, self.prefix, self.max = Path(out_dir), prefix, max_bytes
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seq, self.files, self._raw, self._gz = start_seq, [], None, None
        self.docs = self.chars = 0
        self.flush_every, self._pending = flush_every, 0  # zlib tamponu boyut ölçümünü geciktirmesin

    def _open(self):
        p = self.dir / f"{self.prefix}-{self.seq:04d}.jsonl.gz"
        self._raw = open(p, "wb")
        self._gz = gzip.GzipFile(fileobj=self._raw, mode="wb", compresslevel=6)
        self.files.append(p)

    def write(self, rec: dict) -> None:
        if self._gz is None:
            self._open()
        b = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
        self._gz.write(b)
        self._pending += len(b)
        if self._pending >= self.flush_every:
            self._gz.flush()
            self._pending = 0
        self.docs += 1
        self.chars += len(rec.get("text", ""))
        if self._raw.tell() >= self.max:
            self.close()
            self.seq += 1

    def close(self) -> None:
        if self._gz is not None:
            self._gz.close()
            self._raw.close()
            self._gz = self._raw = None


class State:
    """durum-<parça>.json: imleç, sonraki dosya sırası, sayaçlar, bitti mi. tekil-<parça>.txt.gz: görülen belge özetleri."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "imlec": None, "sira": 0, "belge": 0, "karakter": 0, "bitti": False, "atilan": {}, "calisma": 0}
        self.seen_path = self.path.with_name(self.path.name.replace("durum-", "tekil-").replace(".json", ".txt.gz"))
        self.seen: set[str] = set()
        if self.seen_path.exists():
            with gzip.open(self.seen_path, "rt") as f:
                self.seen = {ln.strip() for ln in f if ln.strip()}

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        with gzip.open(self.seen_path, "wt") as f:
            for h in sorted(self.seen):
                f.write(h + "\n")
