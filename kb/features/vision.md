# Vision — image input, auxiliary vision fallback, video.

## Image input
A user turn may carry `images: [{"media_type","data"(base64)}]`. `images.py`
builds them: `grab_clipboard_image()` (`kbcode/images.py:43`, via Pillow) or
`load_image_file(path)` (`kbcode/images.py:68`), downscaled to <=1568px PNG
(`_MAX_DIM`, `kbcode/images.py:27`). Chat input binds **Alt+V** to grab the clipboard
into a pending buffer (`kbcode/prompt_input.py:247` `_attach_image`); `repl.py` drains
it and calls `Agent.run(user, images=...)` (`kbcode/agent.py:248`) — the `images` key
is only added when non-empty, so non-vision turns are unaffected. Each
provider's `_to_native` expands an image-bearing message into its own vision
format (Anthropic image blocks, OpenAI `image_url` parts — see [[providers]]).
`compaction.estimate_tokens()` (`kbcode/compaction.py:49`) counts each image as a flat
~1300 tokens instead of its base64 length.

## Auxiliary vision fallback
`provider._classify()` recognizes the specific error a non-vision model/route
gives back for an image request and raises `ProviderError("...doesn't support
image input.")`. `Agent.run` catches exactly that and calls
`_try_vision_fallback` (`kbcode/agent.py:206`), which asks `vision_fallback
.describe_images()` (`kbcode/vision_fallback.py:131`) for a text description, rewrites
the pending message in place, and retries — so the image is described once and
never resent as bytes. `_candidates()` (`kbcode/vision_fallback.py:43`) builds an
**ordered** list, most-trusted first: (1) explicit `KBCODE_VISION_*` override,
(2) the active provider's own key *only if* its `base_url` is verifiably
`openrouter.ai` (some presets alias `key_env` to `OPENROUTER_API_KEY` while
`KBCODE_BASE_URL` points elsewhere — trusting the name alone would 401), (3)
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` in that order.
`available()` (`kbcode/vision_fallback.py:72`) is false only when no candidate exists.

## Video
No provider here has a native video content-part (Anthropic Messages API has
none at all), so `describe_video()` (`kbcode/vision_fallback.py:146`) skips
`kind=="anthropic"` candidates and always makes a raw OpenAI-compatible call
with a `video_url` part. `videos.load_video_file()` (`kbcode/videos.py:31`) base64s a
local file (<=30MB). `/video <path>` (chat, `kbcode/cli.py:357` `_describe_videos`) /
`--video` (one-shot, `_take_video`, `kbcode/cli.py:342`) call this synchronously; the description is
threaded into the next turn via `repl.py`'s `pending_notes` (`kbcode/repl.py:701`) —
the main model never sees raw video.

See [[providers]] for the retry/translation layer these routes reuse,
[[gotchas]] for the vision-error-detection trap.
