None of the 13 round-3 items has shipped yet, and only 3 are ready. That count comes from the live issue files; the table in your handoff is already out of date. The good news is that most of what's stuck is waiting on one item, 0178, which already passed review and has your approval.

**The 13 round-3 items, by state:**

| State | Items |
|---|---|
| Ready (3) | 0174 (loosen the craft rules; it had a failed review and is back with the worker), 0193 (critic on each cut, advice only), 0195 (crossfade option for build.py, the app-walkthrough renderer) |
| In review (3) | 0170 (a reviewer started at 14:12). 0175 and 0181 failed review and need another worker pass. 0181's new check also flags elements that correctly leave and come back, so following it would break good films. |
| Blocked (5) | 0171, 0172, 0173 and 0180 are blocked on 0178 (craft files out of `.claude/`). 0182 is blocked on you. |
| Backlog (2) | 0168 (TTS fallback), 0169 (third-party cost, which needs 0173 first) |

**Being worked on right now:** only the 0170 review. 0037, 0038 and 0039 say "in-progress", but nobody owns them. Their code merged on Nov 5 and they're waiting on one supervised verification run, so the label is misleading.

**What needs your judgment:**

1. **Shipping 0178 is the biggest lever.** It unblocks 0171, 0172, 0173, 0180 and 0174. It's approved, so it should be next in the shipper's queue. I'm confident about this.
2. **Not all 13 need to be done before round 3.** I'd split them:
   - **Gate for round 3 (they change the video):** 0171, 0172, 0174, 0175, 0180, 0181, 0182, 0195.
   - **Can land during or after the round (they change reporting):** 0168, 0169, 0170, 0173, 0193.

   I'm fairly sure of this split. The one I'm unsure of is 0173: if directors keep writing their own paid scripts, round 3 spends money we can't see.
3. **Voice is the risk nobody owns.** In round 2 ElevenLabs was out of quota, so all three voices fell back to Gemini or Kokoro, and you rated each one low quality. If we launch without checking the quota, the voices won't be comparable again. The shared workspace's reset date is still unknown.

**Items I'd consider adding before round 3:** 0149 (it's only a checklist to run on the round-3 cuts of 02, 03 and 09), a voice gate, and 0143 (Docker disk was 99% full on 11-25). 0079 (the single-shot director threw away real screen captures) only matters if the real-UI style is in round 3.

---
**Summary:** Of the 13 round-3 items, 0 have shipped and 3 are ready. Shipping 0178 unblocks five of them, and 0182 needs you. My suggestion is to start round 3 once the 8 items that change the video are done, not all 13, and to add a voice/quota check before launch.

**Next for you:**
- F1. *Round-3 prep › 0182 canon prompts.* Who applies the goal-only v2 prompts for styles 1–8 to `docs/lisa/canon-styles.md`? The worker drafted them in `.ana/tmp/worker/canon-next.md` but can't write that doc, because it's outside `repo/`. Four open points need your call either way:
  - style 2 says "users", not "businesses"
  - style 4 drops the AI assistant names
  - style 8's CTA URL isn't sourced
  - style 8 keeps "Shopify"

  Answer `me` (m) or `worker` (w). Recommended: `me`, because it's a one-file doc edit and the open points are yours regardless. Next: you answer the four points, then I apply the blocks, mark v1 superseded, add the changelog line and move 0182 to review. https://tjdsneto-macbook.tail6c2cf1.ts.net:8444/e/ib-7cu5
- F2. *Round-3 prep › Extra gate items.* Which of these go into the round-3 gate? Answer with any of `verify` (v, 0149, the frame-review checklist on the cuts), `voice` (o, an ElevenLabs quota check and a decision on the 0168 fallback), `disk` (d, 0143, a Docker disk check) or `realui` (r, 0079, only if that style runs). Recommended: `verify` + `voice` + `disk`, because they're cheap and cover what went wrong in round 2. Next: I add the ones you pick to 0134's round-3 gate and file the voice gate if you take it. https://tjdsneto-macbook.tail6c2cf1.ts.net:8444/e/ib-7q8b

**To hand off / do later:**
- F3. 0194 (high severity): since 0163 shipped, `./x` in any worktree loads the main checkout's database connection, so a migration run from a branch could hit the live database. It doesn't block round 3, but workers are active, so it should be triaged soon.
- F4. Re-label 0037/0038/0039 from in-progress to backlog or blocked so the board shows the truth.
