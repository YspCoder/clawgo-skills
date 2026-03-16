# Xiaohongshu Integration

This skill includes a Xiaohongshu-specific Playwright script derived from the workflow and selectors used by the open-source project [white0dew/XiaohongshuSkills](https://github.com/white0dew/XiaohongshuSkills).

Scope included here:

- Persistent login with a local browser profile directory
- Named account and multi-browser profile management
- Managed browser launch and reuse for Chromium accounts
- Login status checks
- Home recommendation feed listing
- Search notes by keyword
- Read note detail from feed id and xsec token
- Read profile snapshots
- List notes from profile pages
- Fetch notification mentions
- Fetch creator content data metrics
- Like/unlike notes
- Bookmark/unbookmark notes
- Post top-level comments
- Reply to matched comments
- Creator-center image post publishing
- Creator-center video post publishing
- Remote media download before upload
- Post-publish verification and note link extraction
- Preview mode by default, with explicit publish action only when requested

Key assumptions:

- Use a persistent browser profile so login survives across runs.
- Prefer headed mode for login and first-run debugging.
- Treat final publish as opt-in, not default.
- Expect creator-center selectors to change over time; update `scripts/xiaohongshu_ops.py` when Xiaohongshu changes the publish page DOM.

Basic commands:

```bash
python3 scripts/browser_manager.py add-account main --alias "主账号" --browser chromium --debug-port 9222 --set-default
python3 scripts/browser_manager.py add-account alt --alias "备用账号" --browser chromium --debug-port 9223
python3 scripts/browser_manager.py list-accounts
python3 scripts/browser_manager.py launch --account main
python3 scripts/browser_manager.py status
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser --keep-browser-open login
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser check-login
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser list-feeds --limit 5
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser search-feeds --keyword "春招" --limit 5
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser profile-snapshot --user-id USER_ID
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser notes-from-profile --user-id USER_ID --limit 10 --max-scrolls 3
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser get-notification-mentions --num 20
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser content-data --page-num 1 --page-size 10 --type 0
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser get-feed-detail --feed-id FEED_ID --xsec-token TOKEN
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser note-upvote --feed-id FEED_ID --xsec-token TOKEN
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser note-bookmark --feed-id FEED_ID --xsec-token TOKEN
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser post-comment-to-feed --feed-id FEED_ID --xsec-token TOKEN --content "写得很实用"
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser respond-comment --feed-id FEED_ID --xsec-token TOKEN --comment-author "某用户" --content "谢谢反馈"
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser publish-images --title "标题" --content "正文" --images /abs/path/1.jpg
python3 scripts/xiaohongshu_ops.py --account main --launch-managed-browser publish-images --title "标题" --content "正文" --image-urls "https://example.com/1.jpg" "https://example.com/2.jpg" --publish --verify-publish
python3 scripts/xiaohongshu_ops.py --account alt publish-video --title "标题" --content "正文" --video-url "https://example.com/demo.mp4" --publish --verify-publish
python3 scripts/xiaohongshu_ops.py --account alt publish-video --title "标题" --content "正文" --video /abs/path/demo.mp4
python3 scripts/browser_manager.py kill --account main
```

Recommended usage:

1. Create one named account per Xiaohongshu login identity with `browser_manager.py add-account`.
2. For Chromium accounts, optionally pre-launch a managed browser with `browser_manager.py launch --account ...`.
3. Run `login` in headed mode and complete QR login manually for that account profile.
4. Use `check-login` to verify the profile is still valid.
5. Use `list-feeds` for homepage recommendations and `search-feeds` to find candidate notes with `feed_id` plus `xsec_token`.
6. Use `profile-snapshot` and `notes-from-profile` when targeting a creator page rather than a search result.
7. Use `get-notification-mentions` to inspect recent comment and @ events from the logged-in account.
8. Use `content-data` to fetch creator performance rows from the data-analysis backend while logged in.
9. Use `get-feed-detail` before interaction if the target note needs verification.
10. Use `post-comment-to-feed` for top-level comments and `respond-comment` when you need targeted replies.
11. Run `publish-images` or `publish-video` with `--publish` only after the user confirms the final content.
12. Add `--verify-publish` when you need a stronger post-publish success check and note link extraction.
13. Save screenshots during preview or failure handling for debugging.
