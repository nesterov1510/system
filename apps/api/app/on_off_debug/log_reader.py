# ruff: noqa: BLE001, S112  -- порт из архива: широкий except и локальное время — намеренно
# on_off_debug/log_reader.py
"""
Live-reader логов для HTML-страницы мониторинга (/admin/logs).

Назначение:
- читать все уровни логов on_off_debug/log_folder;
- ВСЕГДА показывать INFO / SUCCESS / SUCCESS1 / WARNING / ERROR / ERROR1 /
  CRITICAL, даже если папка уровня ещё не создана;
- автоматически выбирать свежий лог;
- отдавать данные для HTML-шаблона;
- не писать секреты и не ломать основное приложение.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from app.on_off_debug.debug_mode import debug_error1_print
from app.on_off_debug.env_tools import read_env_file, resolve_log_dir
from app.on_off_debug.time_utils import from_ts, local_now

LEVEL_LABELS = {
    "critical_error_print": "CRITICAL",
    "error_print": "ERROR",
    "error1_print": "ERROR1",
    "warning_print": "WARNING",
    "info_print": "INFO",
    "success_print": "SUCCESS",
    "success1_print": "SUCCESS1",
}

LEVEL_TITLES = {
    "critical_error_print": "Критические ошибки",
    "error_print": "Ошибки операций",
    "error1_print": "Внутренние ошибки",
    "warning_print": "Предупреждения",
    "info_print": "Информация",
    "success_print": "Успешные действия",
    "success1_print": "Успешные внутренние этапы",
}

LEVEL_DESCRIPTIONS = {
    "critical_error_print": "Опасные события: безопасность, потеря данных, падение важного сервиса.",
    "error_print": "Операция сломалась, но приложение продолжает работать.",
    "error1_print": "Внутренние ошибки обработчиков, парсеров и подэтапов.",
    "warning_print": "Странно или подозрительно, но сервис живой.",
    "info_print": "Обычные события приложения.",
    "success_print": "Главные успешные действия.",
    "success1_print": "Успешные внутренние этапы.",
}

LEVEL_ORDER = [
    "critical_error_print",
    "error_print",
    "error1_print",
    "warning_print",
    "info_print",
    "success_print",
    "success1_print",
]

LEVEL_SEVERITY = {
    "critical_error_print": "critical",
    "error_print": "error",
    "error1_print": "error1",
    "warning_print": "warning",
    "info_print": "info",
    "success_print": "success",
    "success1_print": "success1",
}

ERROR_LEVELS = {"critical_error_print", "error_print", "error1_print"}
DEFAULT_LIMIT = 300
MAX_LIMIT = 5000


def get_base_log_dir() -> str:
    """Возвращает базовую папку логов из debug_module.env."""
    env_data = read_env_file()
    return resolve_log_dir(env_data)


def _safe_name(value: str) -> str:
    """Защита от path traversal через query-параметры."""
    value = str(value or "").strip()
    value = value.replace("\\", "").replace("/", "")
    value = value.replace("..", "")
    return value


def _safe_limit(value, default: int = DEFAULT_LIMIT) -> int:
    try:
        limit = int(value)
    except Exception:
        limit = default
    return max(20, min(limit, MAX_LIMIT))


def _list_dirs(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted([p.name for p in path.iterdir() if p.is_dir()], reverse=True)


def _list_files(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted([p.name for p in path.iterdir() if p.is_file()])


def _sort_levels(levels: Sequence[str]) -> list[str]:
    order_map = {name: idx for idx, name in enumerate(LEVEL_ORDER)}
    return sorted(
        {str(item).strip() for item in levels if str(item).strip()},
        key=lambda item: (order_map.get(item, 999), item),
    )


def _get_all_display_levels(base_log_dir: Path) -> list[str]:
    """
    Возвращает полный список уровней для интерфейса.

    ERROR / ERROR1 / CRITICAL не должны исчезать только потому, что сегодня
    ещё нет файлов. Мониторинг должен показывать все каналы.
    """
    existing = _list_dirs(base_log_dir)
    existing = [level for level in existing if level in LEVEL_LABELS or level.endswith("_print")]
    return _sort_levels(list(LEVEL_ORDER) + existing)


def _format_bytes(size: int) -> str:
    size = int(size or 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{round(size / 1024, 2)} KB"
    if size < 1024 * 1024 * 1024:
        return f"{round(size / 1024 / 1024, 2)} MB"
    return f"{round(size / 1024 / 1024 / 1024, 2)} GB"


def _mtime_iso(file_path: Path) -> str:
    try:
        return from_ts(file_path.stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return ""


def _read_tail(file_path: Path, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Читает последние строки лог-файла."""
    if not file_path.exists() or not file_path.is_file():
        return []

    limit = _safe_limit(limit)

    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as file:
            lines = file.readlines()
        return [line.rstrip("\n") for line in lines[-limit:]]

    except Exception as e:
        debug_error1_print(
            f"Ошибка чтения лог-файла {file_path}: {e}",
            source="on_off_debug.log_reader._read_tail",
        )
        return []


def _count_file_lines(file_path: Path) -> int:
    if not file_path.exists() or not file_path.is_file():
        return 0

    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as file:
            return sum(1 for _ in file)
    except Exception:
        return 0


def _find_newest_log_file(base_log_dir: Path, only_level: str = "") -> tuple[str, str, str]:
    """
    Возвращает (level, date, filename) самого свежего лог-файла.

    Если only_level указан, ищет только внутри этого уровня.
    Если логов нет — возвращает пустые строки.
    """
    newest: tuple[float, str, str, str] | None = None

    if not base_log_dir.exists():
        return "", "", ""

    for level_dir in base_log_dir.iterdir():
        if not level_dir.is_dir():
            continue

        level = level_dir.name
        if only_level and level != only_level:
            continue
        if level not in LEVEL_LABELS and not level.endswith("_print"):
            continue

        for date_dir in level_dir.iterdir():
            if not date_dir.is_dir():
                continue

            for file_path in date_dir.iterdir():
                if not file_path.is_file():
                    continue

                try:
                    mtime = file_path.stat().st_mtime
                except Exception:
                    continue

                if newest is None or mtime > newest[0]:
                    newest = (mtime, level, date_dir.name, file_path.name)

    if newest is None:
        return "", "", ""

    return newest[1], newest[2], newest[3]


def _get_stats(base_log_dir: Path, levels: Sequence[str]) -> list[dict]:
    stats: list[dict] = []

    for level in levels:
        level_path = base_log_dir / level
        total_files = 0
        total_size = 0
        total_lines = 0
        newest_mtime = 0.0
        newest_file = ""

        if level_path.exists():
            for root, _, filenames in os.walk(level_path):
                for fname in filenames:
                    fpath = Path(root) / fname
                    if not fpath.is_file():
                        continue

                    try:
                        stat = fpath.stat()
                    except Exception:
                        continue

                    total_files += 1
                    total_size += stat.st_size
                    total_lines += _count_file_lines(fpath)

                    if stat.st_mtime > newest_mtime:
                        newest_mtime = stat.st_mtime
                        newest_file = str(fpath)

        stats.append({
            "name": level,
            "label": LEVEL_LABELS.get(level, level),
            "title": LEVEL_TITLES.get(level, level),
            "description": LEVEL_DESCRIPTIONS.get(level, ""),
            "severity": LEVEL_SEVERITY.get(level, "info"),
            "is_error_level": level in ERROR_LEVELS,
            "total_files": total_files,
            "total_size": total_size,
            "total_size_human": _format_bytes(total_size),
            "total_size_kb": round(total_size / 1024, 2),
            "total_lines": total_lines,
            "newest_file": newest_file,
            "newest_time": (
                from_ts(newest_mtime).strftime("%d.%m.%Y %H:%M:%S")
                if newest_mtime
                else ""
            ),
            "has_files": total_files > 0,
            "has_lines": total_lines > 0,
        })

    return stats


def _stats_by_level(stats: Sequence[dict]) -> dict[str, dict]:
    return {str(item.get("name", "")): dict(item) for item in stats}


def _build_error_summary(stats: Sequence[dict]) -> dict:
    by_level = _stats_by_level(stats)

    critical = by_level.get("critical_error_print", {})
    error = by_level.get("error_print", {})
    error1 = by_level.get("error1_print", {})
    warning = by_level.get("warning_print", {})

    return {
        "critical_lines": int(critical.get("total_lines", 0) or 0),
        "error_lines": int(error.get("total_lines", 0) or 0),
        "error1_lines": int(error1.get("total_lines", 0) or 0),
        "warning_lines": int(warning.get("total_lines", 0) or 0),
        "critical_files": int(critical.get("total_files", 0) or 0),
        "error_files": int(error.get("total_files", 0) or 0),
        "error1_files": int(error1.get("total_files", 0) or 0),
        "warning_files": int(warning.get("total_files", 0) or 0),
    }


def _grep(lines: list[str], q: str) -> list[str]:
    q = (q or "").strip().lower()
    if not q:
        return lines
    return [line for line in lines if q in line.lower()]


def get_log_view_data(
    selected_level: str = "",
    selected_date: str = "",
    selected_file: str = "",
    limit: int = DEFAULT_LIMIT,
    auto_latest: bool = True,
    q: str = "",
) -> dict:
    """Готовит данные для HTML-шаблона.

    `q` — поиск по тексту строк (регистронезависимый): при заданном поиске
    читается весь файл (он ограничен ротацией по размеру), фильтруются
    совпадения и показываются последние `limit` из них.
    """
    base_log_dir = Path(get_base_log_dir())

    levels = _get_all_display_levels(base_log_dir)

    selected_level = _safe_name(selected_level)
    selected_date = _safe_name(selected_date)
    selected_file = _safe_name(selected_file)
    limit = _safe_limit(limit)
    search_q = (q or "").strip()

    if selected_level and selected_level not in levels:
        selected_level = ""

    if auto_latest and (not selected_level or not selected_date or not selected_file):
        newest_level, newest_date, newest_file = _find_newest_log_file(
            base_log_dir, only_level=selected_level
        )
        selected_level = selected_level or newest_level
        selected_date = selected_date or newest_date
        selected_file = selected_file or newest_file

    if not selected_level and levels:
        selected_level = levels[0]

    level_dir = base_log_dir / selected_level if selected_level else base_log_dir
    dates = _list_dirs(level_dir)

    if not selected_date and dates:
        selected_date = dates[0]

    date_dir = level_dir / selected_date if selected_date else level_dir
    files = _list_files(date_dir)

    if not selected_file and files:
        selected_file = files[-1]

    log_path: Path | None = None
    log_lines: list[str] = []
    file_size = 0
    file_size_human = "0 B"
    file_mtime = ""
    total_file_lines = 0
    matched_total = 0

    if selected_level and selected_date and selected_file:
        log_path = base_log_dir / selected_level / selected_date / selected_file
        if search_q:
            # Поиск — по всему файлу, а не по хвосту.
            all_lines = _read_tail(log_path, limit=10_000_000)
            matched = _grep(all_lines, search_q)
            matched_total = len(matched)
            log_lines = matched[-limit:]
        else:
            log_lines = _read_tail(log_path, limit=limit)

        if log_path.exists() and log_path.is_file():
            try:
                file_size = log_path.stat().st_size
            except Exception:
                file_size = 0
            file_size_human = _format_bytes(file_size)
            file_mtime = _mtime_iso(log_path)
            total_file_lines = _count_file_lines(log_path)

    stats = _get_stats(base_log_dir, levels)
    error_summary = _build_error_summary(stats)

    return {
        "ok": True,
        "base_log_dir": str(base_log_dir),
        "levels": levels,
        "dates": dates,
        "files": files,
        "selected_level": selected_level,
        "selected_level_label": LEVEL_LABELS.get(selected_level, selected_level),
        "selected_level_title": LEVEL_TITLES.get(selected_level, selected_level),
        "selected_level_severity": LEVEL_SEVERITY.get(selected_level, "info"),
        "selected_date": selected_date,
        "selected_file": selected_file,
        "selected_limit": limit,
        "selected_log_path": str(log_path) if log_path else "",
        "log_lines": log_lines,
        "log_text": "\n".join(log_lines),
        "visible_lines": len(log_lines),
        "total_file_lines": total_file_lines,
        "matched_total": matched_total,
        "search_q": search_q,
        "file_size": file_size,
        "file_size_human": file_size_human,
        "file_mtime": file_mtime,
        "stats": stats,
        "error_summary": error_summary,
        "level_labels": LEVEL_LABELS,
        "level_titles": LEVEL_TITLES,
        "level_severity": LEVEL_SEVERITY,
        "last_update": local_now().strftime("%d.%m.%Y %H:%M:%S"),
        "has_logs": bool(log_lines),
    }


def get_logs_fingerprint() -> tuple:
    """
    «Отпечаток» всей папки логов: меняется при любой записи.

    Используется SSE-стримом /admin/logs/stream, чтобы отправлять обновления
    клиенту только когда в журнале реально что-то изменилось.
    """
    base = Path(get_base_log_dir())
    if not base.exists():
        return ()
    parts = []
    for root, _, filenames in os.walk(base):
        for fname in filenames:
            p = Path(root) / fname
            try:
                st = p.stat()
            except Exception:
                continue
            parts.append((str(p), st.st_mtime, st.st_size))
    return tuple(sorted(parts))
