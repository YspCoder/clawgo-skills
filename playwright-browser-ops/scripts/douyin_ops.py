#!/usr/bin/env python3
"""Run Douyin creator-center publish flows with Playwright."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from media_downloader import MediaDownloader


DOUYIN_CREATOR_HOME = "https://creator.douyin.com/"
DOUYIN_UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
DOUYIN_PUBLISH_URL_PREFIXES = (
    "https://creator.douyin.com/creator-micro/content/publish",
    "https://creator.douyin.com/creator-micro/content/post/video",
)
DOUYIN_MANAGE_URL_PREFIX = "https://creator.douyin.com/creator-micro/content/manage"
LOGIN_KEYWORDS = ("扫码登录", "手机号登录", "登录", "身份验证")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--account", help="Named browser/account profile managed by browser_manager.py")
    parser.add_argument(
        "--profile-dir",
        default=str(Path(__file__).resolve().parent.parent / "tmp" / "douyin-profile"),
        help="Persistent browser profile directory",
    )
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Action timeout in milliseconds")
    parser.add_argument("--screenshot", help="Optional screenshot path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Open Douyin creator and wait for manual QR login")
    login.add_argument("--wait-seconds", type=int, default=180, help="How long to keep the browser open for manual login")
    subparsers.add_parser("check-login", help="Check whether the persistent profile is logged in")

    publish = subparsers.add_parser("publish-video", help="Publish or preview a Douyin video")
    publish.add_argument("--video", help="Local video path")
    publish.add_argument("--video-url", help="Remote video URL to download before upload")
    publish.add_argument("--thumbnail", help="Local thumbnail path")
    publish.add_argument("--thumbnail-url", help="Remote thumbnail URL to download before upload")
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
    script = Path(__file__).resolve().parent / "browser_manager.py"
    proc = subprocess.run(
        [sys.executable, str(script), *parts],
        capture_output=True,
        text=True,
        check=False,
    )
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
    meta = {"browser_name": browser_name, "profile_dir": profile_dir}
    return playwright_cm, context, page, meta


def visible_editable_candidates(page):
    candidates = []
    locator = page.locator("input:not([type='file']), textarea, [contenteditable='true'], [role='textbox']")
    try:
        count = locator.count()
    except Exception:
        count = 0
    for idx in range(count):
        item = locator.nth(idx)
        try:
            if item.is_visible(timeout=500):
                candidates.append(item)
        except Exception:
            continue
    return candidates


def current_page_logged_in(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        text = ""
    return not any(keyword in text for keyword in LOGIN_KEYWORDS)


def is_logged_in(page) -> bool:
    page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    return current_page_logged_in(page)


def save_screenshot(page, screenshot: str | None) -> str | None:
    path = ensure_parent(screenshot)
    if path:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    return None


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


def resolve_upload_input(page):
    selectors = [
        "input[type='file']",
        "div[class^='container'] input",
        "div[class*='upload'] input[type='file']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError("upload input not found")


def wait_for_publish_page(page, timeout_ms: int) -> None:
    deadline = time.time() + max(8.0, timeout_ms / 1000)
    while time.time() < deadline:
        dismiss_known_overlays(page)
        url = page.url
        if any(url.startswith(prefix) for prefix in DOUYIN_PUBLISH_URL_PREFIXES):
            return
        if page.locator("text=作品标题").count():
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("timed out waiting for Douyin publish page")


def resolve_title_input(page):
    selectors = [
        "input[placeholder='填写作品标题，为作品获得更多流量']",
        "input[placeholder*='作品标题']",
        "input[placeholder*='填写作品标题']",
        "input[placeholder*='输入标题']",
        ".semi-input-wrapper input.semi-input",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    try:
        by_text = page.get_by_text("作品标题").locator("..").locator("xpath=following-sibling::div[1]").locator("input").first
        if by_text.count():
            return by_text
    except Exception:
        pass
    candidates = [item for item in visible_editable_candidates(page) if item.evaluate("el => !el.isContentEditable")]
    if candidates:
        return candidates[0]
    raise RuntimeError("Douyin title input not found")


def resolve_content_editor(page):
    selectors = [
        "div.zone-container[data-slate-editor='true']",
        "div[data-slate-editor='true'][contenteditable='true']",
        ".zone-container",
        "div[contenteditable='true']",
        "textarea[placeholder*='简介']",
        "div.public-DraftEditor-content",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    candidates = visible_editable_candidates(page)
    if len(candidates) >= 2:
        return candidates[-1]
    if candidates:
        return candidates[0]
    raise RuntimeError("Douyin content editor not found")


def wait_for_upload_complete(page, timeout_ms: int) -> str | None:
    deadline = time.time() + max(20.0, timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.locator("text=重新上传").count():
                return "reupload_visible"
            if page.locator("text=上传失败").count():
                raise RuntimeError("Douyin video upload failed")
            if page.get_by_role("button", name="发布", exact=True).count():
                return "publish_ready"
        except Exception as exc:
            if "failed" in str(exc).lower():
                raise
        page.wait_for_timeout(1500)
    raise RuntimeError("timed out waiting for Douyin upload to complete")


def fill_title_content_tags(page, title: str, content: str, tags: list[str]) -> None:
    dismiss_known_overlays(page)
    title_input = resolve_title_input(page)
    title_input.click()
    title_input.fill("")
    title_input.fill(title[:30])

    editor = resolve_content_editor(page)
    plain_content = content.strip()
    if plain_content:
        fill_editor(editor, plain_content)
        page.wait_for_timeout(500)

    for tag in [item.strip().lstrip("#") for item in tags if item.strip()]:
        editor.click()
        page.keyboard.type(f"#{tag}")
        page.keyboard.press("Space")
        page.wait_for_timeout(350)


def set_thumbnail(page, thumbnail_path: str | None) -> bool:
    if not thumbnail_path:
        return False
    if not click_button_by_text(page, "选择封面"):
        return False
    try:
        page.locator("div.dy-creator-content-modal").first.wait_for(state="visible", timeout=10000)
    except Exception:
        return False
    click_button_by_text(page, "设置竖封面")
    page.wait_for_timeout(1500)
    selectors = [
        "div[class*='upload'] input[type='file']",
        "input.semi-upload-hidden-input",
        "input[type='file']",
    ]
    uploaded = False
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            if locator.count():
                locator.set_input_files(thumbnail_path)
                uploaded = True
                break
        except Exception:
            continue
    if not uploaded:
        return False
    page.wait_for_timeout(2000)
    if not click_button_by_text(page, "完成"):
        return False
    page.wait_for_timeout(1500)
    return True


def wait_for_publish_button(page) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            button = page.get_by_role("button", name="发布", exact=True).first
            if button.count() and button.is_visible():
                return
        except Exception:
            pass
        page.wait_for_timeout(800)
    raise RuntimeError("Douyin publish button not found")


def click_publish(page) -> None:
    button = page.get_by_role("button", name="发布", exact=True).first
    button.click()


def verify_publish(page, timeout_ms: int) -> dict[str, Any]:
    deadline = time.time() + max(8.0, timeout_ms / 1000)
    while time.time() < deadline:
        url = page.url
        if url.startswith(DOUYIN_MANAGE_URL_PREFIX):
            return {"verified": True, "signal": "manage_url"}
        if page.locator("text=发布成功").count():
            return {"verified": True, "signal": "success_text"}
        page.wait_for_timeout(1000)
    return {"verified": False, "signal": None}


def fetch_manage_summary(page) -> dict[str, Any]:
    page.goto(f"{DOUYIN_MANAGE_URL_PREFIX}?enter_from=publish", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    body = page.locator("body").inner_text(timeout=5000)
    match = re.search(r"共\\s*(\\d+)\\s*个作品", body)
    return {
        "count": int(match.group(1)) if match else None,
        "body": body,
        "url": page.url,
    }


def verify_publish_in_manage(page, timeout_ms: int, title: str, previous_count: int | None) -> dict[str, Any]:
    deadline = time.time() + max(12.0, timeout_ms / 1000)
    normalized_title = title.strip()
    while time.time() < deadline:
        summary = fetch_manage_summary(page)
        count = summary["count"]
        body = summary["body"]
        if normalized_title and normalized_title in body:
            return {
                "verified": True,
                "signal": "manage_title",
                "manage_count": count,
                "manage_url": summary["url"],
            }
        if previous_count is not None and count is not None and count > previous_count:
            return {
                "verified": True,
                "signal": "manage_count_increased",
                "manage_count": count,
                "manage_url": summary["url"],
            }
        page.wait_for_timeout(1500)
    return {
        "verified": False,
        "signal": None,
        "manage_count": None,
        "manage_url": page.url,
    }


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
        video_path = downloader.download_video(args.video_url)
        return validate_file(video_path, "video"), str(downloader.temp_dir)
    return validate_file(args.video, "video"), None


def resolve_thumbnail_input(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.thumbnail and args.thumbnail_url:
        raise ValueError("use only one of --thumbnail or --thumbnail-url")
    downloader: MediaDownloader | None = None
    if args.thumbnail_url:
        downloader = MediaDownloader()
        image_path = downloader.download_image(args.thumbnail_url)
        return validate_file(image_path, "thumbnail"), str(downloader.temp_dir)
    if args.thumbnail:
        return validate_file(args.thumbnail, "thumbnail"), None
    return None, None


def cleanup_download_dir(path_str: str | None) -> None:
    if not path_str:
        return
    try:
        import shutil

        shutil.rmtree(path_str, ignore_errors=True)
    except Exception:
        pass


def run_login(page, args: argparse.Namespace) -> dict[str, Any]:
    page.goto(DOUYIN_CREATOR_HOME, wait_until="domcontentloaded")
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
        raise RuntimeError("Douyin profile is not logged in. Run login first.")
    before_manage = fetch_manage_summary(page)
    video_path, video_tmp = resolve_video_input(args)
    thumb_path, thumb_tmp = resolve_thumbnail_input(args)
    try:
        page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        resolve_upload_input(page).set_input_files(video_path)
        wait_for_publish_page(page, args.timeout_ms)
        fill_title_content_tags(page, args.title, args.content, args.tag)
        upload_signal = wait_for_upload_complete(page, args.timeout_ms)
        thumbnail_applied = set_thumbnail(page, thumb_path)
        wait_for_publish_button(page)
        save_screenshot(page, args.screenshot)
        verification = {"verified": False, "signal": None, "manage_count": before_manage["count"], "manage_url": None}
        if args.publish:
            click_publish(page)
            page.wait_for_timeout(2000)
            if args.verify_publish:
                verification = verify_publish_in_manage(page, args.timeout_ms, args.title, before_manage["count"])
                save_screenshot(page, args.screenshot)
        return {
            "ok": True,
            "action": "publish-video",
            "published": bool(args.publish),
            "verified_publish": verification["verified"],
            "publish_signal": verification["signal"],
            "upload_signal": upload_signal,
            "thumbnail_applied": thumbnail_applied,
            "final_url": page.url,
            "manage_count_before": before_manage["count"],
            "manage_count_after": verification.get("manage_count"),
            "video": video_path,
            "thumbnail": thumb_path,
            "tags": args.tag,
            "screenshot": args.screenshot,
        }
    finally:
        cleanup_download_dir(video_tmp)
        cleanup_download_dir(thumb_tmp)


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
        payload.update(
            {
                "browser": meta.get("browser_name"),
                "profile_dir": meta.get("profile_dir"),
                "account": args.account,
            }
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "action": getattr(args, "command", "unknown"),
            "error": str(exc),
        }
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
