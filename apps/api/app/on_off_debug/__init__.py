# on_off_debug/__init__.py

from app.on_off_debug.debug_mode import (
    apply_debug_settings,
    clear_all_logs,
    critical_error_print,
    debug_error1_print,
    debug_error_print,
    debug_http_log,
    debug_info_print,
    debug_success1_print,
    debug_success_print,
    debug_warning_print,
    flush_log_writes,
    get_debug_settings,
    log_unicode,
    reload_debug_config,
    set_debug_mode,
)
from app.on_off_debug.log_reader import get_log_view_data, get_logs_fingerprint

__all__ = [
    "apply_debug_settings",
    "clear_all_logs",
    "critical_error_print",
    "debug_error1_print",
    "debug_error_print",
    "debug_http_log",
    "debug_info_print",
    "debug_success1_print",
    "debug_success_print",
    "debug_warning_print",
    "flush_log_writes",
    "get_debug_settings",
    "get_log_view_data",
    "get_logs_fingerprint",
    "log_unicode",
    "reload_debug_config",
    "set_debug_mode",
]
