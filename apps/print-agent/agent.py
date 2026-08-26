#!/usr/bin/env python3
"""RemontFlow print-agent — печать бланков из очереди на принтер.

Режимы (настраиваются в админке «Принтер»):
  - mode=agent : печать через драйвер ОС (рекомендуется для Epson L3250).
  - mode=ipp   : прямая печать по AirPrint/IPP на http://IP:631/ipp/print.

ВАЖНО для Windows:
  - для тихой печати PDF нужен SumatraPDF (бесплатный, portable):
    https://www.sumatrapdfreader.org/download-free-pdf-viewer
    Скачайте `SumatraPDF.exe` и положите рядом с agent.py (или укажите путь
    в переменной REMONTFLOW_SUMATRA). Если Sumatra нет — агент сохранит PDF
    в папку `printed/` и откроет его для печати вручную.

Каждый бланк ВСЕГДА сохраняется в папку `printed/` (запасной вариант:
можно распечатать вручную, даже если автоматическая печать не сработала).

Запуск:
    REMONTFLOW_API_URL=http://localhost:8000 \\
    REMONTFLOW_EMAIL=operator@remontflow.local \\
    REMONTFLOW_PASSWORD=operator123 \\
    python agent.py
"""
import base64
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

import requests

API_URL = os.environ.get("REMONTFLOW_API_URL", "http://localhost:8000")
EMAIL = os.environ.get("REMONTFLOW_EMAIL", "operator@remontflow.local")
PASSWORD = os.environ.get("REMONTFLOW_PASSWORD", "operator123")
PRINT_CMD = os.environ.get("REMONTFLOW_PRINT_CMD", "")  # переопределение для agent-режима
POLL_SECONDS = float(os.environ.get("REMONTFLOW_POLL_SECONDS", "3"))
SUMATRA = os.environ.get("REMONTFLOW_SUMATRA", "")
SAVE_DIR = os.environ.get("REMONTFLOW_SAVE_DIR", "./printed")

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def log(msg: str) -> None:
    print(f"[print-agent] {msg}", flush=True)


def login() -> str:
    r = requests.post(
        f"{API_URL}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_jobs(token: str) -> list[dict]:
    r = requests.get(
        f"{API_URL}/api/print/jobs",
        params={"status": "queued"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def complete(token: str, job_id: str, status: str, error: str | None = None) -> None:
    body = {"status": status}
    if error:
        body["error"] = error[:500]
    try:
        requests.patch(
            f"{API_URL}/api/print/jobs/{job_id}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        log(f"не удалось обновить статус задания {job_id}: {e}")


# --------------------------------------------------------------------------
# Сохранение PDF (всегда, как запасной вариант).
# --------------------------------------------------------------------------
def save_pdf(pdf_bytes: bytes, number: str) -> str:
    os.makedirs(SAVE_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in number)
    path = os.path.join(SAVE_DIR, f"{safe}.pdf")
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return path


# --------------------------------------------------------------------------
# Поиск SumatraPDF на Windows.
# --------------------------------------------------------------------------
def _find_sumatra() -> str | None:
    candidates = []
    if SUMATRA:
        candidates.append(SUMATRA)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "SumatraPDF.exe"))
    candidates.append(shutil.which("SumatraPDF.exe") or "")
    candidates.append(r"C:\Program Files\SumatraPDF\SumatraPDF.exe")
    candidates.append(r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe")
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _write_temp_pdf(pdf_bytes: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(pdf_bytes)
    return path


# --------------------------------------------------------------------------
# Режим agent: печать через драйвер ОС.
# --------------------------------------------------------------------------
def print_via_os(pdf_bytes: bytes, printer: dict | None) -> None:
    printer_name = (printer or {}).get("name", "Epson L3250")
    tmp = _write_temp_pdf(pdf_bytes)

    if PRINT_CMD:
        # Явная команда из окружения (переопределяет всё).
        cmd = PRINT_CMD.format(file=tmp, printer=printer_name)
        log(f"печать: {cmd}")
        subprocess.run(cmd, shell=True, check=True, timeout=120)
        return

    if IS_WINDOWS:
        # 1) SumatraPDF — тихая печать.
        sumatra = _find_sumatra()
        if sumatra:
            cmd = [sumatra, "-print-to", printer_name, "-silent", tmp]
            log(f"печать (SumatraPDF): {cmd}")
            subprocess.run(cmd, check=True, timeout=120)
            return
        # 2) Без Sumatra — открываем для ручной печати и сообщаем.
        log("SumatraPDF не найден — открываю PDF для печати вручную")
        os.startfile(tmp, "print")  # type: ignore[attr-defined]
        return

    # macOS / Linux: CUPS `lp`.
    cmd = f'lp -d "{printer_name}" "{tmp}"'
    log(f"печать: {cmd}")
    subprocess.run(cmd, shell=True, check=True, timeout=120)


# --------------------------------------------------------------------------
# Режим ipp: прямая печать PDF через AirPrint/IPP (порт 631).
# --------------------------------------------------------------------------
def _ipp_attribute(tag: int, name: str, value: bytes) -> bytes:
    return (
        bytes([tag])
        + struct.pack(">H", len(name.encode("utf-8")))
        + name.encode("utf-8")
        + struct.pack(">H", len(value))
        + value
    )


def _build_ipp_print_job(printer_uri: str, pdf_bytes: bytes) -> bytes:
    version = b"\x02\x00"  # IPP 2.0
    op = struct.pack(">H", 0x0002)  # Print-Job
    request_id = struct.pack(">I", 1)

    attrs = b"\x01"
    attrs += _ipp_attribute(0x47, "attributes-charset", b"utf-8")
    attrs += _ipp_attribute(0x48, "attributes-natural-language", b"ru")
    attrs += _ipp_attribute(0x45, "printer-uri", printer_uri.encode("utf-8"))
    attrs += _ipp_attribute(0x42, "requesting-user-name", b"remontflow")
    attrs += _ipp_attribute(0x49, "document-format", b"application/pdf")

    return version + op + request_id + attrs + b"\x03" + pdf_bytes


def print_via_ipp(pdf_bytes: bytes, printer: dict) -> None:
    ip = printer.get("ip")
    if not ip:
        raise RuntimeError("Не задан IP-адрес принтера (админка → Принтер)")
    port = int(printer.get("port", 631))
    printer_uri = f"ipp://{ip}:{port}/ipp/print"
    body = _build_ipp_print_job(printer_uri, pdf_bytes)

    log(f"печать по IPP: http://{ip}:{port}/ipp/print")
    r = requests.post(
        f"http://{ip}:{port}/ipp/print",
        data=body,
        headers={"Content-Type": "application/ipp"},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"IPP error: HTTP {r.status_code}")
    if len(r.content) >= 8:
        status_code = struct.unpack(">h", r.content[2:4])[0]
        if status_code != 0x0000:
            raise RuntimeError(f"IPP status code: 0x{status_code:04x}")


def print_pdf(pdf_bytes: bytes, printer: dict | None) -> str:
    mode = (printer or {}).get("mode", "agent")
    if mode == "ipp":
        print_via_ipp(pdf_bytes, printer or {})
    else:
        print_via_os(pdf_bytes, printer or {})
    return mode


def main() -> None:
    log(f"API={API_URL} · poll={POLL_SECONDS}s · OS={sys.platform} · save_dir={SAVE_DIR}")
    if IS_WINDOWS and not PRINT_CMD:
        s = _find_sumatra()
        log("Windows: SumatraPDF " + ("найден" if s else "НЕ найден (PDF будет открыт вручную)"))
    token = login()
    log("авторизация OK")
    while True:
        try:
            jobs = fetch_jobs(token)
            if jobs:
                log(f"в очереди: {len(jobs)}")
            for job in jobs:
                payload = job.get("payload") or {}
                b64 = payload.get("pdf_base64")
                printer = payload.get("printer")
                if not b64:
                    complete(token, job["id"], "failed", "no pdf in payload")
                    continue
                try:
                    pdf = base64.b64decode(b64)
                    # Всегда сохраняем PDF (запасной вариант).
                    saved = save_pdf(pdf, f"job-{str(job['id'])[:8]}")
                    mode = print_pdf(pdf, printer)
                    complete(token, job["id"], "done")
                    log(f"задание {str(job['id'])[:8]} напечатано (режим {mode}) → {saved}")
                except Exception as e:  # noqa: BLE001
                    complete(token, job["id"], "failed", str(e))
                    log(f"ОШИБКА задания {str(job['id'])[:8]}: {e}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token = login()
                log("токен обновлён")
                continue
            log(f"http error: {e}")
        except Exception as e:  # noqa: BLE001
            log(f"error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("остановлен")
        sys.exit(0)
