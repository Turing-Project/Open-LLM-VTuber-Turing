"""Windows desktop launcher for Open-LLM-VTuber.

The launcher starts the Python backend with the bundled uv executable and opens
the local frontend in Microsoft Edge's app mode.  Keeping the backend separate
from this tiny executable makes character/config changes immediately visible.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from tkinter import messagebox


CREATE_NO_WINDOW = 0x08000000


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def read_server_address(root: Path) -> tuple[str, int]:
    text = (root / "conf.yaml").read_text(encoding="utf-8")
    system_block = text.split("character_config:", 1)[0]
    host_match = re.search(r"^\s*host:\s*['\"]?([^'\"\s#]+)", system_block, re.M)
    port_match = re.search(r"^\s*port:\s*(\d+)", system_block, re.M)
    host = host_match.group(1) if host_match else "localhost"
    port = int(port_match.group(1)) if port_match else 12393
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return browser_host, port


def find_edge() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def wait_until_ready(host: str, port: int, process: subprocess.Popen, timeout: int = 180) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    root = app_dir()
    uv = root / "runtime" / "uv.exe"
    if not uv.is_file():
        messagebox.showerror("Open-LLM-VTuber", f"缺少运行组件：{uv}")
        return 1

    try:
        host, port = read_server_address(root)
    except Exception as exc:
        messagebox.showerror("Open-LLM-VTuber", f"读取 conf.yaml 失败：\n{exc}")
        return 1

    data_dir = Path(os.environ.get("LOCALAPPDATA", root)) / "Open-LLM-VTuber"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "desktop-backend.log"
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(data_dir / "uv-cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(data_dir / "python")

    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(uv), "run", "run_server.py"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        try:
            if not wait_until_ready(host, port, process):
                messagebox.showerror(
                    "Open-LLM-VTuber",
                    f"服务启动失败或超时。详细日志：\n{log_path}",
                )
                return 1

            url = f"http://{host}:{port}"
            edge = find_edge()
            if edge:
                edge_profile = data_dir / "edge-profile"
                window = subprocess.Popen(
                    [
                        str(edge),
                        f"--app={url}",
                        f"--user-data-dir={edge_profile}",
                        "--start-maximized",
                        "--no-first-run",
                        "--disable-background-mode",
                    ],
                    creationflags=CREATE_NO_WINDOW,
                )
                window.wait()
            else:
                webbrowser.open(url)
                messagebox.showinfo(
                    "Open-LLM-VTuber",
                    "应用已在浏览器中打开。关闭此提示将同时停止后端服务。",
                )
            return 0
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    check=False,
                )


if __name__ == "__main__":
    raise SystemExit(main())
