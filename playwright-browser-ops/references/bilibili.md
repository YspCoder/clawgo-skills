# Bilibili Integration

This skill includes an initial Bilibili publishing wrapper built around the public `biliup` uploader CLI.

Current scope:

- Account-scoped cookie storage under `tmp/bilibili/<account>/cookies.json`
- `login` to run `biliup login`
- `login` uses a PTY-backed `biliup login` flow and saves `qrcode.png` under the account runtime directory when QR login is selected
- `check-login` to verify whether a usable cookie file exists
- `publish-video` to upload a local or remote video through `biliup upload`
- Optional local or remote cover image support
- Preview mode by default, with explicit `--publish` required for a real upload

Recommended usage:

```bash
python3 scripts/bilibili_ops.py --account main login
python3 scripts/bilibili_ops.py --account main check-login
python3 scripts/bilibili_ops.py --account main publish-video \
  --title "标题" \
  --content "简介" \
  --tag 动态测试 \
  --tag 自动化 \
  --video /abs/path/demo.mp4
python3 scripts/bilibili_ops.py --account main publish-video \
  --title "标题" \
  --content "简介" \
  --tag 动态测试 \
  --video-url "https://example.com/demo.mp4" \
  --cover-url "https://example.com/cover.jpg" \
  --publish
```

Notes:

- This first version uses `biliup` instead of a Playwright-driven Bilibili creator upload page.
- Install dependency with `python3 -m pip install biliup`.
- The script preserves the same explicit-publish pattern used elsewhere in this skill: no real upload happens without `--publish`.
- During login, the returned JSON may include `qrcode_path`, which should be shown to the user when QR scanning is needed.
- The next iteration should add a browser-based fallback uploader when `biliup` is unavailable or insufficient.

Source references checked during development:

- `biliup` uploader project: https://github.com/biliup/biliup-rs
- `ytb2bili`: https://github.com/difyz9/ytb2bili
