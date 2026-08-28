"""Printer discovery and direct printing — integrated into the backend.

No separate print-agent needed. The backend:
1. Scans for printers via CUPS (`lpstat -p`) and network (IPP broadcast).
2. Shows discovered printers in admin UI for one-click selection.
3. Processes print jobs in a background worker started on app boot.
"""
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import logging

import requests as http_requests

log = logging.getLogger("msb.printer")

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# Printer discovery
# ---------------------------------------------------------------------------

def discover_printers() -> list[dict]:
    """Scan for available printers: CUPS local + network scan.

    Returns list of dicts:
      [{"name": "...", "source": "cups"|"network", "ip": "...", "port": 631, "uri": "..."}]
    """
    printers: list[dict] = []

    # 1) CUPS printers (installed on this machine via driver)
    for p in _cups_discover():
        printers.append(p)

    # 2) Network scan — try common printer IPs on the local subnet
    for p in _network_discover():
        # Avoid duplicates by name
        if not any(ep["name"] == p["name"] for ep in printers):
            printers.append(p)

    return printers


def _cups_discover() -> list[dict]:
    """List printers installed in CUPS."""
    printers = []
    try:
        out = subprocess.run(
            ["lpstat", "-p"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return printers

    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "printer":
            name = parts[1]
            status = "idle" if "idle" in line.lower() else "active"
            printers.append({
                "name": name,
                "source": "cups",
                "ip": "",
                "port": 631,
                "uri": "",
                "status": status,
                "label": f"{name} (CUPS — локальный драйвер)",
            })

    # Also try to get the URI for each CUPS printer
    try:
        out = subprocess.run(
            ["lpstat", "-v"], capture_output=True, text=True, timeout=10
        ).stdout
        for line in out.splitlines():
            # "device for PRINTER_NAME: ipp://..."
            if "device for" in line.lower():
                parts = line.split(":", 1)
                if len(parts) == 2:
                    name_part = parts[0].replace("device for", "").strip()
                    uri = parts[1].strip()
                    for p in printers:
                        if p["name"] == name_part:
                            p["uri"] = uri
                            # Extract IP from IPP URI
                            if "ipp://" in uri or "http://" in uri:
                                try:
                                    from urllib.parse import urlparse
                                    parsed = urlparse(uri)
                                    if parsed.hostname:
                                        p["ip"] = parsed.hostname
                                except Exception:
                                    pass
    except Exception:
        pass

    return printers


def _network_discover() -> list[dict]:
    """Scan local subnet for IPP-capable printers."""
    printers = []

    # Get local IP to determine subnet
    local_ip = _get_local_ip()
    if not local_ip:
        return printers

    subnet = ".".join(local_ip.split(".")[:3])

    # Scan common printer ports on the subnet
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        if ip == local_ip:
            continue
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.15)
            result = sock.connect_ex((ip, 631))
            sock.close()
            if result == 0:
                # Port 631 open — likely a printer, try to get info
                info = _probe_ipp_printer(ip)
                if info:
                    printers.append(info)
        except Exception:
            pass

    return printers


def _get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


import socket


def _probe_ipp_printer(ip: str, port: int = 631) -> dict | None:
    """Try to query an IPP printer for its make/model."""
    try:
        # Send a Get-Printer-Attributes request
        uri = f"ipp://{ip}:{port}/ipp/print"
        body = _build_ipp_get_attributes(uri)
        r = http_requests.post(
            f"http://{ip}:{port}/ipp/print",
            data=body,
            headers={"Content-Type": "application/ipp"},
            timeout=1.5,
        )
        if r.status_code == 200 and len(r.content) >= 8:
            # Parse printer info from response
            model = _parse_ipp_printer_name(r.content)
            return {
                "name": model or f"Printer @ {ip}",
                "source": "network",
                "ip": ip,
                "port": port,
                "uri": uri,
                "status": "idle",
                "label": f"{model or 'Сетевой принтер'} ({ip})",
            }
    except Exception:
        pass
    return None


def _build_ipp_get_attributes(printer_uri: str) -> bytes:
    """Build an IPP Get-Printer-Attributes request."""
    version = b"\x02\x00"
    op = struct.pack(">H", 0x0009)  # Get-Printer-Attributes
    request_id = struct.pack(">I", 1)
    attrs = b"\x01"
    attrs += _ipp_attribute(0x47, "attributes-charset", b"utf-8")
    attrs += _ipp_attribute(0x48, "attributes-natural-language", b"ru")
    attrs += _ipp_attribute(0x45, "printer-uri", printer_uri.encode("utf-8"))
    attrs += _ipp_attribute(0x44, "requested-attributes",
                           b"printer-make-and-model printer-state")
    return version + op + request_id + attrs + b"\x03"


def _parse_ipp_printer_name(data: bytes) -> str | None:
    """Try to extract printer make/model from IPP response."""
    try:
        text = data.decode("utf-8", errors="ignore")
        # Look for common printer names
        for brand in ["Epson", "HP", "Canon", "Brother", "Samsung", "Xerox",
                       "Lexmark", "Kyocera", "Ricoh", "OKI", "Pantum"]:
            idx = text.lower().find(brand.lower())
            if idx >= 0:
                # Extract a reasonable substring
                snippet = text[idx:idx+50].strip()
                # Clean up control characters
                snippet = "".join(c for c in snippet if c.isprintable())
                return snippet[:40]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# IPP print job builder (for network printers)
# ---------------------------------------------------------------------------

def _ipp_attribute(tag: int, name: str, value: bytes) -> bytes:
    return (
        bytes([tag])
        + struct.pack(">H", len(name.encode("utf-8")))
        + name.encode("utf-8")
        + struct.pack(">H", len(value))
        + value
    )


def _build_ipp_print_job(printer_uri: str, pdf_bytes: bytes) -> bytes:
    version = b"\x02\x00"
    op = struct.pack(">H", 0x0002)  # Print-Job
    request_id = struct.pack(">I", 1)
    attrs = b"\x01"
    attrs += _ipp_attribute(0x47, "attributes-charset", b"utf-8")
    attrs += _ipp_attribute(0x48, "attributes-natural-language", b"ru")
    attrs += _ipp_attribute(0x45, "printer-uri", printer_uri.encode("utf-8"))
    attrs += _ipp_attribute(0x42, "requesting-user-name", b"msb")
    attrs += _ipp_attribute(0x49, "document-format", b"application/pdf")
    return version + op + request_id + attrs + b"\x03" + pdf_bytes


# ---------------------------------------------------------------------------
# Direct printing
# ---------------------------------------------------------------------------

def print_pdf(pdf_bytes: bytes, printer_config: dict) -> str:
    """Print PDF using the configured printer.

    printer_config: {"mode": "cups"|"ipp", "name": "...", "ip": "...", "port": 631, ...}
    Returns the mode used.
    """
    mode = printer_config.get("mode", "cups")

    if mode == "ipp":
        _print_via_ipp(pdf_bytes, printer_config)
        return "ipp"
    else:
        _print_via_cups(pdf_bytes, printer_config)
        return "cups"


def _print_via_cups(pdf_bytes: bytes, printer_config: dict) -> None:
    """Print via CUPS `lp` command."""
    printer_name = printer_config.get("name", "")

    # If no name specified, use CUPS default
    if not printer_name:
        printer_name = _cups_default() or ""

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(pdf_bytes)

        cmd = ["lp"]
        if printer_name:
            cmd += ["-d", printer_name]
        cmd.append(tmp_path)

        log.info(f"CUPS печать: {' '.join(cmd)}")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            available = _cups_printer_names()
            hint = ", ".join(available) if available else "нет принтеров"
            raise RuntimeError(
                f"CUPS ошибка: {(r.stderr or '').strip()}. "
                f"Доступные: {hint}. Выберите принтер в Админ → Принтер."
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _print_via_ipp(pdf_bytes: bytes, printer_config: dict) -> None:
    """Print via IPP protocol (AirPrint)."""
    ip = printer_config.get("ip", "")
    port = int(printer_config.get("port", 631))
    if not ip:
        raise RuntimeError("Не задан IP принтера")
    uri = f"ipp://{ip}:{port}/ipp/print"
    body = _build_ipp_print_job(uri, pdf_bytes)
    log.info(f"IPP печать: {uri}")
    r = http_requests.post(
        f"http://{ip}:{port}/ipp/print",
        data=body,
        headers={"Content-Type": "application/ipp"},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"IPP HTTP {r.status_code}")
    if len(r.content) >= 8:
        status = struct.unpack(">h", r.content[2:4])[0]
        if status != 0x0000:
            raise RuntimeError(f"IPP status: 0x{status:04x}")


def _cups_printer_names() -> list[str]:
    try:
        out = subprocess.run(
            ["lpstat", "-p"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return []
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "printer":
            names.append(parts[1])
    return names


def _cups_default() -> str | None:
    try:
        out = subprocess.run(
            ["lpstat", "-d"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return None
    if ":" in out:
        return out.rsplit(":", 1)[-1].strip()
    return None
