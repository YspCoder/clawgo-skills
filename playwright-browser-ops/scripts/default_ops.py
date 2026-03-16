#!/usr/bin/env python3
"""Run a minimal Playwright browser workflow and emit JSON results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


OVERLAY_SELECTORS = [
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button:has-text('Got it')",
    "button:has-text('Close')",
    "[aria-label='Close']",
    "[data-testid='close']",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Target page URL")
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--headless", action="store_true", help="Run without opening a visible window")
    parser.add_argument("--width", type=int, default=1440, help="Viewport width")
    parser.add_argument("--height", type=int, default=900, help="Viewport height")
    parser.add_argument("--timeout-ms", type=int, default=15000, help="Action timeout in milliseconds")
    parser.add_argument("--wait-for-text", help="Visible text that must appear before completion")
    parser.add_argument("--dismiss-overlays", action="store_true", help="Dismiss common popups and consent banners")
    parser.add_argument("--extract-text", help="Selector to read text from")
    parser.add_argument("--screenshot", help="Optional screenshot output path")
    return parser


def maybe_dismiss_overlays(page) -> list[str]:
    clicked: list[str] = []
    for selector in OVERLAY_SELECTORS:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=500):
                locator.click(timeout=1000)
                clicked.append(selector)
        except Exception:
            continue
    return clicked


def ensure_parent(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return {
            "ok": False,
            "url": args.url,
            "final_url": None,
            "title": None,
            "dismissed": [],
            "extracted_text": None,
            "screenshot": args.screenshot,
            "error": "playwright package is not installed. Run: python3 -m pip install playwright && python3 -m playwright install",
            "details": str(exc),
        }

    result: dict[str, Any] = {
        "ok": False,
        "url": args.url,
        "final_url": None,
        "title": None,
        "dismissed": [],
        "extracted_text": None,
        "screenshot": args.screenshot,
        "error": None,
    }

    with sync_playwright() as playwright:
        browser_launcher = getattr(playwright, args.browser)
        browser = browser_launcher.launch(headless=args.headless)
        context = browser.new_context(viewport={"width": args.width, "height": args.height})
        page = context.new_page()
        page.set_default_timeout(args.timeout_ms)

        try:
            page.goto(args.url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=args.timeout_ms)

            if args.dismiss_overlays:
                result["dismissed"] = maybe_dismiss_overlays(page)

            if args.wait_for_text:
                page.get_by_text(args.wait_for_text).first.wait_for(state="visible", timeout=args.timeout_ms)

            if args.extract_text:
                result["extracted_text"] = page.locator(args.extract_text).first.inner_text(timeout=args.timeout_ms).strip()

            screenshot_path = ensure_parent(args.screenshot)
            if screenshot_path:
                page.screenshot(path=str(screenshot_path), full_page=True)

            result["ok"] = True
            result["final_url"] = page.url
            result["title"] = page.title()
        except PlaywrightTimeoutError as exc:
            result["error"] = f"timeout: {exc}"
            result["final_url"] = page.url
        except Exception as exc:
            result["error"] = str(exc)
            result["final_url"] = page.url
        finally:
            context.close()
            browser.close()

    return result


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
