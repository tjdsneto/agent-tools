Workers are moving again. The autopilot picked up the misplaced mock-UI fix, the first round-3 item that changes the video, so the priority order is being followed.

Two things need you:

1. **Only one worker runs at a time.** With two agent slots, a reviewer or shipper usually holds one. Seven video-changing items each need a work run and a review, so at this pace they take most of the afternoon (F2). I'm fairly sure of the bottleneck; the afternoon estimate is a guess, since I haven't timed a run.
2. **The canon prompts are still waiting on you, not on the craft-files move.** The worker can't write the canon doc, because it lives outside the worker's repo, and four wording points are yours either way (F1).

One call I made myself: the per-line cost report failed review twice for the same missing server-side work, so I split the model, voice and owner columns into a new item. Veto in the [inbox](https://tjdsneto-macbook.tail6c2cf1.ts.net:8444/e/ib-mqhg).

---
**Summary:** The craft-files move shipped, but four items it should have freed were stuck: two were never sent back after failing review, and two still pointed at its deleted branch. All four are back with the worker, and the video-changing items now have top priority. Each item's hand-back note has the detail.

**Next for you:**
- F1. *Round-3 prep › Canon prompts.* Who applies the worker's rewritten prompts for styles 1–8 to the canon doc? The worker drafted them but can't write that doc, and four wording points need your call either way (they're listed in the inbox). Answer `me` (m) or `worker` (w). Recommended: `me`, because it's a one-file edit and the wording points are yours anyway. Next: you answer the four points, then I apply the draft and send it to review. https://tjdsneto-macbook.tail6c2cf1.ts.net:8444/e/ib-7cu5
- F2. *Round-3 prep › Worker throughput.* Raise the autopilot from two agent slots to three, so two workers can run at once? Workers test in their own worktrees, so a third slot costs CPU and spend, not contention for the main checkout. Answer `three` (t) or `keep` (k). Recommended: `three`, and back to two once the video-changing items are in review. Next: I raise the slot count in the project settings. https://tjdsneto-macbook.tail6c2cf1.ts.net:8444/e/ib-wnq3

+1 more waiting under this topic: https://tjdsneto-macbook.tail6c2cf1.ts.net:8444/topics#tp-z748

**To hand off / do later:**
- F3. The worktree database bug (0194: `./x` in a worktree reaches the live database) is ready but has no priority, so it waits behind round 3. Say if it should jump the queue.
