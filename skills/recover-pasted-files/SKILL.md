---
name: recover-pasted-files
description: Recover an image or file the user pasted into the Claude Code chat as a real file on disk. Use when the user asks to save, attach, extract, or get a file they pasted, or when a task needs the pasted image as a file (e.g. attaching a screenshot to a GitHub issue/PR).
user-invocable: true
argument-hint: "[output-dir]"
---

# Recover Pasted Files

When the user pastes an image into the Claude Code chat, it is **not** written to a temp file and is **not** in `~/.claude/paste-cache/` (that directory holds pasted *text* only). The image is embedded as a base64 content block in the current session transcript `.jsonl`:

```json
{"type":"image","source":{"type":"base64","media_type":"image/png","data":"<base64>"}}
```

## Steps

1. **Find the transcript path.** The `SessionStart`/`UserPromptSubmit` hook prints it every turn:

   > The transcript for this session is stored at: `/Users/tjdsneto/.claude/projects/<slug>/<session-id>.jsonl`

   If it is not in view, derive it: `~/.claude/projects/<cwd-slugged>/<session-id>.jsonl`, where the slug is the cwd with `/` and `.` replaced by `-`. Pick the newest `.jsonl` in that dir for the current session id if unsure.

2. **Extract the pasted image(s).** Recurse the whole message tree so the block is found wherever it nests:

   ```bash
   TRANSCRIPT="/Users/tjdsneto/.claude/projects/<slug>/<session-id>.jsonl"
   OUT="./tmp"   # or the user-supplied output dir
   mkdir -p "$OUT"

   # single most-recent pasted image
   jq -r '.. | objects | select(.type?=="image") | .source.data' "$TRANSCRIPT" \
     | tail -1 | base64 -d > "$OUT/pasted.png"

   file "$OUT/pasted.png"   # confirm it decoded to a valid image
   ```

   - `tail -1` grabs the most recently pasted image; `head -1` grabs the first. Drop both and loop to extract all of them.
   - Read `media_type` (`image/png`, `image/jpeg`, `image/webp`, …) to choose the right extension when it is not PNG.
   - The base64 blob makes one very long line in the `.jsonl` (hundreds of KB) — that line is the image.

3. **Verify** with `file` that the output is a valid image before handing it back.

## Gotchas

- A plain `grep 'data:image'` on the transcript finds **nothing** — it is an Anthropic image content block, not a `data:` URL. Use the `jq` recursion above.
- `~/.claude/paste-cache/` is a red herring for images (pasted text only).
- **GitHub attach caveat:** `gh` has no attach flag and cannot upload an image to an issue/PR. For a **private** repo, a committed raw `githubusercontent.com` URL will not render for other viewers (it needs auth). The reliable path is to drag-drop the recovered file into the issue/PR on github.com.
