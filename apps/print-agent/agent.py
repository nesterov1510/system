#!/usr/bin/env python3
"""RemontFlow print-agent.

Печатает PDF-бланки из очереди на принтер. Поддерживает два режима
(настраиваются в админке, секция «Принтер»):

1. `mode=agent` — печать через драйвер ОС (рекомендуется для Epson EcoTank L3250).
   Агент запускается на машине, к которой подключён принтер, и вызывает команду ОС.

2. `mode=ipp` — прямая печать по IP через AirPrint/IPP (порт 631). Принтер должен
   поддерживать AirPrint (Epson L3250 — поддерживает). В админке указывается
   IP-адрес принтера; агент отправляет PDF напрямую на `http://IP:631/ipp/print`.

Конфигурация принтера (IP/порт/режим) приходит в каждом задании печати
(payload.printer), поэтому отдельно задавать её в окружении не нужно.
`REMONTFLOW_PRINT_CMD` нужен только для режима `agent`.

Usage:
    REMONTFLOW_API_URL=http://api:8000 \\
    REMONTFLOW_EMAIL=operator@remontflow.local \\
    REMONTFLOW_PASSWORD=operator123 \\
    REMONTFLOW_PRINT_CMD='lp -d EPSON_L3250 {file}' \\
    python agent.py
"""
import base64
import os
import struct
import subprocess
import sys
import tempfile
import time

import requests

API_URL = os.environ.get("REMONTFLOW_API_URL", "http://localhost:8000")
EMAIL = os.environ.get("REMONTFLOW_EMAIL", "operator@remontflow.local")
PASSWORD = os.environ.get("REMONTFLOW_PASSWORD", "operator123")
PRINT_CMD = os.environ.get("REMONTFLOW_PRINT_CMD", "lp {file}")
POLL_SECONDS = float(os.environ.get("REMONTFLOW_POLL_SECONDS", "3"))


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
        body["error"] = error
    requests.patch(
        f"{API_URL}/api/print/jobs/{job_id}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )


# --------------------------------------------------------------------------
# Режим agent: печать через драйвер ОС.
# --------------------------------------------------------------------------
def print_via_os(pdf_bytes: bytes) -> None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    cmd = PRINT_CMD.format(file=path)
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
    """Минимальный IPP Print-Job запрос с PDF-документом."""
    version = b"\x02\x00"  # IPP 2.0
    op = struct.pack(">H", 0x0002)  # Print-Job
    request_id = struct.pack(">I", 1)

    # operation-attributes-tag
    attrs = b"\x01"
    attrs += _ipp_attribute(0x47, "attributes-charset", b"utf-8")
    attrs += _ipp_attribute(0x48, "attributes-natural-language", b"ru")
    attrs += _ipp_attribute(0x45, "printer-uri", printer_uri.encode("utf-8"))
    attrs += _ipp_attribute(0x42, "requesting-user-name", b"remontflow")
    attrs += _ipp_attribute(0x49, "document-format", b"application/pdf")

    # end-of-attributes-tag, затем PDF.
    return version + op + request_id + attrs + b"\x03" + pdf_bytes


def print_via_ipp(pdf_bytes: bytes, printer: dict) -> None:
    ip = printer.get("ip")
    if not ip:
        raise RuntimeError("Не задан IP-адрес принтера (админка → Принтер)")
    port = int(printer.get("port", 631))
    printer_uri = f"ipp://{ip}:{port}/ipp/print"
    body = _build_ipp_print_job(printer_uri, pdf_bytes)

    r = requests.post(
        f"http://{ip}:{port}/ipp/print",
        data=body,
        headers={"Content-Type": "application/ipp"},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"IPP error: HTTP {r.status_code}")
    # В теле ответа IPP есть status-code; проверяем, что он успешный (0x0000).
    if len(r.content) >= 8:
        status_code = struct.unpack(">h", r.content[2:4])[0]
        if status_code != 0x0000:
            raise RuntimeError(f"IPP status code: 0x{status_code:04x}")


def print_pdf(pdf_bytes: bytes, printer: dict | None) -> None:
    mode = (printer or {}).get("mode", "agent")
    if mode == "ipp":
        print_via_ipp(pdf_bytes, printer or {})
    else:
        print_via_os(pdf_bytes)


def main() -> None:
    print(f"[print-agent] API={API_URL} poll={POLL_SECONDS}s")
    token = login()
    print("[print-agent] authenticated")
    while True:
        try:
            jobs = fetch_jobs(token)
            for job in jobs:
                payload = job.get("payload") or {}
                b64 = payload.get("pdf_base64")
                printer = payload.get("printer")
                if not b64:
                    complete(token, job["id"], "failed", "no pdf in payload")
                    continue
                try:
                    print_pdf(base64.b64decode(b64), printer)
                    complete(token, job["id"], "done")
                    print(f"[print-agent] printed job {job['id']}")
                except Exception as e:  # noqa: BLE001
                    complete(token, job["id"], "failed", str(e))
                    print(f"[print-agent] failed job {job['id']}: {e}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token = login()
                continue
            print(f"[print-agent] http error: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[print-agent] error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
