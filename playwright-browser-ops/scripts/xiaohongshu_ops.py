#!/usr/bin/env python3
"""Run Xiaohongshu creator-center flows with Playwright.

Selectors and workflow are adapted from the MIT-licensed project:
https://github.com/white0dew/XiaohongshuSkills
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlencode
from pathlib import Path
from typing import Any

from media_downloader import MediaDownloader


XHS_HOME_URL = "https://www.xiaohongshu.com"
XHS_CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"
XHS_CONTENT_DATA_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result"
XHS_NOTIFICATION_URL = "https://www.xiaohongshu.com/notification"
XHS_LOGIN_KEYWORDS = (
    "登录后推荐更懂你的笔记",
    "扫码登录",
    "登录",
)
SELECTORS = {
    "image_text_tab_text": "上传图文",
    "video_tab_text": "上传视频",
    "upload_input": ".upload-input",
    "upload_input_alt": 'input[type="file"]',
    "title_input": "div.d-input input",
    "title_input_alt": 'input[placeholder*="填写标题"], input[placeholder*="标题"], input.d-text',
    "content_editor": "div.tiptap.ProseMirror",
    "content_editor_alt": 'div.ProseMirror[contenteditable="true"]',
    "content_editor_alt2": "div.ql-editor",
    "publish_button": ".publish-page-publish-btn button.bg-red",
    "publish_button_text": "发布",
    "schedule_publish_button_text": "定时发布",
    "success_link": 'a[href*="xiaohongshu.com/explore"]',
    "like_button": "button:has-text('赞'), [class*='like']",
    "bookmark_button": "button:has-text('收藏'), [class*='collect'], [class*='bookmark']",
    "comment_input": "div.input-box div.content-edit, div.input-box [contenteditable='true'], div.input-box",
    "comment_submit": "div.bottom button.submit, div.bottom button[class*='submit'], button.submit, button[type='submit']",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--account", help="Named browser/account profile managed by browser_manager.py")
    parser.add_argument("--launch-managed-browser", action="store_true", help="Launch or reuse a tracked browser instance from browser_manager.py and connect via CDP")
    parser.add_argument("--keep-browser-open", action="store_true", help="When using --launch-managed-browser, leave the tracked browser process running after the command")
    parser.add_argument(
        "--profile-dir",
        default=str(Path(__file__).resolve().parent.parent / "tmp" / "xhs-profile"),
        help="Persistent browser profile directory",
    )
    parser.add_argument("--timeout-ms", type=int, default=20000, help="Action timeout in milliseconds")
    parser.add_argument("--screenshot", help="Optional screenshot path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Open Xiaohongshu and wait for manual QR login")
    login.add_argument("--wait-seconds", type=int, default=120, help="How long to keep the browser open for manual login")
    subparsers.add_parser("check-login", help="Check whether the persistent profile is logged in")

    list_home = subparsers.add_parser("list-feeds", help="List home recommendation feeds")
    list_home.add_argument("--limit", type=int, default=10, help="Max number of feeds to return")

    search = subparsers.add_parser("search-feeds", help="Search Xiaohongshu notes by keyword")
    search.add_argument("--keyword", required=True, help="Search keyword")
    search.add_argument("--limit", type=int, default=10, help="Max number of feeds to return")

    profile = subparsers.add_parser("profile-snapshot", help="Read a user profile snapshot")
    add_profile_target_args(profile)

    profile_notes = subparsers.add_parser("notes-from-profile", help="List notes from a user profile page")
    add_profile_target_args(profile_notes)
    profile_notes.add_argument("--limit", type=int, default=20, help="Max number of notes to return")
    profile_notes.add_argument("--max-scrolls", type=int, default=3, help="How many scroll rounds to attempt")

    mentions = subparsers.add_parser("get-notification-mentions", help="Fetch the notification mentions payload from the logged-in page")
    mentions.add_argument("--num", type=int, default=20, help="How many mentions to request")

    content_data = subparsers.add_parser("content-data", help="Fetch creator content metrics table")
    content_data.add_argument("--page-num", type=int, default=1, help="Page number, starting from 1")
    content_data.add_argument("--page-size", type=int, default=10, help="Rows per page")
    content_data.add_argument("--type", type=int, default=0, help="Creator API note type filter")

    detail = subparsers.add_parser("get-feed-detail", help="Open a note detail page and extract the visible state")
    detail.add_argument("--feed-id", required=True, help="Feed id")
    detail.add_argument("--xsec-token", required=True, help="xsec token")

    upvote = subparsers.add_parser("note-upvote", help="Like a note")
    add_note_target_args(upvote)

    unvote = subparsers.add_parser("note-unvote", help="Remove like from a note")
    add_note_target_args(unvote)

    bookmark = subparsers.add_parser("note-bookmark", help="Bookmark a note")
    add_note_target_args(bookmark)

    unbookmark = subparsers.add_parser("note-unbookmark", help="Remove bookmark from a note")
    add_note_target_args(unbookmark)

    comment = subparsers.add_parser("post-comment-to-feed", help="Post a top-level comment to a note")
    add_note_target_args(comment)
    comment.add_argument("--content", required=True, help="Comment content")

    reply = subparsers.add_parser("respond-comment", help="Reply to a matched comment in a note")
    add_note_target_args(reply)
    reply.add_argument("--content", required=True, help="Reply content")
    reply.add_argument("--comment-id", help="Comment id to match")
    reply.add_argument("--comment-author", help="Comment author name to match")
    reply.add_argument("--comment-snippet", help="Substring from comment content to match")

    images = subparsers.add_parser("publish-images", help="Publish or preview an image post")
    add_publish_args(images)
    images.add_argument("--images", nargs="*", default=[], help="Local image paths")
    images.add_argument("--image-urls", nargs="*", default=[], help="Remote image URLs to download before upload")

    video = subparsers.add_parser("publish-video", help="Publish or preview a video post")
    add_publish_args(video)
    video.add_argument("--video", help="Local video path")
    video.add_argument("--video-url", help="Remote video URL to download before upload")

    return parser


def add_publish_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", required=True, help="Post title")
    parser.add_argument("--content", required=True, help="Post content")
    parser.add_argument("--publish", action="store_true", help="Actually click publish")
    parser.add_argument("--verify-publish", action="store_true", help="After publish, wait for a visible success signal and extract the note link if possible")


def add_note_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--feed-id", required=True, help="Feed id")
    parser.add_argument("--xsec-token", required=True, help="xsec token")


def add_profile_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile-url", help="Explicit profile URL")
    parser.add_argument("--user-id", help="User id to open as https://www.xiaohongshu.com/user/profile/<id>")


def ensure_parent(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright package is not installed. Run: python3 -m pip install playwright && python3 -m playwright install"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


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


def resolve_profile_settings(args: argparse.Namespace) -> tuple[str, str, int | None]:
    if not args.account:
        return args.browser, str(Path(args.profile_dir).expanduser().resolve()), None
    payload = run_manager_command("resolve-profile", "--account", args.account)
    return payload["browser"], payload["profile_dir"], int(payload["debug_port"])


def attach_to_managed_browser(args: argparse.Namespace):
    sync_playwright, _ = get_playwright()
    if not args.account:
        raise RuntimeError("--launch-managed-browser requires --account")

    payload = run_manager_command("resolve-instance", "--account", args.account)
    browser_name = payload["browser"]
    profile_dir = payload["profile_dir"]
    debug_port = int(payload["debug_port"])
    if browser_name not in {"chromium", "chrome"}:
        raise RuntimeError("managed browser reuse is only supported for chromium-based browsers")

    if not payload["running"]:
        launch_args = ["launch", "--account", args.account]
        if args.headless:
            launch_args.append("--headless")
        launch_payload = run_manager_command(*launch_args)
        debug_port = int(launch_payload["instance"]["port"])
    playwright_cm = sync_playwright()
    playwright = playwright_cm.__enter__()
    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
    context = browser.contexts[0] if browser.contexts else browser.new_context(viewport={"width": 1440, "height": 900})
    context.set_default_timeout(args.timeout_ms)
    page = context.pages[0] if context.pages else context.new_page()
    meta = {
        "managed": True,
        "browser_name": browser_name,
        "profile_dir": profile_dir,
        "debug_port": debug_port,
        "browser": browser,
    }
    return playwright_cm, context, page, meta


def launch_context(args: argparse.Namespace):
    if args.launch_managed_browser:
        playwright_cm, context, page, meta = attach_to_managed_browser(args)
        return playwright_cm, context, page, meta

    sync_playwright, _ = get_playwright()
    browser_name, profile_dir, debug_port = resolve_profile_settings(args)
    playwright_cm = sync_playwright()
    playwright = playwright_cm.__enter__()
    browser_type = getattr(playwright, browser_name)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    context = browser_type.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=args.headless,
        viewport={"width": 1440, "height": 900},
    )
    context.set_default_timeout(args.timeout_ms)
    page = context.pages[0] if context.pages else context.new_page()
    meta = {
        "managed": False,
        "browser_name": browser_name,
        "profile_dir": profile_dir,
        "debug_port": debug_port,
        "browser": None,
    }
    return playwright_cm, context, page, meta


def is_logged_in(page) -> bool:
    page.goto(XHS_HOME_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    text = page.locator("body").inner_text(timeout=5000)
    return not any(keyword in text for keyword in XHS_LOGIN_KEYWORDS)


def save_screenshot(page, screenshot: str | None) -> str | None:
    path = ensure_parent(screenshot)
    if path:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    return None


def click_tab_by_text(page, text: str) -> None:
    page.get_by_text(text, exact=False).first.click()
    page.wait_for_timeout(1200)


def resolve_upload_input(page):
    for selector in (SELECTORS["upload_input"], SELECTORS["upload_input_alt"]):
        locator = page.locator(selector).first
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError("upload input not found")


def resolve_title_input(page):
    for selector in (SELECTORS["title_input"], SELECTORS["title_input_alt"]):
        locator = page.locator(selector).first
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError("title input not found")


def resolve_content_editor(page):
    for selector in (
        SELECTORS["content_editor"],
        SELECTORS["content_editor_alt"],
        SELECTORS["content_editor_alt2"],
    ):
        locator = page.locator(selector).first
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError("content editor not found")


def fill_editor(locator, content: str) -> None:
    locator.click()
    locator.evaluate(
        """(el, value) => {
            el.focus();
            if (el.isContentEditable) {
                el.innerHTML = "";
                const lines = String(value).split("\\n");
                for (const line of lines) {
                    const p = document.createElement("p");
                    p.textContent = line || "";
                    el.appendChild(p);
                }
                el.dispatchEvent(new Event("input", { bubbles: true }));
                return;
            }
            el.value = value;
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
        }""",
        content,
    )


def wait_for_publish_button(page) -> None:
    try:
        page.locator(SELECTORS["publish_button"]).first.wait_for(state="visible", timeout=20000)
        return
    except Exception:
        pass
    page.get_by_role("button", name=SELECTORS["publish_button_text"]).first.wait_for(state="visible", timeout=20000)


def click_publish(page) -> None:
    try:
        page.locator(SELECTORS["publish_button"]).first.click()
        return
    except Exception:
        pass
    for label in (SELECTORS["publish_button_text"], SELECTORS["schedule_publish_button_text"]):
        try:
            page.get_by_role("button", name=label).first.click()
            return
        except Exception:
            continue
    raise RuntimeError("publish button not found")


def validate_files(paths: list[str]) -> list[str]:
    resolved = [str(Path(path).expanduser().resolve()) for path in paths]
    missing = [path for path in resolved if not os.path.isfile(path)]
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
    return validate_files(local_images), downloader.temp_dir.as_posix() if downloader else None


def resolve_video_input(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.video and args.video_url:
        raise ValueError("use only one of --video or --video-url")
    downloader: MediaDownloader | None = None
    if args.video_url:
        downloader = MediaDownloader()
        video_path = downloader.download_video(args.video_url)
        return validate_files([video_path])[0], downloader.temp_dir.as_posix()
    if not args.video:
        raise ValueError("provide one of --video or --video-url")
    return validate_files([args.video])[0], None


def cleanup_download_dir(path_str: str | None) -> None:
    if not path_str:
        return
    try:
        import shutil

        shutil.rmtree(path_str, ignore_errors=True)
    except Exception:
        pass


def make_search_url(keyword: str) -> str:
    if not keyword.strip():
        raise ValueError("keyword cannot be empty")
    return f"{XHS_SEARCH_URL}?{urlencode({'keyword': keyword.strip(), 'source': 'web_explore_feed'})}"


def make_feed_detail_url(feed_id: str, xsec_token: str) -> str:
    feed_id = feed_id.strip()
    xsec_token = xsec_token.strip()
    if not feed_id or not xsec_token:
        raise ValueError("feed_id and xsec_token are required")
    return f"https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}&xsec_source=pc_feed"


def resolve_profile_url(profile_url: str | None, user_id: str | None) -> str:
    if profile_url:
        return profile_url.strip()
    if user_id:
        return f"https://www.xiaohongshu.com/user/profile/{user_id.strip()}"
    raise ValueError("provide either --profile-url or --user-id")


def wait_for_initial_state(page, expr: str, timeout_ms: int) -> None:
    deadline = time.time() + max(3.0, timeout_ms / 1000)
    while time.time() < deadline:
        try:
            ready = page.evaluate(expr)
            if ready:
                return
        except Exception:
            pass
        time.sleep(0.6)
    raise RuntimeError("timed out waiting for Xiaohongshu page data")


def extract_search_feeds(page, limit: int) -> list[dict[str, Any]]:
    data = page.evaluate(
        """(limit) => {
            const state = window.__INITIAL_STATE__;
            const feeds = state?.search?.feeds || [];
            const pick = feeds.slice(0, limit);
            return pick.map((item) => {
                const note = item?.noteCard || item;
                const user = note?.user || note?.author || {};
                const interact = note?.interactInfo || {};
                return {
                    id: note?.id || note?.noteId || item?.id || "",
                    xsec_token: note?.xsecToken || item?.xsecToken || "",
                    title: note?.displayTitle || note?.title || "",
                    type: note?.type || note?.noteType || "",
                    author: user?.nickname || user?.name || "",
                    user_id: user?.userId || user?.id || "",
                    liked_count: interact?.likedCount ?? interact?.likeCount ?? null,
                    cover: note?.cover?.urlDefault || note?.cover?.url || note?.imageList?.[0]?.urlDefault || "",
                };
            });
        }""",
        limit,
    )
    return data if isinstance(data, list) else []


def extract_home_feeds(page, limit: int) -> list[dict[str, Any]]:
    data = page.evaluate(
        """(limit) => {
            const state = window.__INITIAL_STATE__;
            const feeds = state?.feed?.feeds || [];
            return feeds.slice(0, limit).map((item) => {
                const note = item?.note || item?.noteCard || item;
                const user = note?.user || item?.user || {};
                const interact = note?.interactInfo || {};
                return {
                    id: note?.id || note?.noteId || item?.id || "",
                    xsec_token: note?.xsecToken || item?.xsecToken || "",
                    title: note?.displayTitle || note?.title || "",
                    type: note?.type || note?.noteType || "",
                    author: user?.nickname || user?.name || "",
                    user_id: user?.userId || user?.id || "",
                    liked_count: interact?.likedCount ?? interact?.likeCount ?? null,
                    cover: note?.cover?.urlDefault || note?.cover?.url || note?.imageList?.[0]?.urlDefault || "",
                };
            });
        }""",
        limit,
    )
    return data if isinstance(data, list) else []


def extract_feed_detail(page, feed_id: str) -> dict[str, Any]:
    detail = page.evaluate(
        """(feedId) => {
            const state = window.__INITIAL_STATE__;
            const detailMap = state?.note?.noteDetailMap || {};
            const noteEntry = detailMap[feedId] || Object.values(detailMap)[0] || {};
            const note = noteEntry?.note || noteEntry;
            const user = note?.user || {};
            const interact = note?.interactInfo || {};
            const comments = (note?.comments || []).slice(0, 10).map((comment) => ({
                id: comment?.id || "",
                user_name: comment?.userInfo?.nickname || "",
                content: comment?.content || "",
                like_count: comment?.likeCount ?? null,
            }));
            return {
                id: note?.id || feedId,
                title: note?.title || "",
                desc: note?.desc || note?.content || "",
                type: note?.type || "",
                author: user?.nickname || "",
                user_id: user?.userId || user?.id || "",
                liked_count: interact?.likedCount ?? interact?.likeCount ?? null,
                collected_count: interact?.collectedCount ?? interact?.collectCount ?? null,
                comment_count: interact?.commentCount ?? null,
                share_count: interact?.shareCount ?? null,
                comments,
                current_url: location.href,
            };
        }""",
        feed_id,
    )
    return detail if isinstance(detail, dict) else {}


def extract_profile_snapshot(page) -> dict[str, Any]:
    data = page.evaluate(
        """() => {
            const normalize = (text) => (text || "").replace(/\\s+/g, " ").trim();
            const state = window.__INITIAL_STATE__ || {};
            const getByKeys = (obj, keys) => {
                if (!obj || typeof obj !== "object") return null;
                for (const key of keys) {
                    const value = obj[key];
                    if (value !== undefined && value !== null && String(value).trim()) return value;
                }
                return null;
            };
            const queue = [state];
            const seen = new Set();
            let userNode = null;
            let count = 0;
            while (queue.length && count < 2400) {
                count += 1;
                const node = queue.shift();
                if (!node || typeof node !== "object" || seen.has(node)) continue;
                seen.add(node);
                if (!Array.isArray(node)) {
                    const idVal = getByKeys(node, ["userId", "user_id", "userid", "uid", "redId"]);
                    const nameVal = getByKeys(node, ["nickname", "nickName", "name", "userName", "username"]);
                    const avatarVal = getByKeys(node, ["avatar", "avatarUrl", "headUrl", "image"]);
                    if (nameVal && (idVal || avatarVal)) {
                        userNode = node;
                        break;
                    }
                }
                const values = Array.isArray(node) ? node : Object.values(node).slice(0, 120);
                for (const value of values) {
                    if (value && typeof value === "object") queue.push(value);
                }
            }
            const nameNode = document.querySelector("h1, [class*='name'], [class*='nickname'], [class*='user-name']");
            const bioNode = document.querySelector("[class*='desc'], [class*='bio'], [class*='signature'], [class*='intro']");
            return {
                url: location.href,
                page_title: document.title || "",
                profile: {
                    user_id: getByKeys(userNode, ["userId", "user_id", "userid", "uid", "redId"]),
                    nickname: getByKeys(userNode, ["nickname", "nickName", "name", "userName", "username"]) || normalize(nameNode?.textContent || ""),
                    avatar: getByKeys(userNode, ["avatar", "avatarUrl", "headUrl", "image"]) || "",
                    desc: getByKeys(userNode, ["desc", "description", "bio", "signature", "introduction"]) || normalize(bioNode?.textContent || ""),
                    followers: getByKeys(userNode, ["fans", "fansCount", "followerCount", "followers", "fans_count"]),
                    following: getByKeys(userNode, ["follows", "followCount", "followingCount", "following"]),
                    liked: getByKeys(userNode, ["likes", "likedCount", "totalLikes", "likeCount", "like_count"]),
                },
            };
        }"""
    )
    return data if isinstance(data, dict) else {}


def extract_profile_notes(page, limit: int) -> list[dict[str, Any]]:
    data = page.evaluate(
        """(limit) => {
            const normalize = (text) => (text || "").replace(/\\s+/g, " ").trim();
            const toAbs = (href) => {
                try { return new URL(href, location.href).href; } catch { return ""; }
            };
            const parseLink = (href) => {
                const abs = toAbs(href);
                if (!abs) return null;
                const parsed = new URL(abs);
                const match = parsed.pathname.match(/\\/(?:explore|discovery\\/item)\\/([0-9a-zA-Z]{24})/);
                if (!match) return null;
                return { id: match[1], xsec_token: parsed.searchParams.get("xsec_token") || "", url: parsed.toString() };
            };
            const links = document.querySelectorAll("a[href*='/explore/'], a[href*='/discovery/item/']");
            const seen = new Set();
            const notes = [];
            for (const link of links) {
                if (!(link instanceof HTMLAnchorElement)) continue;
                const parsed = parseLink(link.getAttribute("href") || link.href || "");
                if (!parsed || seen.has(parsed.id)) continue;
                seen.add(parsed.id);
                const card = link.closest("[class*='note-item'], [class*='card'], [class*='cover'], li, article, div") || link;
                const titleNode = card.querySelector("[class*='title'], [class*='name'], h3, h2, img[alt]");
                const coverNode = card.querySelector("img");
                notes.push({
                    id: parsed.id,
                    xsec_token: parsed.xsec_token,
                    note_url: parsed.url,
                    title: normalize((titleNode && (titleNode.getAttribute("alt") || titleNode.textContent)) || link.getAttribute("title") || link.textContent),
                    cover: coverNode instanceof HTMLImageElement ? coverNode.src : "",
                });
                if (notes.length >= limit) break;
            }
            return notes;
        }""",
        limit,
    )
    return data if isinstance(data, list) else []


def fetch_notification_mentions(page, num: int) -> dict[str, Any]:
    data = page.evaluate(
        """async (num) => {
            const url = `https://edith.xiaohongshu.com/api/sns/web/v1/you/mentions?num=${encodeURIComponent(num)}&cursor=`;
            const response = await fetch(url, {
                method: "GET",
                credentials: "include",
                headers: { "Accept": "application/json, text/plain, */*" },
            });
            const payload = await response.json();
            const body = payload?.data || {};
            const items = body.message_list || body.items || body.mentions || body.list || [];
            return {
                request_url: url,
                ok: response.ok,
                status: response.status,
                count: Array.isArray(items) ? items.length : 0,
                has_more: body.has_more ?? null,
                cursor: body.cursor ?? null,
                items: Array.isArray(items) ? items : [],
                raw_payload: payload,
            };
        }""",
        num,
    )
    return data if isinstance(data, dict) else {}


def format_post_time(post_time_ms: Any) -> str:
    if not isinstance(post_time_ms, (int, float)):
        return "-"
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(post_time_ms / 1000, tz=ZoneInfo("Asia/Shanghai"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def metric_or_dash(note: dict[str, Any], field: str) -> Any:
    value = note.get(field)
    return "-" if value is None else value


def format_cover_click_rate(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    normalized = value * 100 if 0 <= value <= 1 else value
    return f"{normalized:.2f}%"


def format_view_time_avg(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{int(value)}s"


def map_note_infos_to_content_rows(note_infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for note in note_infos:
        rows.append(
            {
                "标题": note.get("title") or "-",
                "发布时间": format_post_time(note.get("post_time")),
                "曝光": metric_or_dash(note, "imp_count"),
                "观看": metric_or_dash(note, "read_count"),
                "封面点击率": format_cover_click_rate(note.get("coverClickRate")),
                "点赞": metric_or_dash(note, "like_count"),
                "评论": metric_or_dash(note, "comment_count"),
                "收藏": metric_or_dash(note, "fav_count"),
                "涨粉": metric_or_dash(note, "increase_fans_count"),
                "分享": metric_or_dash(note, "share_count"),
                "人均观看时长": format_view_time_avg(note.get("view_time_avg")),
                "弹幕": metric_or_dash(note, "danmaku_count"),
                "操作": "详情数据",
                "_id": note.get("id") or "",
            }
        )
    return rows


def fetch_content_data(page, page_num: int, page_size: int, note_type: int) -> dict[str, Any]:
    payload = page.evaluate(
        """async ({ pageNum, pageSize, noteType }) => {
            const url = "https://creator.xiaohongshu.com/api/galaxy/creator/datacenter/note/analyze/list";
            const response = await fetch(url, {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json;charset=UTF-8",
                    "Accept": "application/json, text/plain, */*",
                },
                body: JSON.stringify({
                    page_num: pageNum,
                    page_size: pageSize,
                    type: noteType,
                }),
            });
            const json = await response.json();
            return {
                ok: response.ok,
                status: response.status,
                request_url: url,
                payload: json,
            };
        }""",
        {"pageNum": page_num, "pageSize": page_size, "noteType": note_type},
    )
    return payload if isinstance(payload, dict) else {}


def find_comment_candidates(page) -> list[dict[str, Any]]:
    data = page.evaluate(
        """() => {
            const normalize = (text) => (text || "").replace(/\\s+/g, " ").trim();
            const nodes = Array.from(document.querySelectorAll("div, li, article"));
            const results = [];
            for (const node of nodes) {
                if (!(node instanceof HTMLElement) || node.offsetParent === null) continue;
                const text = normalize(node.innerText || node.textContent || "");
                if (!text || text.length < 2) continue;
                const replyButton = Array.from(node.querySelectorAll("button, span, a")).find((el) => {
                    const value = normalize(el.textContent || "");
                    return value === "回复" || value.startsWith("回复");
                });
                if (!replyButton) continue;
                const id = node.getAttribute("data-rid") || node.getAttribute("data-id") || node.id || "";
                const userEl = node.querySelector("[class*='author'], [class*='user'], .name");
                const author = normalize(userEl?.textContent || "");
                const replyText = normalize(replyButton.textContent || "");
                results.push({
                    id,
                    author,
                    text,
                    reply_text: replyText,
                });
            }
            return results.slice(0, 50);
        }"""
    )
    return data if isinstance(data, list) else []


def open_note_detail(page, feed_id: str, xsec_token: str) -> str:
    url = make_feed_detail_url(feed_id, xsec_token)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    return url


def get_button_state(locator) -> dict[str, Any]:
    classes = ""
    text = ""
    pressed = None
    try:
        classes = locator.get_attribute("class") or ""
    except Exception:
        pass
    try:
        text = locator.inner_text(timeout=1000).strip()
    except Exception:
        pass
    try:
        pressed = locator.get_attribute("aria-pressed")
    except Exception:
        pass
    return {"class": classes, "text": text, "aria_pressed": pressed}


def resolve_action_button(page, action: str):
    action_map = {
        "like": [
            page.get_by_role("button", name="赞").first,
            page.locator("[class*='like']").first,
        ],
        "bookmark": [
            page.get_by_role("button", name="收藏").first,
            page.locator("[class*='collect'], [class*='bookmark']").first,
        ],
    }
    for locator in action_map[action]:
        try:
            if locator.count():
                return locator
        except Exception:
            continue
    raise RuntimeError(f"{action} button not found")


def toggle_note_action(page, feed_id: str, xsec_token: str, action: str, expected_active: bool) -> dict[str, Any]:
    open_note_detail(page, feed_id, xsec_token)
    button = resolve_action_button(page, action)
    before = get_button_state(button)
    button.click()
    page.wait_for_timeout(1500)
    after = get_button_state(button)
    state_text = f"{after['text']} {after['class']}".lower()
    inferred_active = expected_active
    if action == "like":
        if any(token in state_text for token in ("已赞", "liked", "active")) or after["aria_pressed"] == "true":
            inferred_active = True
        if any(token in state_text for token in ("赞", "like")) and not any(token in state_text for token in ("已赞", "liked", "active")) and after["aria_pressed"] != "true":
            inferred_active = False
    if action == "bookmark":
        if any(token in state_text for token in ("已收藏", "collected", "active")) or after["aria_pressed"] == "true":
            inferred_active = True
        if any(token in state_text for token in ("收藏", "bookmark")) and not any(token in state_text for token in ("已收藏", "collected", "active")) and after["aria_pressed"] != "true":
            inferred_active = False
    return {
        "ok": inferred_active == expected_active,
        "action": action,
        "expected_active": expected_active,
        "active": inferred_active,
        "before": before,
        "after": after,
        "final_url": page.url,
    }


def fill_comment_input(page, content: str) -> int:
    locator = page.locator(SELECTORS["comment_input"]).first
    locator.wait_for(state="visible", timeout=10000)
    locator.click()
    locator.evaluate(
        """(el, value) => {
            const text = String(value);
            el.focus();
            if (el.isContentEditable) {
                el.innerHTML = "";
                const p = document.createElement("p");
                p.textContent = text;
                el.appendChild(p);
                el.dispatchEvent(new Event("input", { bubbles: true }));
                return;
            }
            if ("value" in el) {
                el.value = text;
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }
        }""",
        content,
    )
    return len(content.strip())


def submit_comment(page) -> None:
    try:
        page.locator(SELECTORS["comment_submit"]).first.click()
        return
    except Exception:
        pass
    for label in ("发送", "提交", "评论", "回复"):
        try:
            page.get_by_role("button", name=label).first.click()
            return
        except Exception:
            continue
    raise RuntimeError("comment submit button not found")


def wait_comment_signal(page, timeout_ms: int) -> bool:
    deadline = time.time() + max(3.0, timeout_ms / 1000)
    while time.time() < deadline:
        try:
            body = page.locator("body").inner_text(timeout=1200)
            if any(token in body for token in ("评论成功", "回复成功", "发送成功")):
                return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


def match_comment(candidates: list[dict[str, Any]], comment_id: str | None, author: str | None, snippet: str | None) -> dict[str, Any]:
    filtered = candidates
    if comment_id:
        filtered = [item for item in filtered if item.get("id") == comment_id]
    if author:
        filtered = [item for item in filtered if author in (item.get("author") or "")]
    if snippet:
        filtered = [item for item in filtered if snippet in (item.get("text") or "")]
    if not filtered:
        raise RuntimeError("target comment not found")
    return filtered[0]


def click_reply_for_comment(page, target: dict[str, Any]) -> None:
    comment_id = target.get("id") or ""
    author = target.get("author") or ""
    text = target.get("text") or ""
    clicked = page.evaluate(
        """(target) => {
            const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
            const nodes = Array.from(document.querySelectorAll("div, li, article"));
            for (const node of nodes) {
                if (!(node instanceof HTMLElement) || node.offsetParent === null) continue;
                const nodeId = node.getAttribute("data-rid") || node.getAttribute("data-id") || node.id || "";
                const nodeText = normalize(node.innerText || node.textContent || "");
                if (target.id && nodeId !== target.id) continue;
                if (target.author && !nodeText.includes(target.author)) continue;
                if (target.text && !nodeText.includes(target.text.slice(0, Math.min(12, target.text.length)))) continue;
                const replyButton = Array.from(node.querySelectorAll("button, span, a")).find((el) => {
                    const value = normalize(el.textContent || "");
                    return value === "回复" || value.startsWith("回复");
                });
                if (replyButton) {
                    replyButton.click();
                    return true;
                }
            }
            return false;
        }""",
        {"id": comment_id, "author": author, "text": text},
    )
    if not clicked:
        raise RuntimeError("reply trigger not found for target comment")
    page.wait_for_timeout(800)


def extract_note_link(page) -> str | None:
    try:
        link = page.locator(SELECTORS["success_link"]).first
        if link.count():
            href = link.get_attribute("href")
            if href:
                return href
    except Exception:
        pass
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
        import re

        match = re.search(r"\b[0-9a-fA-F]{24}\b", body_text)
        if match:
            return f"https://www.xiaohongshu.com/explore/{match.group(0)}"
    except Exception:
        pass
    return None


def verify_publish_result(page, timeout_ms: int) -> dict[str, Any]:
    deadline = time.time() + max(3.0, timeout_ms / 1000)
    last_url = page.url
    while time.time() < deadline:
        note_link = extract_note_link(page)
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=1500)
        except Exception:
            pass
        if note_link:
            return {"verified": True, "note_link": note_link, "signal": "note_link"}
        if any(token in body_text for token in ("发布成功", "笔记发布成功", "已发布", "发布完成")):
            return {"verified": True, "note_link": note_link, "signal": "success_text"}
        if page.url != last_url and "publish" not in page.url:
            return {"verified": True, "note_link": note_link, "signal": "url_changed"}
        time.sleep(1.0)
    return {"verified": False, "note_link": extract_note_link(page), "signal": None}


def run_login(page, args: argparse.Namespace) -> dict[str, Any]:
    page.goto(XHS_HOME_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    save_screenshot(page, args.screenshot)
    deadline = time.time() + max(1, args.wait_seconds)
    logged_in = is_logged_in(page)
    while time.time() < deadline and not logged_in:
        time.sleep(2)
        try:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
        except Exception:
            pass
        logged_in = is_logged_in(page)
    return {
        "ok": True,
        "action": "login",
        "logged_in": logged_in,
        "message": "Login window was kept open for manual QR scan.",
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_check_login(page, args: argparse.Namespace) -> dict[str, Any]:
    logged_in = is_logged_in(page)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "check-login",
        "logged_in": logged_in,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_list_feeds(page, args: argparse.Namespace) -> dict[str, Any]:
    page.goto(XHS_HOME_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    wait_for_initial_state(page, "() => !!(window.__INITIAL_STATE__ && window.__INITIAL_STATE__.feed && window.__INITIAL_STATE__.feed.feeds)", args.timeout_ms)
    feeds = extract_home_feeds(page, args.limit)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "list-feeds",
        "count": len(feeds),
        "feeds": feeds,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_search_feeds(page, args: argparse.Namespace) -> dict[str, Any]:
    url = make_search_url(args.keyword)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    wait_for_initial_state(page, "() => !!(window.__INITIAL_STATE__ && window.__INITIAL_STATE__.search && window.__INITIAL_STATE__.search.feeds)", args.timeout_ms)
    feeds = extract_search_feeds(page, args.limit)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "search-feeds",
        "keyword": args.keyword,
        "count": len(feeds),
        "feeds": feeds,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_profile_snapshot(page, args: argparse.Namespace) -> dict[str, Any]:
    url = resolve_profile_url(args.profile_url, args.user_id)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    snapshot = extract_profile_snapshot(page)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "profile-snapshot",
        "snapshot": snapshot,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_notes_from_profile(page, args: argparse.Namespace) -> dict[str, Any]:
    url = resolve_profile_url(args.profile_url, args.user_id)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    notes: list[dict[str, Any]] = []
    for _ in range(max(1, args.max_scrolls)):
        notes = extract_profile_notes(page, args.limit)
        if len(notes) >= args.limit:
            break
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(1200)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "notes-from-profile",
        "count": len(notes),
        "notes": notes[: args.limit],
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_get_notification_mentions(page, args: argparse.Namespace) -> dict[str, Any]:
    page.goto(XHS_NOTIFICATION_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    payload = fetch_notification_mentions(page, args.num)
    save_screenshot(page, args.screenshot)
    return {
        "ok": bool(payload.get("ok", True)),
        "action": "get-notification-mentions",
        "count": payload.get("count"),
        "has_more": payload.get("has_more"),
        "cursor": payload.get("cursor"),
        "items": payload.get("items"),
        "request_url": payload.get("request_url"),
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_content_data(page, args: argparse.Namespace) -> dict[str, Any]:
    if args.page_num < 1:
        raise RuntimeError("--page-num must be >= 1")
    if args.page_size < 1:
        raise RuntimeError("--page-size must be >= 1")
    page.goto(XHS_CONTENT_DATA_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    fetched = fetch_content_data(page, args.page_num, args.page_size, args.type)
    payload = fetched.get("payload") or {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    note_infos = data.get("note_infos") if isinstance(data, dict) else []
    note_infos = note_infos if isinstance(note_infos, list) else []
    rows = map_note_infos_to_content_rows(note_infos)
    save_screenshot(page, args.screenshot)
    return {
        "ok": bool(fetched.get("ok", True)),
        "action": "content-data",
        "page_num": args.page_num,
        "page_size": args.page_size,
        "type": args.type,
        "count": len(rows),
        "rows": rows,
        "raw_payload": payload,
        "request_url": fetched.get("request_url"),
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_get_feed_detail(page, args: argparse.Namespace) -> dict[str, Any]:
    open_note_detail(page, args.feed_id, args.xsec_token)
    wait_for_initial_state(page, "() => !!(window.__INITIAL_STATE__ && window.__INITIAL_STATE__.note && window.__INITIAL_STATE__.note.noteDetailMap)", args.timeout_ms)
    detail = extract_feed_detail(page, args.feed_id)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "get-feed-detail",
        "detail": detail,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_note_upvote(page, args: argparse.Namespace) -> dict[str, Any]:
    result = toggle_note_action(page, args.feed_id, args.xsec_token, "like", True)
    save_screenshot(page, args.screenshot)
    result["action"] = "note-upvote"
    result["screenshot"] = args.screenshot
    return result


def run_note_unvote(page, args: argparse.Namespace) -> dict[str, Any]:
    result = toggle_note_action(page, args.feed_id, args.xsec_token, "like", False)
    save_screenshot(page, args.screenshot)
    result["action"] = "note-unvote"
    result["screenshot"] = args.screenshot
    return result


def run_note_bookmark(page, args: argparse.Namespace) -> dict[str, Any]:
    result = toggle_note_action(page, args.feed_id, args.xsec_token, "bookmark", True)
    save_screenshot(page, args.screenshot)
    result["action"] = "note-bookmark"
    result["screenshot"] = args.screenshot
    return result


def run_note_unbookmark(page, args: argparse.Namespace) -> dict[str, Any]:
    result = toggle_note_action(page, args.feed_id, args.xsec_token, "bookmark", False)
    save_screenshot(page, args.screenshot)
    result["action"] = "note-unbookmark"
    result["screenshot"] = args.screenshot
    return result


def run_post_comment_to_feed(page, args: argparse.Namespace) -> dict[str, Any]:
    open_note_detail(page, args.feed_id, args.xsec_token)
    content_length = fill_comment_input(page, args.content)
    submit_comment(page)
    success = wait_comment_signal(page, args.timeout_ms)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "post-comment-to-feed",
        "feed_id": args.feed_id,
        "content_length": content_length,
        "success_signal": success,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def run_respond_comment(page, args: argparse.Namespace) -> dict[str, Any]:
    if not any((args.comment_id, args.comment_author, args.comment_snippet)):
        raise RuntimeError("provide at least one of --comment-id, --comment-author, or --comment-snippet")
    open_note_detail(page, args.feed_id, args.xsec_token)
    candidates = find_comment_candidates(page)
    target = match_comment(candidates, args.comment_id, args.comment_author, args.comment_snippet)
    click_reply_for_comment(page, target)
    content_length = fill_comment_input(page, args.content)
    submit_comment(page)
    success = wait_comment_signal(page, args.timeout_ms)
    save_screenshot(page, args.screenshot)
    return {
        "ok": True,
        "action": "respond-comment",
        "feed_id": args.feed_id,
        "target_comment": target,
        "content_length": content_length,
        "success_signal": success,
        "final_url": page.url,
        "screenshot": args.screenshot,
    }


def navigate_creator(page) -> None:
    page.goto(XHS_CREATOR_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")


def run_publish_images(page, args: argparse.Namespace) -> dict[str, Any]:
    images, cleanup_dir = resolve_image_inputs(args)
    try:
        navigate_creator(page)
        click_tab_by_text(page, SELECTORS["image_text_tab_text"])
        resolve_upload_input(page).set_input_files(images)
        resolve_title_input(page).fill(args.title)
        fill_editor(resolve_content_editor(page), args.content)
        wait_for_publish_button(page)
        save_screenshot(page, args.screenshot)
        verification = {"verified": False, "note_link": None, "signal": None}
        if args.publish:
            click_publish(page)
            page.wait_for_timeout(2500)
            if args.verify_publish:
                verification = verify_publish_result(page, args.timeout_ms)
                save_screenshot(page, args.screenshot)
        return {
            "ok": True,
            "action": "publish-images",
            "published": bool(args.publish),
            "verified_publish": verification["verified"],
            "publish_signal": verification["signal"],
            "note_link": verification["note_link"],
            "final_url": page.url,
            "files": images,
            "screenshot": args.screenshot,
        }
    finally:
        cleanup_download_dir(cleanup_dir)


def run_publish_video(page, args: argparse.Namespace) -> dict[str, Any]:
    video, cleanup_dir = resolve_video_input(args)
    try:
        navigate_creator(page)
        click_tab_by_text(page, SELECTORS["video_tab_text"])
        resolve_upload_input(page).set_input_files(video)
        resolve_title_input(page).fill(args.title)
        fill_editor(resolve_content_editor(page), args.content)
        wait_for_publish_button(page)
        save_screenshot(page, args.screenshot)
        verification = {"verified": False, "note_link": None, "signal": None}
        if args.publish:
            click_publish(page)
            page.wait_for_timeout(2500)
            if args.verify_publish:
                verification = verify_publish_result(page, args.timeout_ms)
                save_screenshot(page, args.screenshot)
        return {
            "ok": True,
            "action": "publish-video",
            "published": bool(args.publish),
            "verified_publish": verification["verified"],
            "publish_signal": verification["signal"],
            "note_link": verification["note_link"],
            "final_url": page.url,
            "files": [video],
            "screenshot": args.screenshot,
        }
    finally:
        cleanup_download_dir(cleanup_dir)


def dispatch(page, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "login":
        return run_login(page, args)
    if args.command == "check-login":
        return run_check_login(page, args)
    if args.command == "list-feeds":
        return run_list_feeds(page, args)
    if args.command == "search-feeds":
        return run_search_feeds(page, args)
    if args.command == "profile-snapshot":
        return run_profile_snapshot(page, args)
    if args.command == "notes-from-profile":
        return run_notes_from_profile(page, args)
    if args.command == "get-notification-mentions":
        return run_get_notification_mentions(page, args)
    if args.command == "content-data":
        return run_content_data(page, args)
    if args.command == "get-feed-detail":
        return run_get_feed_detail(page, args)
    if args.command == "note-upvote":
        return run_note_upvote(page, args)
    if args.command == "note-unvote":
        return run_note_unvote(page, args)
    if args.command == "note-bookmark":
        return run_note_bookmark(page, args)
    if args.command == "note-unbookmark":
        return run_note_unbookmark(page, args)
    if args.command == "post-comment-to-feed":
        return run_post_comment_to_feed(page, args)
    if args.command == "respond-comment":
        return run_respond_comment(page, args)
    if args.command == "publish-images":
        return run_publish_images(page, args)
    if args.command == "publish-video":
        return run_publish_video(page, args)
    raise ValueError(f"unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result: dict[str, Any]

    try:
        playwright_cm, context, page, meta = launch_context(args)
    except Exception as exc:
        result = {
            "ok": False,
            "action": args.command,
            "error": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        result = dispatch(page, args)
        result["browser"] = meta["browser_name"]
        result["profile_dir"] = meta["profile_dir"]
        result["debug_port"] = meta["debug_port"]
        result["managed_browser"] = meta["managed"]
        result["account"] = args.account
    except Exception as exc:
        result = {
            "ok": False,
            "action": args.command,
            "final_url": getattr(page, "url", None),
            "error": str(exc),
            "account": args.account,
            "browser": meta["browser_name"],
            "profile_dir": meta["profile_dir"],
            "debug_port": meta["debug_port"],
            "managed_browser": meta["managed"],
        }
        save_screenshot(page, args.screenshot)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)
    finally:
        time.sleep(0.5)
        if meta["managed"]:
            try:
                if meta["browser"] is not None:
                    meta["browser"].close()
            except Exception:
                pass
        else:
            context.close()
        if not (meta["managed"] and args.keep_browser_open):
            playwright_cm.__exit__(None, None, None)
        else:
            playwright_cm.__exit__(None, None, None)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
