#!/usr/bin/env python3
"""RemontFlow print-agent.

Runs on the machine next to the printer (Epson EcoTank L3250, A4 inkjet via
OS driver). Polls the API for queued print jobs, downloads the rendered PDF
and sends it to the OS printer.

Usage:
    REMONTFLOW_API_URL=http://api:8000 \
    REMONTFLOW_EMAIL=operator@remontflow.local \
    REMONTFLOW_PASSWORD=operator123 \
    REMONTFLOW_PRINT_CMD='lp -d EPSON_L3250 {file}' \
    python agent.py

`REMONTFLOW_PRINT_CMD` must contain the literal `{file}` placeholder.
Examples:
  - Linux/CUPS:   lp -d EPSON_L3250 {file}
  - Windows:      powershell -Command "Start-Process -FilePath '{file}' -Verb Print"
  - macOS:        lp -d EPSON_L3250 {file}
"""
import base64
import os
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


def print_pdf(pdf_bytes: bytes) -> None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    cmd = PRINT_CMD.format(file=path)
    subprocess.run(cmd, shell=True, check=True, timeout=120)


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
                if not b64:
                    complete(token, job["id"], "failed", "no pdf in payload")
                    continue
                try:
                    print_pdf(base64.b64decode(b64))
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
