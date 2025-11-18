from __future__ import annotations

import asyncio
import ipaddress
import os
import platform
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

MAX_TARGETS = 20
IP_LIKE_PATTERN = re.compile(r"^[0-9A-Fa-f:.]+$")
LATENCY_PATTERN = re.compile(r"time[=<]\s*([0-9.]+)\s*ms", re.IGNORECASE)
WINDOWS_AVG_PATTERN = re.compile(r"Average = ([0-9]+)ms", re.IGNORECASE)
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
CLEAR_SCREEN = "\033[2J\033[H"
CURSOR_HOME = "\033[H"


@dataclass
class PingResult:
    address: str
    sent: int
    received: int
    latency_ms: Optional[float]
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.received > 0 and not self.error

    @property
    def success_rate(self) -> float:
        if self.sent == 0:
            return 0.0
        return (self.received / self.sent) * 100


@dataclass
class PingStats:
    address: str
    sent: int = 0
    received: int = 0
    latency_ms: Optional[float] = None
    last_success: bool = False

    @property
    def success_rate(self) -> float:
        if self.sent == 0:
            return 0.0
        return (self.received / self.sent) * 100


class EscapeListener:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._pressed = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._supported = sys.stdin.isatty()

    def start(self) -> None:
        if not self._supported:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join()

    @property
    def pressed(self) -> bool:
        return self._pressed.is_set()

    def _run(self) -> None:
        if os.name == "nt":
            self._run_windows()
        else:
            self._run_posix()

    def _run_windows(self) -> None:
        try:
            import msvcrt
        except ImportError:
            return
        while not self._stop.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b"\x1b":
                    self._pressed.set()
                    break
            time.sleep(0.05)

    def _run_posix(self) -> None:
        try:
            import termios
            import tty
            import select
        except ImportError:
            return
        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
        except termios.error:
            return
        try:
            tty.setcbreak(fd)
            while not self._stop.is_set():
                rlist, _, _ = select.select([fd], [], [], 0.1)
                if not rlist:
                    continue
                try:
                    ch = os.read(fd, 1)
                except OSError:
                    break
                if ch == b"\x1b":
                    self._pressed.set()
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def prompt_addresses() -> List[str]:
    print("Select input method:")
    print("  1) Manual entry")
    print("  2) Load from ip_list.txt")
    choice = ""
    while choice not in {"1", "2"}:
        choice = input("Enter choice (1 or 2): ").strip()
    if choice == "1":
        return prompt_addresses_manual()
    return load_addresses_from_file()


def prompt_addresses_manual() -> List[str]:
    addresses: List[str] = []
    print("Enter up to 20 IP addresses or FQDNs. Type 'end' when finished.")
    while len(addresses) < MAX_TARGETS:
        raw = input(f"Target {len(addresses) + 1}: ").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered == "end":
            break
        if IP_LIKE_PATTERN.fullmatch(raw):
            if not is_valid_ip(raw):
                print("  Invalid IP address. Please try again.")
                continue
        addresses.append(raw)
    if len(addresses) == MAX_TARGETS:
        print("Reached the maximum of 20 targets.")
    if not addresses:
        print("No targets provided. Exiting.")
        sys.exit(0)
    return addresses


def load_addresses_from_file() -> List[str]:
    file_path = resolve_ip_list_path()
    if not file_path.exists():
        message = f"ip_list.txt not found at {file_path}. Exiting."
        print(colorize_text(message, COLOR_YELLOW))
        sys.exit(1)
    addresses: List[str] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if IP_LIKE_PATTERN.fullmatch(stripped) and not is_valid_ip(stripped):
                print(f"Skipping invalid IP in file: {stripped}")
                continue
            addresses.append(stripped)
            if len(addresses) == MAX_TARGETS:
                break
    if not addresses:
        print("File did not contain any valid IP addresses. Exiting.")
        sys.exit(1)
    return addresses


def resolve_ip_list_path() -> Path:
    candidates: List[Path] = []
    main_module = sys.modules.get("__main__")
    if main_module is not None and getattr(main_module, "__file__", None):
        main_path = Path(main_module.__file__).resolve()
        candidates.append(main_path.with_name("ip_list.txt"))
    candidates.append(Path(__file__).resolve().with_name("ip_list.txt"))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return candidates[0]


def is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


async def ping_target(address: str) -> PingResult:
    cmd = build_ping_command(address)
    if cmd is None:
        return PingResult(address, 1, 0, None, "Unsupported OS")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        return PingResult(address, 1, 0, None, "'ping' command not found")
    output = f"{stdout.decode(errors='ignore')}\n{stderr.decode(errors='ignore')}"
    success = proc.returncode == 0
    latency = parse_latency_ms(output)
    received = 1 if success else 0
    if success and latency is None:
        latency = 0.0
    error = None if success else "No reply"
    return PingResult(address, 1, received, latency, error)


def build_ping_command(address: str) -> Optional[list[str]]:
    system = platform.system().lower()
    if system == "windows":
        return ["ping", "-n", "1", "-w", "2000", address]
    if system == "darwin":
        return ["ping", "-c", "1", "-W", "2000", address]
    if system in {"linux", "freebsd"}:
        return ["ping", "-c", "1", "-W", "2", address]
    return None


def parse_latency_ms(output: str) -> Optional[float]:
    match = LATENCY_PATTERN.search(output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    match = WINDOWS_AVG_PATTERN.search(output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def colorize(text: str, success: bool) -> str:
    if not sys.stdout.isatty():
        return text
    color = COLOR_GREEN if success else COLOR_RED
    return f"{color}{text}{COLOR_RESET}"


def colorize_text(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{COLOR_RESET}"


def display_results(stats: List[PingStats], *, initial: bool = False) -> None:
    indent = " " * 5
    header = f"{indent}{'Address':<35}{'Sent/Recv':<12}{'Success %':<12}{'Latency (ms)':<14}"
    buffer: List[str] = []
    if sys.stdout.isatty():
        buffer.append(CLEAR_SCREEN if initial else CURSOR_HOME)
    buffer.append(f"{indent}Press 'Esc' to exit monitoring.\n\n")
    buffer.append(header + "\n")
    buffer.append(indent + "-" * (len(header) - len(indent)) + "\n")
    for stat in stats:
        sent_recv = f"{stat.sent}/{stat.received}"
        success_pct = f"{stat.success_rate:.0f}%"
        latency = f"{stat.latency_ms:.1f}" if stat.latency_ms is not None else "N/A"
        row = f"{indent}{stat.address:<35}{sent_recv:<12}{success_pct:<12}{latency:<14}"
        if stat.sent > 0:
            row = colorize(row, stat.last_success)
        buffer.append(row + "\n")
    sys.stdout.write("".join(buffer))
    sys.stdout.flush()


async def monitor_addresses(addresses: List[str]) -> None:
    stats: Dict[str, PingStats] = {addr: PingStats(addr) for addr in addresses}
    ordered_stats = [stats[addr] for addr in addresses]
    listener = EscapeListener()
    listener.start()
    display_results(ordered_stats, initial=True)
    stopped_by_escape = False
    try:
        while True:
            stop_requested = False
            for addr in addresses:
                if listener.pressed:
                    stop_requested = True
                    stopped_by_escape = True
                    break
                stat = stats[addr]
                stat.sent += 1
                result = await ping_target(addr)
                stat.received += result.received
                stat.latency_ms = result.latency_ms
                stat.last_success = result.success
                display_results(ordered_stats)
                if listener.pressed:
                    stop_requested = True
                    stopped_by_escape = True
                    break
            if stop_requested:
                break
    except KeyboardInterrupt:
        print("\nStopping monitoring (Ctrl+C detected).")
    finally:
        listener.stop()
    if stopped_by_escape:
        print("\nEsc pressed. Stopping monitoring. Goodbye!")


def main() -> None:
    addresses = prompt_addresses()
    asyncio.run(monitor_addresses(addresses))


if __name__ == "__main__":
    main()
