# Douyin Integration

This skill includes an initial Douyin creator-center publishing script built on top of Playwright and persistent browser profiles.

Current scope:

- Persistent login with a local browser profile directory
- `login` for QR sign-in
- `check-login` for creator upload-page validation
- `publish-video` for local or remote video upload
- Optional local or remote thumbnail upload
- Title, description content, and repeatable `--tag` topic input
- Preview mode by default, with explicit `--publish` required for a real publish

Recommended usage:

```bash
python3 scripts/douyin_ops.py --account main login
python3 scripts/douyin_ops.py --account main check-login
python3 scripts/douyin_ops.py --account main publish-video \
  --title "标题" \
  --content "简介正文" \
  --tag 自动化 \
  --tag 测试 \
  --video /abs/path/demo.mp4
python3 scripts/douyin_ops.py --account main publish-video \
  --title "标题" \
  --content "简介正文" \
  --tag 自动化 \
  --video-url "https://example.com/demo.mp4" \
  --thumbnail-url "https://example.com/cover.jpg" \
  --publish \
  --verify-publish
```

Notes:

- This version uses a persistent browser profile rather than a separate cookie JSON file layout.
- The script targets Douyin creator center upload flows seen in public Playwright implementations and tolerates both older and newer publish URLs.
- The next iteration should add scheduled publish, product-link support, and more robust cover handling.

Source references checked during development:

- `dreammis/social-auto-upload`: https://github.com/dreammis/social-auto-upload
- `kebenxiaoming/matrix`: https://github.com/kebenxiaoming/matrix
