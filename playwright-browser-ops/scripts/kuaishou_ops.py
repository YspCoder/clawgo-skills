#!/usr/bin/env python3
"""Run Kuaishou creator publish flows with Playwright."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from media_downloader import MediaDownloader


KUAISHOU_HOME_URL = "https://cp.kuaishou.com"
KUAISHOU_PUBLISH_URL = "https://cp.kuaishou.com/article/publish/video"
KUAISHOU_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video?status=2&from=publish"
LOGIN_KEYWORDS = ("登录", "扫码登录", "手机号登录", "验证码登录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--account", help="Named browser/account profile managed by browser_manager.py")
    parser.add_argument(
        "--profile-dir",
        default=str(Path(__file__).resolve().parent.parent / "tmp" / "kuaishou-profile"),
        help="Persistent browser profile directory",
    )
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Action timeout in milliseconds")
    parser.add_argument("--screenshot", help="Optional screenshot path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Open Kuaishou creator and wait for manual QR login")
    login.add_argument("--wait-seconds", type=int, default=180, help="How long to keep the browser open for manual login")
    subparsers.add_parser("check-login", help="Check whether the persistent profile is logged in")

    publish = subparsers.add_parser("publish-video", help="Publish or preview a Kuaishou video")
    publish.add_argument("--video", help="Local video path")
    publish.add_argument("--video-url", help="Remote video URL to download before upload")
    publish.add_argument("--title", required=True, help="Video title")
    publish.add_argument("--content", default="", help="Video description content")
    publish.add_argument("--tag", action="append", default=[], help="Repeatable topic tag")
    publish.add_argument("--publish", action="store_true", help="Actually click publish")
    publish.add_argument("--verify-publish", action="store_true", help="Wait for a visible publish success signal")
    return parser


def ensure_parent(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright package is not installed. Run: python3 -m pip install playwright && python3 -m playwright install"
        ) from exc
    return sync_playwright


def run_manager_command(*parts: str) -> dict[str, Any]:
    import subprocess, sys

    script = Path(__file__).resolve().parent / "browser_manager.py"
    proc = subprocess.run([sys.executable, str(script), *parts], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or proc.stderr.strip() or f"browser_manager command failed: {' '.join(parts)}")
    return json.loads(proc.stdout)


def resolve_profile_settings(args: argparse.Namespace) -> tuple[str, str]:
    if not args.account:
        return args.browser, str(Path(args.profile_dir).expanduser().resolve())
    payload = run_manager_command("resolve-profile", "--account", args.account)
    return payload["browser"], payload["profile_dir"]


def launch_context(args: argparse.Namespace):
    sync_playwright = get_playwright()
    browser_name, profile_dir = resolve_profile_settings(args)
    playwright_cm = sync_playwright()
    playwright = playwright_cm.__enter__()
    browser_type = getattr(playwright, browser_name)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    context = browser_type.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=args.headless,
        viewport={"width": 1440, "height": 960},
    )
    context.set_default_timeout(args.timeout_ms)
    page = context.pages[0] if context.pages else context.new_page()
    return playwright_cm, context, page, {"browser_name": browser_name, "profile_dir": profile_dir}


def save_screenshot(page, screenshot: str | None) -> str | None:
    path = ensure_parent(screenshot)
    if path:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    return None


def current_page_logged_in(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        text = ""
    return not any(keyword in text for keyword in LOGIN_KEYWORDS)


def is_logged_in(page) -> bool:
    page.goto(KUAISHOU_PUBLISH_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    return current_page_logged_in(page)


def click_button_by_text(page, text: str) -> bool:
    rect = page.evaluate(
        """(targetText) => {
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const nodes = Array.from(document.querySelectorAll('button, div, span, a, label'));
            for (const el of nodes) {
                if (!(el instanceof HTMLElement) || el.offsetParent === null) continue;
                const value = normalize(el.innerText || el.textContent || '');
                if (value !== targetText) continue;
                let target = el;
                let current = el;
                for (let depth = 0; depth < 5 && current; depth += 1) {
                    const rect = current.getBoundingClientRect();
                    if (current.offsetParent !== null && rect.width >= 24 && rect.height >= 18) {
                        target = current;
                        break;
                    }
                    current = current.parentElement;
                }
                const rect = target.getBoundingClientRect();
                target.scrollIntoView({ block: 'center', inline: 'center' });
                return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }
            return null;
        }""",
        text,
    )
    if not rect:
        return False
    page.mouse.click(float(rect["x"]) + float(rect["width"]) / 2, float(rect["y"]) + float(rect["height"]) / 2)
    page.wait_for_timeout(500)
    return True


def dismiss_known_overlays(page) -> None:
    for label in ("我知道了", "知道了", "关闭"):
        try:
            if click_button_by_text(page, label):
                page.wait_for_timeout(500)
        except Exception:
            continue


def resolve_upload_input(page):
    selectors = [
        "input[type='file']",
        "button[class^='_upload-btn'] input[type='file']",
        "input.accept[type='file']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError("Kuaishou upload input not found")


def resolve_description_input(page):
    selectors = [
        "div#work-description-edit[contenteditable='true']",
        "textarea[placeholder*='添加合适的话题和描述']",
        "textarea[placeholder*='描述']",
        "[contenteditable='true']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    raise RuntimeError("Kuaishou description input not found")


def fill_description_and_tags(page, title: str, content: str, tags: list[str]) -> None:
    dismiss_known_overlays(page)
    editor = resolve_description_input(page)
    editor.click()
    try:
        editor.fill("")
    except Exception:
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
    text_parts = [title.strip()]
    if content.strip():
        text_parts.append(content.strip())
    for tag in [item.strip().lstrip("#") for item in tags[:3] if item.strip()]:
        text_parts.append(f"#{tag}")
    payload = " ".join([item for item in text_parts if item]).strip()
    try:
        editor.fill(payload)
    except Exception:
        page.keyboard.type(payload)
    page.wait_for_timeout(500)


def wait_for_upload_complete(page, timeout_ms: int) -> str | None:
    deadline = time.time() + max(20.0, timeout_ms / 1000)
    while time.time() < deadline:
        dismiss_known_overlays(page)
        body = page.locator("body").inner_text(timeout=3000)
        if "上传中" not in body:
            if "发布" in body:
                return "publish_ready"
            return "upload_finished"
        page.wait_for_timeout(1500)
    raise RuntimeError("timed out waiting for Kuaishou upload to complete")


def click_publish(page) -> None:
    if click_button_by_text(page, "发布"):
        page.wait_for_timeout(1000)
    if click_button_by_text(page, "确认发布"):
        page.wait_for_timeout(1000)


def verify_publish(page, timeout_ms: int) -> dict[str, Any]:
    deadline = time.time() + max(10.0, timeout_ms / 1000)
    while time.time() < deadline:
        if page.url.startswith(KUAISHOU_MANAGE_URL):
            body = page.locator("body").inner_text(timeout=3000)
            if "已发布" in body or "审核中" in body:
                return {"verified": True, "signal": "manage_status"}
            return {"verified": True, "signal": "manage_url"}
        body = page.locator("body").inner_text(timeout=3000)
        if "发布成功" in body:
            return {"verified": True, "signal": "success_text"}
        page.wait_for_timeout(1000)
    return {"verified": False, "signal": None}


def validate_file(path_str: str, kind: str) -> str:
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{kind} file not found: {path}")
    return str(path)


def resolve_video_input(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.video and args.video_url:
        raise ValueError("use only one of --video or --video-url")
    if not args.video and not args.video_url:
        raise ValueError("provide one of --video or --video-url")
    downloader: MediaDownloader | None = None
    if args.video_url:
        downloader = MediaDownloader()
        path = downloader.download_video(args.video_url)
        return validate_file(path, "video"), str(downloader.temp_dir)
    return validate_file(args.video, "video"), None


def cleanup_download_dir(path_str: str | None) -> None:
    if not path_str:
        return
    import shutil

    shutil.rmtree(path_str, ignore_errors=True)


def run_login(page, args: argparse.Namespace) -> dict[str, Any]:
    page.goto(KUAISHOU_HOME_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    deadline = time.time() + max(args.wait_seconds, 10)
    logged_in = current_page_logged_in(page)
    while time.time() < deadline and not logged_in:
        page.wait_for_timeout(1500)
        logged_in = current_page_logged_in(page)
    save_screenshot(page, args.screenshot)
    return {
        "ok": logged_in,
        "action": "login",
        "logged_in": logged_in,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_check_login(page, args: argparse.Namespace) -> dict[str, Any]:
    logged_in = is_logged_in(page)
    save_screenshot(page, args.screenshot)
    return {
        "ok": logged_in,
        "action": "check-login",
        "logged_in": logged_in,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_publish_video(page, args: argparse.Namespace) -> dict[str, Any]:
    if not is_logged_in(page):
        raise RuntimeError("Kuaishou profile is not logged in. Run login first.")
    video_path, tmp_dir = resolve_video_input(args)
    try:
        page.goto(KUAISHOU_PUBLISH_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        dismiss_known_overlays(page)
        resolve_upload_input(page).set_input_files(video_path)
        page.wait_for_timeout(3000)
        dismiss_known_overlays(page)
        fill_description_and_tags(page, args.title, args.content, args.tag)
        upload_signal = wait_for_upload_complete(page, args.timeout_ms)
        save_screenshot(page, args.screenshot)
        verification = {"verified": False, "signal": None}
        if args.publish:
            click_publish(page)
            if args.verify_publish:
                verification = verify_publish(page, args.timeout_ms)
                save_screenshot(page, args.screenshot)
        return {
            "ok": True,
            "action": "publish-video",
            "published": bool(args.publish),
            "verified_publish": verification["verified"],
            "publish_signal": verification["signal"],
            "upload_signal": upload_signal,
            "final_url": page.url,
            "video": video_path,
            "tags": args.tag,
            "screenshot": args.screenshot,
        }
    finally:
        cleanup_download_dir(tmp_dir)


def dispatch(page, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "login":
        return run_login(page, args)
    if args.command == "check-login":
        return run_check_login(page, args)
    if args.command == "publish-video":
        return run_publish_video(page, args)
    raise RuntimeError(f"unsupported command: {args.command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    playwright_cm = context = None
    meta: dict[str, Any] = {}
    try:
        playwright_cm, context, page, meta = launch_context(args)
        payload = dispatch(page, args)
        payload.update({"browser": meta.get("browser_name"), "profile_dir": meta.get("profile_dir"), "account": args.account})
    except Exception as exc:
        payload = {"ok": False, "action": getattr(args, "command", "unknown"), "error": str(exc)}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if playwright_cm is not None:
            try:
                playwright_cm.__exit__(None, None, None)
            except Exception:
                pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
