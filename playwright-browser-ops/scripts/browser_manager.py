#!/usr/bin/env python3
"""Manage browser profiles and launched browser instances for automation skills."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_DIR = SKILL_DIR / "config"
TMP_DIR = SKILL_DIR / "tmp"
PROFILE_ROOT = TMP_DIR / "profiles"
RUNTIME_DIR = TMP_DIR / "browser-manager"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
PID_FILE = RUNTIME_DIR / "instances.json"
DEFAULT_BROWSER = "chromium"
DEFAULT_PORT = 9222


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def load_accounts() -> dict[str, Any]:
    ensure_dirs()
    if not ACCOUNTS_FILE.exists():
        data = {
            "default_account": "default",
            "accounts": {
                "default": {
                    "alias": "Default",
                    "browser": DEFAULT_BROWSER,
                    "profile_dir": str((PROFILE_ROOT / "default").resolve()),
                    "debug_port": DEFAULT_PORT,
                }
            },
        }
        save_accounts(data)
        return data
    return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))


def save_accounts(data: dict[str, Any]) -> None:
    ensure_dirs()
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_instances() -> dict[str, Any]:
    ensure_dirs()
    if not PID_FILE.exists():
        return {}
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_instances(data: dict[str, Any]) -> None:
    ensure_dirs()
    PID_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-") or "default"


def get_account_config(data: dict[str, Any], account: str | None) -> tuple[str, dict[str, Any]]:
    name = account or data.get("default_account") or "default"
    accounts = data.setdefault("accounts", {})
    if name not in accounts:
        raise KeyError(f"account not found: {name}")
    cfg = accounts[name]
    profile_dir = cfg.get("profile_dir") or str((PROFILE_ROOT / name).resolve())
    cfg["profile_dir"] = str(Path(profile_dir).expanduser().resolve())
    cfg["browser"] = cfg.get("browser") or DEFAULT_BROWSER
    cfg["debug_port"] = int(cfg.get("debug_port") or DEFAULT_PORT)
    return name, cfg


def upsert_account(
    name: str,
    alias: str | None,
    browser: str | None,
    profile_dir: str | None,
    debug_port: int | None,
    set_default: bool,
) -> dict[str, Any]:
    data = load_accounts()
    account_name = slugify(name)
    accounts = data.setdefault("accounts", {})
    current = accounts.get(account_name, {})
    current["alias"] = alias or current.get("alias") or account_name
    current["browser"] = browser or current.get("browser") or DEFAULT_BROWSER
    current["profile_dir"] = str(Path(profile_dir).expanduser().resolve()) if profile_dir else current.get("profile_dir") or str((PROFILE_ROOT / account_name).resolve())
    current["debug_port"] = int(debug_port or current.get("debug_port") or DEFAULT_PORT)
    accounts[account_name] = current
    if set_default or "default_account" not in data:
        data["default_account"] = account_name
    save_accounts(data)
    return {"ok": True, "action": "upsert-account", "account": account_name, "config": current, "default_account": data.get("default_account")}


def remove_account(name: str) -> dict[str, Any]:
    data = load_accounts()
    account_name = slugify(name)
    accounts = data.setdefault("accounts", {})
    if account_name not in accounts:
        raise KeyError(f"account not found: {account_name}")
    removed = accounts.pop(account_name)
    if data.get("default_account") == account_name:
        data["default_account"] = next(iter(accounts), "default")
    save_accounts(data)
    return {"ok": True, "action": "remove-account", "account": account_name, "removed": removed, "default_account": data.get("default_account")}


def list_accounts() -> dict[str, Any]:
    data = load_accounts()
    accounts = []
    for name, cfg in data.get("accounts", {}).items():
        accounts.append(
            {
                "name": name,
                "alias": cfg.get("alias"),
                "browser": cfg.get("browser"),
                "profile_dir": cfg.get("profile_dir"),
                "debug_port": cfg.get("debug_port"),
                "is_default": name == data.get("default_account"),
            }
        )
    return {"ok": True, "action": "list-accounts", "default_account": data.get("default_account"), "accounts": accounts}


def set_default_account(name: str) -> dict[str, Any]:
    data = load_accounts()
    account_name, _ = get_account_config(data, name)
    data["default_account"] = account_name
    save_accounts(data)
    return {"ok": True, "action": "set-default-account", "default_account": account_name}


def detect_browser_path(browser: str) -> str:
    browser = browser.lower()
    candidates: list[str] = []
    if browser != "chromium":
        found = shutil.which(browser)
        if found:
            return found
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    elif sys.platform == "win32":
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var, "")
            if base:
                candidates.extend(
                    [
                        os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                        os.path.join(base, "Chromium", "Application", "chromium.exe"),
                    ]
                )
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(f"browser executable not found for: {browser}")


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def build_launch_command(executable: str, browser: str, profile_dir: str, port: int, headless: bool) -> list[str]:
    cmd = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if browser in {"chromium", "chrome"} and headless:
        cmd.append("--headless=new")
    elif headless:
        cmd.append("--headless")
    return cmd


def launch_browser(account: str | None, headless: bool, port: int | None, browser: str | None) -> dict[str, Any]:
    data = load_accounts()
    account_name, cfg = get_account_config(data, account)
    executable = detect_browser_path(browser or cfg["browser"])
    debug_port = int(port or cfg["debug_port"])
    profile_dir = Path(cfg["profile_dir"]).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    instances = load_instances()
    existing = instances.get(account_name)
    if existing and is_process_running(int(existing.get("pid", 0))) and is_port_open("127.0.0.1", int(existing.get("port", debug_port))):
        return {"ok": True, "action": "launch", "account": account_name, "already_running": True, "instance": existing}
    cmd = build_launch_command(executable, browser or cfg["browser"], str(profile_dir), debug_port, headless)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 15
    while time.time() < deadline:
        if is_port_open("127.0.0.1", debug_port):
            break
        time.sleep(0.3)
    instance = {
        "pid": proc.pid,
        "port": debug_port,
        "browser": browser or cfg["browser"],
        "profile_dir": str(profile_dir),
        "headless": headless,
        "started_at": int(time.time()),
    }
    instances[account_name] = instance
    save_instances(instances)
    return {"ok": True, "action": "launch", "account": account_name, "already_running": False, "instance": instance, "command": cmd}


def kill_browser(account: str | None) -> dict[str, Any]:
    data = load_accounts()
    account_name, _ = get_account_config(data, account)
    instances = load_instances()
    instance = instances.get(account_name)
    if not instance:
        return {"ok": True, "action": "kill", "account": account_name, "killed": False, "reason": "no tracked instance"}
    pid = int(instance.get("pid", 0))
    if is_process_running(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        time.sleep(1.0)
        if is_process_running(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
    instances.pop(account_name, None)
    save_instances(instances)
    return {"ok": True, "action": "kill", "account": account_name, "killed": True}


def status(account: str | None) -> dict[str, Any]:
    data = load_accounts()
    if account:
        names = [get_account_config(data, account)[0]]
    else:
        names = list(data.get("accounts", {}).keys())
    instances = load_instances()
    rows = []
    for name in names:
        _, cfg = get_account_config(data, name)
        instance = instances.get(name)
        running = False
        if instance:
            running = is_process_running(int(instance.get("pid", 0))) and is_port_open("127.0.0.1", int(instance.get("port", cfg["debug_port"])))
        rows.append(
            {
                "account": name,
                "browser": cfg.get("browser"),
                "profile_dir": cfg.get("profile_dir"),
                "debug_port": cfg.get("debug_port"),
                "running": running,
                "instance": instance if running else None,
            }
        )
    return {"ok": True, "action": "status", "rows": rows}


def resolve_profile(account: str | None) -> dict[str, Any]:
    data = load_accounts()
    account_name, cfg = get_account_config(data, account)
    return {"ok": True, "action": "resolve-profile", "account": account_name, "browser": cfg["browser"], "profile_dir": cfg["profile_dir"], "debug_port": cfg["debug_port"]}


def resolve_instance(account: str | None) -> dict[str, Any]:
    data = load_accounts()
    account_name, cfg = get_account_config(data, account)
    instances = load_instances()
    instance = instances.get(account_name)
    running = False
    if instance:
        running = is_process_running(int(instance.get("pid", 0))) and is_port_open("127.0.0.1", int(instance.get("port", cfg["debug_port"])))
    return {
        "ok": True,
        "action": "resolve-instance",
        "account": account_name,
        "browser": cfg["browser"],
        "profile_dir": cfg["profile_dir"],
        "debug_port": cfg["debug_port"],
        "running": running,
        "instance": instance if running else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add-account", help="Add or update an automation account")
    add.add_argument("name")
    add.add_argument("--alias")
    add.add_argument("--browser", default=DEFAULT_BROWSER)
    add.add_argument("--profile-dir")
    add.add_argument("--debug-port", type=int, default=DEFAULT_PORT)
    add.add_argument("--set-default", action="store_true")

    remove = subparsers.add_parser("remove-account", help="Remove an account")
    remove.add_argument("name")

    set_default = subparsers.add_parser("set-default-account", help="Set default account")
    set_default.add_argument("name")

    subparsers.add_parser("list-accounts", help="List accounts")

    launch = subparsers.add_parser("launch", help="Launch a browser instance for an account")
    launch.add_argument("--account")
    launch.add_argument("--browser")
    launch.add_argument("--port", type=int)
    launch.add_argument("--headless", action="store_true")

    kill = subparsers.add_parser("kill", help="Kill a tracked browser instance")
    kill.add_argument("--account")

    status_parser = subparsers.add_parser("status", help="Show tracked browser status")
    status_parser.add_argument("--account")

    resolve = subparsers.add_parser("resolve-profile", help="Resolve account profile settings")
    resolve.add_argument("--account")

    resolve_instance_parser = subparsers.add_parser("resolve-instance", help="Resolve account profile and tracked instance status")
    resolve_instance_parser.add_argument("--account")

    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "add-account":
        return upsert_account(args.name, args.alias, args.browser, args.profile_dir, args.debug_port, args.set_default)
    if args.command == "remove-account":
        return remove_account(args.name)
    if args.command == "set-default-account":
        return set_default_account(args.name)
    if args.command == "list-accounts":
        return list_accounts()
    if args.command == "launch":
        return launch_browser(args.account, args.headless, args.port, args.browser)
    if args.command == "kill":
        return kill_browser(args.account)
    if args.command == "status":
        return status(args.account)
    if args.command == "resolve-profile":
        return resolve_profile(args.account)
    if args.command == "resolve-instance":
        return resolve_instance(args.account)
    raise ValueError(f"unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = dispatch(args)
    except Exception as exc:
        result = {"ok": False, "action": args.command, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
