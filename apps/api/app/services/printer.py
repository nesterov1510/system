"""Printer discovery and direct printing — integrated into the backend.

No separate print-agent needed. The backend:
1. Scans for printers via CUPS, mDNS (avahi), and network scan.
2. Shows discovered printers in admin UI for one-click selection.
3. Processes print jobs in a background worker started on app boot.
"""
import asyncio
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import logging
import socket
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("msb.printer")

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# Printer discovery
# ---------------------------------------------------------------------------

def discover_printers() -> list[dict]:
    """Scan for available printers using multiple methods.

    Returns list of dicts:
      [{"name": "...", "source": "cups"|"avahi"|"network",
        "ip": "...", "port": 631, "uri": "...", "status": "...", "label": "..."}]
    """
    printers: list[dict] = []

    # 1) CUPS printers (installed locally via driver)
    printers.extend(_cups_discover())

    # 2) avahi / mDNS (AirPrint printers on the network)
    printers.extend(_avahi_discover())

    # 3) Quick network scan — only top candidates
    existing_ips = {p.get("ip") for p in printers if p.get("ip")}
    printers.extend(_quick_network_discover(existing_ips))

    return printers


def _cups_discover() -> list[dict]:
    """List printers installed in CUPS (via lpstat and lpinfo)."""
    printers = []

    # Method 1: lpstat -p (currently installed queues)
    try:
        out = subprocess.run(
            ["lpstat", "-p"], capture_output=True, text=True, timeout=5
        ).stdout
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
    except Exception:
        pass

    # Method 2: lpinfo -v (find available backends/device URIs)
    try:
        out = subprocess.run(
            ["lpinfo", "-v"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            # Lines like: "direct usb://EPSON/..."
            # or "network ipp://..."
            if "://" in line:
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    uri = parts[1].strip()
                    # Extract name from URI
                    name = _name_from_uri(uri)
                    if name and not any(p["name"] == name for p in printers):
                        source = "cups" if "usb" in uri else "network"
                        ip = _ip_from_uri(uri)
                        printers.append({
                            "name": name,
                            "source": source,
                            "ip": ip,
                            "port": 631,
                            "uri": uri,
                            "status": "idle",
                            "label": f"{name} ({uri[:60]})",
                        })
    except Exception:
        pass

    # Enrich CUPS printers with URI if missing
    try:
        out = subprocess.run(
            ["lpstat", "-v"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            if "device for" in line.lower():
                colon_parts = line.split(":", 1)
                if len(colon_parts) == 2:
                    dev_name = colon_parts[0].replace("device for", "").strip()
                    uri = colon_parts[1].strip()
                    for p in printers:
                        if p["name"] == dev_name and not p["uri"]:
                            p["uri"] = uri
                            ip = _ip_from_uri(uri)
                            if ip:
                                p["ip"] = ip
    except Exception:
        pass

    return printers


def _avahi_discover() -> list[dict]:
    """Discover AirPrint printers via avahi-browse (mDNS)."""
    printers = []
    if not shutil.which("avahi-browse"):
        return printers
    try:
        out = subprocess.run(
            ["avahi-browse", "-t", "-r", "-p", "_ipp._tcp"],
            capture_output=True, text=True, timeout=8
        ).stdout
        # Parse avahi output — each printer block has address, port, name
        current = {}
        for line in out.splitlines():
            if line.startswith("="):
                if current.get("name"):
                    printers.append(current)
                current = {}
            elif "=;IPv4;" in line or "=;IPv6;" in line:
                parts = line.split(";")
                if len(parts) >= 8:
                    current = {
                        "name": parts[3] if len(parts) > 3 else "",
                        "source": "avahi",
                        "ip": parts[7] if len(parts) > 7 else "",
                        "port": int(parts[8]) if len(parts) > 8 and parts[8].isdigit() else 631,
                        "uri": f"ipp://{parts[7]}:{parts[8] if len(parts) > 8 else 631}/ipp/print",
                        "status": "idle",
                        "label": f"{parts[3] if len(parts) > 3 else ''} (AirPrint — обнаружен в сети)",
                    }
            elif "addr=" in line.lower():
                # Alternative format
                for part in line.split(";"):
                    part = part.strip()
                    if part.startswith("address="):
                        addr = part.split("=", 1)[1].strip()
                        if not current.get("ip"):
                            current["ip"] = addr
                            current.setdefault("port", 631)
        if current.get("name"):
            printers.append(current)
    except Exception as e:
        log.debug(f"avahi-browse failed: {e}")
    return printers


def _quick_network_discover(existing_ips: set[str]) -> list[dict]:
    """Fast parallel scan of local subnet for IPP printers.

    Only checks IPs not already found. Uses short timeouts.
    """
    printers = []
    local_ip = _get_local_ip()
    if not local_ip:
        return printers

    subnet = ".".join(local_ip.split(".")[:3])

    # Generate candidate IPs — skip .0, .255, and already-found IPs
    candidates = []
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        if ip == local_ip or ip in existing_ips:
            continue
        candidates.append(ip)

    def _probe(ip: str) -> dict | None:
        """Try to connect to common printer ports."""
        for port in [631, 9100]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.3)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    # Port open — try IPP probe on 631
                    if port == 631:
                        info = _probe_ipp_printer(ip)
                        if info:
                            return info
                    # Port 9100 open — likely a printer (raw jetdirect)
                    return {
                        "name": f"Printer @ {ip}",
                        "source": "network",
                        "ip": ip,
                        "port": 9100,
                        "uri": f"socket://{ip}:9100",
                        "status": "idle",
                        "label": f"Сетевой принтер ({ip}:9100 — raw/JetDirect)",
                    }
            except Exception:
                pass
        return None

    # Scan in parallel with thread pool
    with ThreadPoolExecutor(max_workers=30) as pool:
        futures = {pool.submit(_probe, ip): ip for ip in candidates}
        for future in futures:
            try:
                result = future.result(timeout=2)
                if result:
                    printers.append(result)
            except Exception:
                pass

    return printers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def _name_from_uri(uri: str) -> str:
    """Extract a human-readable name from a device URI."""
    # usb://EPSON/SL-D500/...
    # ipp://192.168.1.50/ipp/print
    if "://" in uri:
        path = uri.split("://", 1)[1]
        parts = path.split("/")
        # First meaningful segment
        for p in parts:
            if p and p not in ["ipp", "print", ""]:
                return p
    return uri[:30]


def _ip_from_uri(uri: str) -> str:
    """Extract IP from an IPP/HTTP URI."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(uri)
        return parsed.hostname or ""
    except Exception:
        return ""


def _probe_ipp_printer(ip: str, port: int = 631) -> dict | None:
    """Try to query an IPP printer for its make/model."""
    try:
        uri = f"ipp://{ip}:{port}/ipp/print"
        body = _build_ipp_get_attributes(uri)
        # Use a short timeout
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect((ip, port))
        sock.sendall(body)
        # Read response
        data = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 8192:
                    break
            except socket.timeout:
                break
        sock.close()

        if len(data) >= 8:
            model = _parse_ipp_printer_name(data)
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


def _ipp_attribute(tag: int, name: str, value: bytes) -> bytes:
    return (
        bytes([tag])
        + struct.pack(">H", len(name.encode("utf-8")))
        + name.encode("utf-8")
        + struct.pack(">H", len(value))
        + value
    )


def _parse_ipp_printer_name(data: bytes) -> str | None:
    """Try to extract printer make/model from IPP response."""
    try:
        text = data.decode("utf-8", errors="ignore")
        for brand in ["Epson", "HP", "Canon", "Brother", "Samsung", "Xerox",
                       "Lexmark", "Kyocera", "Ricoh", "OKI", "Pantum",
                       "Epson", "SNP", "L3250", "L3210", "L3252"]:
            idx = text.lower().find(brand.lower())
            if idx >= 0:
                snippet = text[idx:idx + 50].strip()
                snippet = "".join(c for c in snippet if c.isprintable())
                return snippet[:40]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# IPP print job builder (for network printers)
# ---------------------------------------------------------------------------

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

    printer_config: {"mode": "cups"|"ipp", "name": "...", "ip": "...", "port": 631}
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

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((ip, port))
    sock.sendall(body)

    data = b""
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 8:
                break
        except socket.timeout:
            break
    sock.close()

    if len(data) >= 8:
        status = struct.unpack(">h", data[2:4])[0]
        if status != 0x0000:
            raise RuntimeError(f"IPP status: 0x{status:04x}")


def _cups_printer_names() -> list[str]:
    try:
        out = subprocess.run(
            ["lpstat", "-p"], capture_output=True, text=True, timeout=5
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
            ["lpstat", "-d"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return None
    if ":" in out:
        return out.rsplit(":", 1)[-1].strip()
    return None
