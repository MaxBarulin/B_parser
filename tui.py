"""Interactive menu for the customer demo.

Launches automatically when `python main.py` is run with no arguments,
or with `python main.py tui`. Every action's console output is tee'd to
logs/session_<ts>.log so the customer can zip and ship logs back to us.
"""
from __future__ import annotations

import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
SESSION_LOG = LOG_DIR / f"session_{time.strftime('%Y%m%d_%H%M%S')}.log"


class _Tee:
    """Write to multiple streams. Tolerant of tqdm's carriage returns."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:  # noqa: BLE001
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self):
        return getattr(self.streams[0], "isatty", lambda: False)()


def _banner() -> None:
    print()
    print("=" * 64)
    print(" B_parser — выгрузка и анализ данных BTC / Polymarket")
    print(f" Лог сессии: {SESSION_LOG}")
    print(" Все действия пишутся в этот файл — пригодится для разработчика")
    print("=" * 64)


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else (default or "")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        s = _ask(prompt, str(default))
        try:
            return int(s)
        except ValueError:
            print(f"  введи целое число (или Enter для {default})")


def _menu(title: str, options: list[tuple[str, object]]) -> object:
    print()
    print(title)
    for i, (label, _) in enumerate(options, 1):
        print(f"  {i}) {label}")
    print("  0) Назад")
    while True:
        s = input("Выбор: ").strip()
        if s == "0" or s == "":
            return None
        try:
            i = int(s)
            if 1 <= i <= len(options):
                return options[i - 1][1]
        except ValueError:
            pass
        print(f"  введи число 0..{len(options)}")


def _load_cfg():
    import yaml
    cfg_path = Path("config.yaml")
    if not cfg_path.exists() and getattr(sys, "frozen", False):
        # When packed by PyInstaller, also look beside the .exe
        alt = Path(sys.executable).parent / "config.yaml"
        if alt.exists():
            cfg_path = alt
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def run() -> None:
    log_fh = SESSION_LOG.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, log_fh)
    sys.stderr = _Tee(sys.__stderr__, log_fh)

    print(f"\n[session] start {datetime.now().isoformat(timespec='seconds')}")
    _banner()
    cfg = _load_cfg()

    actions: list[tuple[str, str]] = [
        ("Скачать данные (klines + aggTrades)", "download"),
        ("Что лежит в кэше", "status"),
        ("Прогнать анализ (UP/DOWN + серии + сигналы)", "analyze"),
        ("Выгрузить всё в Excel", "export"),
        ("Проверить связь с биржами", "ping"),
        ("Упаковать логи в ZIP для разработчика", "package"),
    ]

    while True:
        choice = _menu("Что делаем?", actions)
        if choice is None:
            print("Выход.")
            break
        try:
            _dispatch(choice, cfg)
        except KeyboardInterrupt:
            print("\nПрервано пользователем.")
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"\nОшибка: {e}")
            print(f"Подробности в {SESSION_LOG}")


def _dispatch(action: str, cfg: dict) -> None:
    if action == "download":
        _do_download(cfg)
    elif action == "status":
        _do_status(cfg)
    elif action == "analyze":
        _do_analyze(cfg)
    elif action == "export":
        _do_export(cfg)
    elif action == "ping":
        _do_ping()
    elif action == "package":
        _do_package(cfg)


def _do_download(cfg: dict) -> None:
    import main as M
    period = cfg.get("period", {}) or {}
    start = _ask("Старт (UTC, YYYY-MM-DD)", str(period.get("start", "2025-12-18"))[:10])
    end = _ask("Конец (UTC, YYYY-MM-DD)", str(period.get("end", "2026-05-07"))[:10])
    sources = _menu("Какие источники?", [
        ("Всё (klines + aggTrades — долго)", ["binance_futures", "binance_spot", "bybit_linear", "binance_aggtrades"]),
        ("Только klines (быстро)", ["binance_futures", "binance_spot", "bybit_linear"]),
        ("Только Binance Spot", ["binance_spot"]),
        ("Только Binance Futures", ["binance_futures"]),
        ("Только Bybit", ["bybit_linear"]),
        ("Только aggTrades (медленно, ГБ трафика)", ["binance_aggtrades"]),
    ])
    if sources is None:
        return
    args = type("A", (), {"start": start, "end": end, "sources": sources})()
    M.cmd_download(args, cfg)


def _do_status(cfg: dict) -> None:
    import main as M
    M.cmd_status(None, cfg)


def _do_analyze(cfg: dict) -> None:
    import main as M
    src = _menu("Источник для реконструкции исходов?", [
        ("binance_spot (рекомендую — ближе к Polymarket)", "binance_spot"),
        ("binance_futures", "binance_futures"),
        ("bybit_linear", "bybit_linear"),
    ])
    if src is None:
        return
    rule = _menu("Как считаем UP/DOWN?", [
        ("close > open в той же свече (стандарт)", "candle"),
        ("close[t] > close[t-1] (скользящее)", "close_diff"),
    ])
    if rule is None:
        return
    max_attempts = _ask_int("Сколько ставок догон после тройки?", 3)
    long_threshold = _ask_int("С какой длины серия считается 'длинной'?", 7)
    args = type("A", (), {
        "source": src,
        "outcome_rule": rule,
        "max_attempts": max_attempts,
        "long_threshold": long_threshold,
    })()
    M.cmd_analyze(args, cfg)


def _do_export(cfg: dict) -> None:
    import main as M
    fmt = _menu("Формат?", [
        ("Excel (.xlsx)", ("xlsx", ",")),
        ("CSV с ';' (для русского Excel)", ("csv", ";")),
        ("CSV с ',' (международный)", ("csv", ",")),
    ])
    if fmt is None:
        return
    out_dir = _ask("Папка для экспорта", "export")
    args = type("A", (), {
        "out": out_dir,
        "format": fmt[0],
        "csv_sep": fmt[1],
    })()
    M.cmd_export(args, cfg)


def _do_ping() -> None:
    import requests
    targets = [
        ("Binance Futures", "https://fapi.binance.com/fapi/v1/ping"),
        ("Binance Spot", "https://api.binance.com/api/v3/ping"),
        ("Bybit", "https://api.bybit.com/v5/market/time"),
        ("data.binance.vision",
         "https://data.binance.vision/?prefix=data/futures/um/daily/aggTrades/BTCUSDT/&max-keys=1"),
    ]
    print()
    for name, url in targets:
        t0 = time.time()
        try:
            r = requests.get(url, timeout=10)
            ms = int((time.time() - t0) * 1000)
            print(f"  {name:22s}  HTTP {r.status_code}  {ms} ms")
        except Exception as e:  # noqa: BLE001
            print(f"  {name:22s}  ОШИБКА: {e}")


def _do_package(cfg: dict) -> None:
    out = Path(f"B_parser_logs_{time.strftime('%Y%m%d_%H%M%S')}.zip")
    print(f"  собираю {out}...")
    cache_dir = Path(cfg.get("cache_dir", "cache"))

    inventory_lines: list[str] = []
    if cache_dir.exists():
        for f in sorted(cache_dir.rglob("*")):
            if f.is_file():
                size = f.stat().st_size
                inventory_lines.append(f"{f.relative_to(cache_dir).as_posix()}\t{size}")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(LOG_DIR.glob("*")):
            if f.is_file():
                z.write(f, f"logs/{f.name}")
        z.writestr("cache_inventory.txt",
                   "filename\tsize_bytes\n" + "\n".join(inventory_lines))
        if Path("config.yaml").exists():
            z.write("config.yaml", "config.yaml")
        # also include a tiny "env" file: Python/OS info
        import platform
        env_info = (
            f"python={sys.version.replace(chr(10), ' ')}\n"
            f"platform={platform.platform()}\n"
            f"executable={sys.executable}\n"
            f"frozen={getattr(sys, 'frozen', False)}\n"
        )
        z.writestr("env.txt", env_info)

    size_kb = out.stat().st_size // 1024
    print(f"  готово: {out}  ({size_kb} КБ)")
    print("  отправь этот файл разработчику")


if __name__ == "__main__":
    run()
