# Kuaishou Integration

This skill includes an initial Kuaishou creator publishing script built on top of Playwright and persistent browser profiles.

Current scope:

- Persistent login with a local browser profile directory
- `login` for QR sign-in
- `check-login` for creator publish-page validation
- `publish-video` for local or remote video upload
- Title, description content, and up to three repeatable `--tag` topic inputs
- Preview mode by default, with explicit `--publish` required for a real publish

Recommended usage:

```bash
python3 scripts/kuaishou_ops.py --account main login
python3 scripts/kuaishou_ops.py --account main check-login
python3 scripts/kuaishou_ops.py --account main publish-video \
  --title "标题" \
  --content "简介正文" \
  --tag 自动化 \
  --tag 测试 \
  --video /abs/path/demo.mp4
python3 scripts/kuaishou_ops.py --account main publish-video \
  --title "标题" \
  --content "简介正文" \
  --tag 自动化 \
  --video-url "https://example.com/demo.mp4" \
  --publish \
  --verify-publish
```

Notes:

- This version uses persistent browser profiles, aligned with the Xiaohongshu and Douyin scripts in this skill.
- A real publish validation has been run against the current creator page flow: after clicking publish, the script should verify the manage page shows `审核中` or `已发布` for the new item.
- The next iteration should add cover editing, better draft handling, and stronger publish verification in the manage list.

Source references checked during development:

- `dreammis/social-auto-upload`: https://github.com/dreammis/social-auto-upload
- `kebenxiaoming/matrix`: https://github.com/kebenxiaoming/matrix
