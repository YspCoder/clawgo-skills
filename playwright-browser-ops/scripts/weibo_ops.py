#!/usr/bin/env python3
"""Run Weibo compose and publish flows with Playwright."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from media_downloader import MediaDownloader


WEIBO_HOME_URL = "https://weibo.com"
WEIBO_COMPOSE_URL = "https://weibo.com"
LOGIN_KEYWORDS = ("登录", "注册", "手机号登录", "扫码登录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--account", help="Named browser/account profile managed by browser_manager.py")
    parser.add_argument(
        "--profile-dir",
        default=str(Path(__file__).resolve().parent.parent / "tmp" / "weibo-profile"),
        help="Persistent browser profile directory",
    )
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Action timeout in milliseconds")
    parser.add_argument("--screenshot", help="Optional screenshot path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Open Weibo and wait for manual login")
    login.add_argument("--wait-seconds", type=int, default=180, help="How long to keep the browser open for manual login")
    subparsers.add_parser("check-login", help="Check whether the persistent profile is logged in")

    text_post = subparsers.add_parser("publish-text", help="Publish or preview a text-only Weibo post")
    text_post.add_argument("--content", required=True, help="Post content")
    text_post.add_argument("--publish", action="store_true", help="Actually click publish")
    text_post.add_argument("--verify-publish", action="store_true", help="Wait for a visible publish success signal")

    image_post = subparsers.add_parser("publish-images", help="Publish or preview a Weibo image post")
    image_post.add_argument("--content", required=True, help="Post content")
    image_post.add_argument("--images", nargs="*", default=[], help="Local image paths")
    image_post.add_argument("--image-urls", nargs="*", default=[], help="Remote image URLs to download before upload")
    image_post.add_argument("--publish", action="store_true", help="Actually click publish")
    image_post.add_argument("--verify-publish", action="store_true", help="Wait for a visible publish success signal")
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
    page.goto(WEIBO_HOME_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    return current_page_logged_in(page)


def resolve_editor(page):
    selectors = [
        "div[contenteditable='true']",
        "textarea",
        "[node-type='textEl']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    raise RuntimeError("Weibo compose editor not found")


def fill_editor(locator, content: str) -> None:
    locator.click()
    locator.evaluate(
        """(el, value) => {
            el.focus();
            if (el.isContentEditable) {
                el.innerHTML = '';
                const lines = String(value).split('\\n');
                for (const line of lines) {
                    const p = document.createElement('p');
                    p.textContent = line || '';
                    el.appendChild(p);
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                return;
            }
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        content,
    )


def click_button_by_text(page, text: str) -> bool:
    rect = page.evaluate(
        """(targetText) => {
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const nodes = Array.from(document.querySelectorAll('button, div, span, a'));
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


def resolve_upload_input(page):
    selectors = [
        "input[type='file']",
        "input[accept*='image']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError("Weibo image upload input not found")


def validate_files(paths: list[str]) -> list[str]:
    resolved = [str(Path(path).expanduser().resolve()) for path in paths]
    missing = [path for path in resolved if not Path(path).is_file()]
    if missing:
        raise FileNotFoundError(f"missing files: {missing}")
    return resolved


def resolve_image_inputs(args: argparse.Namespace) -> tuple[list[str], str | None]:
    local_images = list(args.images or [])
    image_urls = list(args.image_urls or [])
    if not local_images and not image_urls:
        raise ValueError("provide at least one of --images or --image-urls")
    downloader: MediaDownloader | None = None
    if image_urls:
        downloader = MediaDownloader()
        local_images.extend(downloader.download_images(image_urls))
    return validate_files(local_images), str(downloader.temp_dir) if downloader else None


def cleanup_download_dir(path_str: str | None) -> None:
    if not path_str:
        return
    import shutil

    shutil.rmtree(path_str, ignore_errors=True)


def verify_publish(page, timeout_ms: int) -> dict[str, Any]:
    deadline = time.time() + max(8.0, timeout_ms / 1000)
    while time.time() < deadline:
        body = page.locator("body").inner_text(timeout=3000)
        if "发布成功" in body or "发送成功" in body:
            return {"verified": True, "signal": "success_text"}
        page.wait_for_timeout(1000)
    return {"verified": False, "signal": None}


def open_compose(page) -> None:
    page.goto(WEIBO_COMPOSE_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass


def run_login(page, args: argparse.Namespace) -> dict[str, Any]:
    open_compose(page)
    deadline = time.time() + max(args.wait_seconds, 10)
    logged_in = current_page_logged_in(page)
    while time.time() < deadline and not logged_in:
        page.wait_for_timeout(1500)
        logged_in = current_page_logged_in(page)
    while logged_in and time.time() < deadline:
        page.wait_for_timeout(min(1500, int((deadline - time.time()) * 1000)))
    save_screenshot(page, args.screenshot)
    return {"ok": logged_in, "action": "login", "logged_in": logged_in, "final_url": page.url, "screenshot": args.screenshot}


def run_check_login(page, args: argparse.Namespace) -> dict[str, Any]:
    logged_in = is_logged_in(page)
    save_screenshot(page, args.screenshot)
    return {"ok": logged_in, "action": "check-login", "logged_in": logged_in, "final_url": page.url, "screenshot": args.screenshot}


def run_publish_text(page, args: argparse.Namespace) -> dict[str, Any]:
    if not is_logged_in(page):
        raise RuntimeError("Weibo profile is not logged in. Run login first.")
    open_compose(page)
    fill_editor(resolve_editor(page), args.content)
    save_screenshot(page, args.screenshot)
    verification = {"verified": False, "signal": None}
    if args.publish:
        if not click_button_by_text(page, "发送") and not click_button_by_text(page, "发布"):
            raise RuntimeError("Weibo publish button not found")
        if args.verify_publish:
            verification = verify_publish(page, args.timeout_ms)
            save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "publish-text",
        "published": bool(args.publish),
        "verified_publish": verification["verified"],
        "publish_signal": verification["signal"],
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_publish_images(page, args: argparse.Namespace) -> dict[str, Any]:
    if not is_logged_in(page):
        raise RuntimeError("Weibo profile is not logged in. Run login first.")
    images, cleanup_dir = resolve_image_inputs(args)
    try:
        open_compose(page)
        fill_editor(resolve_editor(page), args.content)
        resolve_upload_input(page).set_input_files(images)
        page.wait_for_timeout(3000)
        save_screenshot(page, args.screenshot)
        verification = {"verified": False, "signal": None}
        if args.publish:
            if not click_button_by_text(page, "发送") and not click_button_by_text(page, "发布"):
                raise RuntimeError("Weibo publish button not found")
            if args.verify_publish:
                verification = verify_publish(page, args.timeout_ms)
                save_screenshot(page, args.screenshot)
        return {
            "ok": True,
            "action": "publish-images",
            "published": bool(args.publish),
            "verified_publish": verification["verified"],
            "publish_signal": verification["signal"],
            "final_url": page.url,
            "files": images,
            "screenshot": args.screenshot,
        }
    finally:
        cleanup_download_dir(cleanup_dir)


def dispatch(page, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "login":
        return run_login(page, args)
    if args.command == "check-login":
        return run_check_login(page, args)
    if args.command == "publish-text":
        return run_publish_text(page, args)
    if args.command == "publish-images":
        return run_publish_images(page, args)
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
