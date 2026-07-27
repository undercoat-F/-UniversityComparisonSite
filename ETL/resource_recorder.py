from __future__ import annotations

import csv
import os
import threading
import time
from datetime import datetime

try:
    import psutil
except ImportError:  # pragma: no cover - optional dependency fallback
    psutil = None


RESOURCE_MONITOR_ENABLED_ENV = "ETL_RESOURCE_MONITOR_ENABLED"
RESOURCE_MONITOR_INTERVAL_ENV = "ETL_RESOURCE_MONITOR_INTERVAL_SEC"


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def start_resource_monitor(log_dt: str):
    if not _env_bool(RESOURCE_MONITOR_ENABLED_ENV, True):
        print("[MONITOR] resource monitoring disabled by env", flush=True)
        return None
    if psutil is None:
        print("[MONITOR] psutil is not installed; resource monitoring disabled", flush=True)
        return None

    interval_sec = max(0.5, _env_float(RESOURCE_MONITOR_INTERVAL_ENV, 5.0))
    monitor_path = os.path.join("log", f"etl_resource_log_{log_dt}.csv")
    os.makedirs("log", exist_ok=True)

    process = psutil.Process(os.getpid())
    process.cpu_percent(None)
    psutil.cpu_percent(None)
    stop_event = threading.Event()

    with open(monitor_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "elapsed_sec",
                "process_cpu_percent",
                "process_rss_mb",
                "system_cpu_percent",
                "system_memory_percent",
            ]
        )

    def _run_monitor() -> None:
        started_at = time.perf_counter()
        with open(monitor_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            while not stop_event.wait(interval_sec):
                try:
                    row = [
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        f"{time.perf_counter() - started_at:.1f}",
                        f"{process.cpu_percent(None):.1f}",
                        f"{process.memory_info().rss / (1024 * 1024):.1f}",
                        f"{psutil.cpu_percent(None):.1f}",
                        f"{psutil.virtual_memory().percent:.1f}",
                    ]
                    writer.writerow(row)
                    f.flush()
                except Exception as exc:  # noqa: BLE001
                    writer.writerow(
                        [
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            f"{time.perf_counter() - started_at:.1f}",
                            "monitor_error",
                            type(exc).__name__,
                            str(exc),
                            "",
                        ]
                    )
                    f.flush()
                    break

    thread = threading.Thread(target=_run_monitor, name="etl-resource-monitor", daemon=True)
    thread.start()
    print(f"[MONITOR] resource log -> {monitor_path} (interval={interval_sec}s)", flush=True)
    return stop_event, thread, monitor_path


def stop_resource_monitor(monitor_state):
    if not monitor_state:
        return None

    stop_event, thread, monitor_path = monitor_state
    stop_event.set()
    thread.join(timeout=2)
    print(f"[MONITOR] resource log finalized -> {monitor_path}", flush=True)
    return monitor_path