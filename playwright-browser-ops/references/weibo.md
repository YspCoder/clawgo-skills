# Weibo Integration

This skill includes a Weibo publishing script built on top of Playwright and persistent browser profiles.

Current scope:

- Persistent login with a local browser profile directory
- `login` for manual sign-in
- `check-login` for session validation
- `publish-text` for text-only posts
- `publish-images` for text plus local or remote images
- Preview mode by default, with explicit `--publish` required for a real post
- Real-tested text publishing on the live Weibo home page

Recommended usage:

```bash
python3 scripts/weibo_ops.py --account main login
python3 scripts/weibo_ops.py --account main check-login
python3 scripts/weibo_ops.py --account main publish-text \
  --content "测试微博正文"
python3 scripts/weibo_ops.py --account main publish-images \
  --content "测试微博图文正文" \
  --images /abs/path/1.jpg /abs/path/2.jpg \
  --publish \
  --verify-publish
```

Notes:

- This first version is Playwright-first because no equally strong, maintained public publish implementation surfaced during research.
- The current live home-page composer uses `发送` as the primary submit button, so automation should match `发送` before falling back to `发布`.
- `login` intentionally keeps the browser open until the configured wait period ends, even after sign-in succeeds.
- Current publish verification uses visible success text such as `发送成功` or `发布成功`.
- The next iteration should add stronger feed-level verification after posting and finish live-testing the image-post flow.
