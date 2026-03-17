# Platform Expansion Research

Date checked: 2026-03-17

Goal: extend `playwright-browser-ops` beyond Xiaohongshu with practical publishing flows for Bilibili, Douyin, Kuaishou, and Weibo.

## Current Findings

### Bilibili

- `biliup/biliup-rs` is the strongest public uploader implementation found for Bilibili.
- It supports multiple login methods and direct command-line upload with title, description, cover, tags, and delayed publish fields.
- It is not Playwright-based, but it is much closer to a stable publishing backend than browser clicking.
- The searched `biliup-rs` repo is archived and points to a newer `biliup` repo, so we should target the actively maintained successor rather than the archived repository.

Recommended integration path:

1. Add `scripts/bilibili_ops.py`.
2. Support two modes:
   - native uploader mode via `biliup` CLI if installed
   - browser mode fallback later if needed
3. Keep the same JSON result contract used by `xiaohongshu_ops.py`.

### Douyin

- `dreammis/social-auto-upload` publicly claims support for Douyin, Bilibili, Xiaohongshu, Kuaishou, WeChat Channels, Baijiahao, and TikTok.
- Its documented flow is browser automation plus saved cookies and example uploader scripts such as `get_douyin_cookie.py` and `upload_video_to_douyin.py`.
- This is close to our current skill architecture because we already use Python plus Playwright plus persistent browser profiles.

Recommended integration path:

1. Read the Douyin uploader implementation from `social-auto-upload`.
2. Extract only the publish flow into `scripts/douyin_ops.py`.
3. Reuse our existing account/profile model instead of copying its cookie-file layout.

### Kuaishou

- `dreammis/social-auto-upload` also documents Kuaishou support and references cookie capture plus uploader scripts such as `get_ks_cookie.py`.
- This makes it the best public implementation candidate found for Kuaishou publishing in the current search pass.

Recommended integration path:

1. Read the Kuaishou uploader implementation from `social-auto-upload`.
2. Extract only the core publish actions into `scripts/kuaishou_ops.py`.
3. Keep login/profile/session handling aligned with `browser_manager.py`.

### Weibo

- No strong, maintained public browser-publishing implementation surfaced in this search pass.
- Most public code found for Weibo was older scraping, screenshot, or widget/API-oriented code rather than a robust creator publishing flow.
- This means Weibo is likely the highest custom-build cost among the four platforms.

Recommended integration path:

1. Build a Playwright-first flow ourselves after live page inspection.
2. Start with text/image posting only.
3. Leave richer drafting and media variations for later.

## Development Order

Recommended order:

1. Bilibili
2. Douyin
3. Kuaishou
4. Weibo

Reasoning:

- Bilibili already has a strong uploader ecosystem, so it is the fastest route to a stable first non-Xiaohongshu integration.
- Douyin and Kuaishou have public browser-automation references we can adapt into our current Playwright skill model.
- Weibo appears to require the most original implementation work.

## Source Links

- `dreammis/social-auto-upload`: https://github.com/dreammis/social-auto-upload
- `biliup/biliup-rs` archived uploader repo: https://github.com/biliup/biliup-rs
- `difyz9/ytb2bili`: https://github.com/difyz9/ytb2bili

## Notes For This Skill

- Do not copy large external projects wholesale into this repository.
- Prefer extracting minimal, platform-specific publishing flows into small Python entry scripts.
- Preserve one shared execution model:
  - persistent profile or managed browser
  - explicit `--publish`
  - optional `--verify-publish`
  - JSON output
