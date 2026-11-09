"""Kod çalıştırma kum havuzu (yalnız EĞİTİM makinesinde: Kaggle/GitHub; telefonda kod çalıştırılmaz).

Orion'un yazdığı Python kodu ayrı bir süreçte, geçici boş klasörde, yalıtılmış (-I) yorumlayıcıyla, işlemci süresi,
bellek ve dosya boyutu sınırıyla çalıştırılır; ortamda anahtar/gizli bilgi yoktur. Ağ erişimi süreç düzeyinde
kapatılmaz (doğrulanmadı) — çalışan kod Orion'un kendi çıktısıdır ve eğitim makinesinde gizli bilgi bulunmaz."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile


def _limits(cpu_s: int, mem_mb: int):
    def f():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))
            resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except Exception:
            pass
    return f


def run_python(code: str, stdin: str = "", timeout: float = 6.0, mem_mb: int = 512) -> tuple[bool, str, str]:
    """(süre içinde ve 0 koduyla bitti mi, stdout, stderr). Çıktılar 20 KB ile sınırlı."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cozum.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(code)
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "HOME": d, "LANG": "C.UTF-8"}
        try:
            r = subprocess.run([sys.executable, "-I", "-S", p], input=stdin, capture_output=True, text=True,
                               timeout=timeout, cwd=d, env=env, preexec_fn=_limits(int(timeout) + 1, mem_mb))
        except subprocess.TimeoutExpired:
            return False, "", "zaman aşımı"
        return r.returncode == 0, r.stdout[:20000], r.stderr[-2000:]


def passes_asserts(code: str, tests: str, setup: str = "") -> bool:
    """Kod + (kurulum) + assert testleri hatasız biterse geçti."""
    ok, _, _ = run_python(f"{setup}\n{code}\n\n{tests}\n")
    return ok


def passes_io(code: str, cases: list[tuple[str, str]]) -> bool:
    """Standart giriş/çıkış testleri: her girdi için çıktı (boşluklar sadeleşmiş) beklenene eşit olmalı."""
    norm = lambda s: "\n".join(x.rstrip() for x in s.strip().splitlines())
    for inp, want in cases:
        ok, out, _ = run_python(code, inp)
        if not ok or norm(out) != norm(want):
            return False
    return True


def extract_code(reply: str, prompt_code: str = "") -> str:
    """Cevaptaki ilk ```python bloğu (yoksa tüm cevap). Fonksiyon gövdesiyle başlıyorsa istem kodu başa eklenir."""
    import re
    m = re.search(r"```(?:python|py)?\n(.*?)(?:```|$)", reply, re.S)
    code = (m.group(1) if m else reply).rstrip()
    if prompt_code and "def " not in code.split("\n", 1)[0]:
        code = prompt_code + code
    return code
