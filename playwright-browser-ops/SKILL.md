---
name: playwright-browser-ops
description: Run bundled Python Playwright scripts to open sites, perform default browser actions, dismiss common blockers, fill forms, click through repeatable UI steps, capture screenshots, and report results. Use when an agent or automation system needs browser work handled through a local Python script rather than a product-specific browser integration.
---

# Playwright Browser Ops

Use the bundled Python script as the primary execution path.

## Workflow

1. Clarify the target outcome, starting URL, and any required account state.
2. Use `scripts/default_ops.py` unless the task clearly needs a different script.
3. Pass only the options needed for the requested workflow.
4. Review the script output JSON and any screenshot artifacts.
5. Stop and report when the workflow hits credentials, MFA, CAPTCHA, payment, or destructive confirmation not explicitly authorized by the user.

This skill is intentionally product-agnostic:

- Any agent that can read files and run Python can use it.
- The browser logic lives in the script, not in a vendor-specific tool wrapper.
- Integrate it by invoking the script and consuming its JSON output.

## Script Entry Point

Primary script:

- `scripts/default_ops.py`
- `scripts/xiaohongshu_ops.py` for Xiaohongshu-specific login and publishing flows
- `scripts/bilibili_ops.py` for Bilibili login state and video publishing through `biliup`
- `scripts/douyin_ops.py` for Douyin creator-center login and video publishing through Playwright
- `scripts/browser_manager.py` for named accounts, isolated browser profiles, and tracked browser instances
- `scripts/media_downloader.py` for downloading remote images or videos before browser upload

Basic usage:

```bash
python3 scripts/default_ops.py --url https://example.com
python3 scripts/default_ops.py --url https://example.com --dismiss-overlays --screenshot output/example.png
python3 scripts/default_ops.py --url https://example.com --wait-for-text "Welcome" --extract-text "h1"
python3 scripts/browser_manager.py add-account main --browser chromium --debug-port 9222 --set-default
python3 scripts/browser_manager.py launch --account main
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser list-feeds --limit 5
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser search-feeds --keyword "春招" --limit 5
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser profile-snapshot --user-id USER_ID
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser content-data --page-num 1 --page-size 10 --type 0
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser get-feed-detail --feed-id FEED_ID --xsec-token TOKEN
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser post-comment-to-feed --feed-id FEED_ID --xsec-token TOKEN --content "写得很实用"
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser check-login
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser publish-images --title "标题" --content "正文" --images /abs/path/1.jpg /abs/path/2.jpg
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser publish-text-image --title "标题" --content $'正文第一段\n正文第二段\n#标签A #标签B' --publish --verify-publish
python3 scripts/bilibili_ops.py --account main login
python3 scripts/bilibili_ops.py --account main publish-video --title "标题" --content "简介" --tag 自动化 --video /abs/path/demo.mp4
python3 scripts/douyin_ops.py --account main login
python3 scripts/douyin_ops.py --account main publish-video --title "标题" --content "简介" --tag 自动化 --video /abs/path/demo.mp4
```

Environment requirements:

- Python 3.9+
- `playwright` package installed in the runtime
- Browser binaries installed with `python3 -m playwright install`
- `requests` package installed when workflows need remote media download
- `biliup` package installed when workflows need Bilibili upload support

## Default Operations

For vague requests such as "open the site and do the usual setup", run the baseline script flow:

1. Resize to a normal desktop viewport if layout matters.
2. Navigate to the requested URL.
3. Wait for the main page text or a stable load state.
4. Dismiss cookie banners, newsletter modals, or location popups if they block interaction.
5. Capture a screenshot or extracted text when the task needs proof.
6. Stop and report if the page requires credentials, MFA, payment, or destructive confirmation that the user did not explicitly authorize.

Use the reference file [references/default-operations.md](references/default-operations.md) for reusable flow patterns.

## Interaction Rules

- Do not invent credentials, verification codes, or account data.
- Do not submit destructive actions unless the user explicitly asked for them.
- Confirm state changes with visible text, URL changes, or screenshots.
- Extend the script instead of improvising long ad hoc one-off shell snippets.
- Keep the user informed when the browser reaches a blocker such as login, CAPTCHA, consent, or broken UI.

## Common Patterns

- Site bootstrap: open page, dismiss blockers, verify landing state.
- Visibility check: wait for text, inspect URL, capture screenshot.
- Lightweight extraction: read heading text or a selector value from the loaded page.
- Script extension: add selectors or steps to `scripts/default_ops.py` when the default flags are not enough.
- Platform integration: add product-specific scripts such as `scripts/xiaohongshu_ops.py` while keeping the base skill generic.

## Cross-Platform Publish Rules

- Keep real publishing opt-in with explicit `--publish`.
- Prefer persistent profiles or account-scoped cookie files so manual login survives across runs.
- When a login flow produces a QR image path, return it and show that image to the user instead of only describing it in text.
- For publish verification, prefer second-order checks such as creator-manage lists,稿件列表, or object counts over simple post-click URL changes.

## Xiaohongshu Text-Image Notes

- `publish-text-image` is for Xiaohongshu's `文字配图` flow in creator center.
- The generated text-image cards must not include `#话题` lines.
- Hashtags stay only in the final publish form content after image generation returns to the main editor.
- The script pauses before and after `再写一张` so each card receives its own text instead of collapsing into the first card.
- On the preview-theme step, the script picks one visible template from the right-side theme list before clicking `下一步`.
- After returning to the publish form, the script fills title and content again so the final post metadata stays complete.

## References

- Default operation recipes: [references/default-operations.md](references/default-operations.md)
- Bilibili integration notes: [references/bilibili.md](references/bilibili.md)
- Douyin integration notes: [references/douyin.md](references/douyin.md)
- Xiaohongshu integration notes: [references/xiaohongshu.md](references/xiaohongshu.md)
- Platform expansion research: [references/platform-expansion-research.md](references/platform-expansion-research.md)
