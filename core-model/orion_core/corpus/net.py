"""Kibar HTTP: alan adı başına ≥1 sn aralık, robots.txt'e uyma, 429/503'te geri çekilme. Testte sahte taşıyıcı verilir."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class RobotsDisallowed(RuntimeError):
    pass


@dataclass
class Resp:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def urllib_transport(url: str, method: str = "GET", headers: dict | None = None, timeout: int = 60) -> Resp:
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read() if method != "HEAD" else b"")
    except urllib.error.HTTPError as e:
        return Resp(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() if method != "HEAD" else b"")


class Polite:
    def __init__(self, user_agent: str, min_interval: float = 1.0, transport=None, sleep=time.sleep,
                 clock=time.monotonic, retries: int = 3):
        if min_interval < 1.0:
            raise ValueError("istek aralığı en az 1 sn olmalı")
        self.ua, self.min_interval, self.retries = user_agent, min_interval, retries
        self.transport = transport or urllib_transport
        self.sleep, self.clock = sleep, clock
        self.last: dict[str, float] = {}
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.log: list[tuple[str, str, int]] = []  # (yöntem, adres, durum) — testler ve rapor için

    def _wait(self, host: str) -> None:
        t = self.last.get(host)
        if t is not None:
            d = self.min_interval - (self.clock() - t)
            if d > 0:
                self.sleep(d)
        self.last[host] = self.clock()

    def _raw(self, url: str, method: str = "GET", headers: dict | None = None) -> Resp:
        host = urlsplit(url).netloc
        h = {"User-Agent": self.ua, **(headers or {})}
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                r = self.transport(url, method, h)
            except Exception as e:  # ağ hatası: kısa geri çekil, sonra yeniden dene
                self.log.append((method, url, -1))
                if attempt == self.retries:
                    raise
                self.sleep(5 * (attempt + 1))
                continue
            self.log.append((method, url, r.status))
            if r.status in (429, 503) and attempt < self.retries:
                ra = r.headers.get("retry-after", "")
                self.sleep(min(float(ra), 300) if ra.isdigit() else 30 * (attempt + 1))
                continue
            return r
        return r

    def robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlsplit(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._raw(key + "/robots.txt")
            except Exception:
                r = Resp(599)
            if r.status in (401, 403) or r.status >= 500:
                rp.disallow_all = True      # erişilemeyen robots: tutucu davran (hiçbir şey çekme)
            elif r.status >= 400:
                rp.allow_all = True         # robots.txt yok: izinli
            else:
                rp.parse(r.text().splitlines())
            self.robots[key] = rp
        return self.robots[key]

    def allowed(self, url: str) -> bool:
        rp = self.robots_for(url)
        return rp.can_fetch(self.ua.split("/")[0], url) and rp.can_fetch(self.ua, url)

    def get(self, url: str, headers: dict | None = None, method: str = "GET") -> Resp:
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt izin vermiyor: {url}")
        return self._raw(url, method, headers)

    def head(self, url: str) -> Resp:
        return self.get(url, method="HEAD")

    def download(self, url: str, dest, chunk: int = 1 << 20) -> int:
        """Büyük dosya (döküm/arşiv) akışla indirilir; robots + aralık yine geçerli. Döner: bayt."""
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt izin vermiyor: {url}")
        self._wait(urlsplit(url).netloc)
        req = urllib.request.Request(url, headers={"User-Agent": self.ua})
        n = 0
        tmp = str(dest) + ".part"
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(chunk)
                if not b:
                    break
                f.write(b)
                n += len(b)
        import os
        os.replace(tmp, dest)
        self.log.append(("GET", url, 200))
        return n
