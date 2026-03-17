#!/usr/bin/env python3
"""Run Bilibili publish flows through the biliup CLI."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pty
import shutil
import signal
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from media_downloader import MediaDownloader


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TMP_DIR = SKILL_DIR / "tmp"
BILIBILI_DIR = TMP_DIR / "bilibili"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="default", help="Named Bilibili account cookie slot")
    parser.add_argument("--cookie-file", help="Override biliup cookie file path")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="Subprocess timeout for upload actions")

    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Run biliup login and save cookies for the selected account")
    login.add_argument("--browser", choices=["chrome", "firefox", "edge"], help="Reserved for future browser-based login mode")
    login.add_argument("--wait-seconds", type=int, default=180, help="How long to wait for QR login to complete")

    subparsers.add_parser("check-login", help="Check whether a biliup cookie file exists and looks usable")

    publish = subparsers.add_parser("publish-video", help="Publish a Bilibili video through biliup upload")
    publish.add_argument("--video", help="Local video path")
    publish.add_argument("--video-url", help="Remote video URL to download before upload")
    publish.add_argument("--cover", help="Local cover image path")
    publish.add_argument("--cover-url", help="Remote cover image URL to download before upload")
    publish.add_argument("--title", required=True, help="Video title")
    publish.add_argument("--content", required=True, help="Video description")
    publish.add_argument("--tag", action="append", default=[], help="Repeatable tag field")
    publish.add_argument("--tid", type=int, default=171, help="Bilibili category id")
    publish.add_argument("--copyright", choices=["1", "2"], default="1", help="1=original, 2=repost")
    publish.add_argument("--source", default="", help="Repost source URL or text when copyright=2")
    publish.add_argument("--dynamic", default="", help="Dynamic post text")
    publish.add_argument("--submit", choices=["app", "web", "b-cut-android"], default="web", help="biliup submit backend")
    publish.add_argument("--line", help="Upload line override")
    publish.add_argument("--limit", type=int, default=3, help="Single-file upload concurrency")
    publish.add_argument("--dtime", help="Delayed publish time as 10-digit unix timestamp")
    publish.add_argument("--no-reprint", choices=["0", "1"], default="0", help="1 to forbid repost")
    publish.add_argument("--is-only-self", action="store_true", help="Make the video visible only to self")
    publish.add_argument("--up-selection-reply", action="store_true", help="Enable selected comments when submit=app")
    publish.add_argument("--up-close-reply", action="store_true", help="Disable comments when submit=app")
    publish.add_argument("--up-close-danmu", action="store_true", help="Disable danmu when submit=app")
    publish.add_argument("--extra-fields", help="Opaque extra submit fields string passed to biliup")
    publish.add_argument("--publish", action="store_true", help="Actually call biliup upload")

    return parser


def ensure_runtime_dir() -> None:
    BILIBILI_DIR.mkdir(parents=True, exist_ok=True)


def account_cookie_path(account: str, override: str | None = None) -> Path:
    if override:
        path = Path(override).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    ensure_runtime_dir()
    account_name = "".join(ch.lower() if ch.isalnum() else "-" for ch in account.strip()).strip("-") or "default"
    account_dir = BILIBILI_DIR / account_name
    account_dir.mkdir(parents=True, exist_ok=True)
    return account_dir / "cookies.json"


def find_biliup_runner() -> list[str]:
    binary = shutil.which("biliup")
    if binary:
        return [binary]
    if importlib.util.find_spec("biliup") is not None:
        return [sys.executable, "-m", "biliup"]
    raise RuntimeError("biliup is not installed. Run: python3 -m pip install biliup")


def account_runtime_dir(account: str, override_cookie_file: str | None = None) -> Path:
    cookie_file = account_cookie_path(account, override_cookie_file)
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    return cookie_file.parent


def run_biliup(cookie_file: Path, parts: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    cmd = [*find_biliup_runner(), "-u", str(cookie_file), *parts]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def run_biliup_login_tty(cookie_file: Path, wait_seconds: int, account_dir: Path) -> dict[str, Any]:
    cmd = [*find_biliup_runner(), "-u", str(cookie_file), "login"]
    qrcode_path = account_dir / "qrcode.png"
    if qrcode_path.exists():
        qrcode_path.unlink()
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(account_dir),
        close_fds=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    os.close(slave_fd)
    output_chunks: list[str] = []
    selection_sent = False
    deadline = time.time() + max(wait_seconds, 10)
    try:
        while time.time() < deadline:
            readable, _, _ = select.select([master_fd], [], [], 0.5)
            if readable:
                try:
                    data = os.read(master_fd, 8192)
                except OSError:
                    data = b""
                if data:
                    text = data.decode("utf-8", errors="ignore")
                    output_chunks.append(text)
                    if not selection_sent and "选择一种登录方式" in text:
                        os.write(master_fd, b"\x1b[B\x1b[B\n")
                        selection_sent = True
            payload = parse_cookie_file(cookie_file)
            if payload:
                proc.wait(timeout=5)
                return {
                    "ok": True,
                    "returncode": proc.returncode,
                    "stdout": "".join(output_chunks),
                    "qrcode_path": str(qrcode_path) if qrcode_path.exists() else None,
                }
            if proc.poll() is not None:
                break
        return {
            "ok": False,
            "returncode": proc.poll(),
            "stdout": "".join(output_chunks),
            "qrcode_path": str(qrcode_path) if qrcode_path.exists() else None,
            "error": "login timed out before cookies were saved" if proc.poll() is None else "login exited before cookies were saved",
        }
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            os.close(master_fd)
        except OSError:
            pass


def parse_cookie_file(cookie_file: Path) -> dict[str, Any] | None:
    if not cookie_file.exists():
        return None
    try:
        payload = json.loads(cookie_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def cookie_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"valid_json": False, "has_sessdata": False, "has_csrf": False, "has_uid": False}
    text = json.dumps(payload, ensure_ascii=False)
    return {
        "valid_json": True,
        "has_sessdata": "SESSDATA" in text,
        "has_csrf": "bili_jct" in text,
        "has_uid": "DedeUserID" in text,
    }


def validate_file(path_str: str, kind: str) -> str:
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{kind} file not found: {path}")
    return str(path)


def resolve_video_inputs(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.video and args.video_url:
        raise ValueError("use only one of --video or --video-url")
    if not args.video and not args.video_url:
        raise ValueError("provide one of --video or --video-url")
    downloader: MediaDownloader | None = None
    if args.video_url:
        downloader = MediaDownloader()
        video_path = downloader.download_video(args.video_url)
        return validate_file(video_path, "video"), str(downloader.temp_dir)
    return validate_file(args.video, "video"), None


def resolve_cover_input(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.cover and args.cover_url:
        raise ValueError("use only one of --cover or --cover-url")
    downloader: MediaDownloader | None = None
    if args.cover_url:
        downloader = MediaDownloader()
        cover_path = downloader.download_image(args.cover_url)
        return validate_file(cover_path, "cover"), str(downloader.temp_dir)
    if args.cover:
        return validate_file(args.cover, "cover"), None
    return None, None


def cleanup_download_dir(path_str: str | None) -> None:
    if not path_str:
        return
    shutil.rmtree(path_str, ignore_errors=True)


def run_login(args: argparse.Namespace) -> dict[str, Any]:
    cookie_file = account_cookie_path(args.account, args.cookie_file)
    payload = parse_cookie_file(cookie_file)
    if payload:
        return {
            "ok": True,
            "action": "login",
            "account": args.account,
            "cookie_file": str(cookie_file),
            "cookie_summary": cookie_summary(payload),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "qrcode_path": None,
        }
    account_dir = account_runtime_dir(args.account, args.cookie_file)
    result = run_biliup_login_tty(cookie_file, args.wait_seconds, account_dir)
    payload = parse_cookie_file(cookie_file)
    ok = bool(payload)
    return {
        "ok": ok,
        "action": "login",
        "account": args.account,
        "cookie_file": str(cookie_file),
        "cookie_summary": cookie_summary(payload),
        "returncode": result.get("returncode"),
        "stdout": result.get("stdout", "").strip(),
        "stderr": result.get("error", "").strip(),
        "qrcode_path": result.get("qrcode_path"),
    }


def run_check_login(args: argparse.Namespace) -> dict[str, Any]:
    cookie_file = account_cookie_path(args.account, args.cookie_file)
    payload = parse_cookie_file(cookie_file)
    summary = cookie_summary(payload)
    return {
        "ok": bool(payload),
        "action": "check-login",
        "account": args.account,
        "cookie_file": str(cookie_file),
        "exists": cookie_file.exists(),
        "cookie_summary": summary,
    }


def build_upload_parts(args: argparse.Namespace, video_path: str, cover_path: str | None) -> list[str]:
    parts = [
        "upload",
        video_path,
        "--submit",
        args.submit,
        "--limit",
        str(args.limit),
        "--copyright",
        args.copyright,
        "--tid",
        str(args.tid),
        "--title",
        args.title,
        "--desc",
        args.content,
        "--tag",
        ",".join([item.strip() for item in args.tag if item.strip()]),
    ]
    if args.source:
        parts.extend(["--source", args.source])
    if args.dynamic:
        parts.extend(["--dynamic", args.dynamic])
    if cover_path:
        parts.extend(["--cover", cover_path])
    if args.line:
        parts.extend(["--line", args.line])
    if args.dtime:
        parts.extend(["--dtime", args.dtime])
    if args.no_reprint:
        parts.extend(["--no-reprint", args.no_reprint])
    if args.is_only_self:
        parts.extend(["--is-only-self", "1"])
    if args.up_selection_reply:
        parts.append("--up-selection-reply")
    if args.up_close_reply:
        parts.append("--up-close-reply")
    if args.up_close_danmu:
        parts.append("--up-close-danmu")
    if args.extra_fields:
        parts.extend(["--extra-fields", args.extra_fields])
    return parts


def run_publish_video(args: argparse.Namespace) -> dict[str, Any]:
    cookie_file = account_cookie_path(args.account, args.cookie_file)
    if not cookie_file.exists():
        raise RuntimeError(f"cookie file not found for account {args.account}: {cookie_file}. Run login first.")

    video_path, video_temp_dir = resolve_video_inputs(args)
    cover_path, cover_temp_dir = resolve_cover_input(args)
    try:
        upload_parts = build_upload_parts(args, video_path, cover_path)
        if not args.publish:
            return {
                "ok": True,
                "action": "publish-video",
                "account": args.account,
                "cookie_file": str(cookie_file),
                "publish": False,
                "video": video_path,
                "cover": cover_path,
                "command_preview": [*find_biliup_runner(), "-u", str(cookie_file), *upload_parts],
            }
        result = run_biliup(cookie_file, upload_parts, args.timeout_seconds)
        ok = result.returncode == 0
        return {
            "ok": ok,
            "action": "publish-video",
            "account": args.account,
            "cookie_file": str(cookie_file),
            "publish": True,
            "video": video_path,
            "cover": cover_path,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    finally:
        cleanup_download_dir(video_temp_dir)
        cleanup_download_dir(cover_temp_dir)


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "login":
        return run_login(args)
    if args.command == "check-login":
        return run_check_login(args)
    if args.command == "publish-video":
        return run_publish_video(args)
    raise RuntimeError(f"unsupported command: {args.command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = dispatch(args)
    except subprocess.TimeoutExpired as exc:
        payload = {
            "ok": False,
            "action": getattr(args, "command", "unknown"),
            "error": f"subprocess timeout after {exc.timeout} seconds",
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "action": getattr(args, "command", "unknown"),
            "error": str(exc),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
