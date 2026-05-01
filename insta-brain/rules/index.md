# Rule index

Every rule below is mandatory. Click each link for full reasoning and edge cases. New rules go here first, then a file in this folder.

| # | Rule | Summary |
|---|---|---|
| [01](01-no-repost.md) | **No repost** | Never publish a fact already in `data/posted.jsonl`. Hash before generate. |
| [02](02-no-image-reuse.md) | **No image reuse** | Never publish an image already in `data/used_images.jsonl`. Both URL and content SHA. |
| [03](03-voice.md) | **Voice** | Direct, dry, British English. No em dashes. No filler. Banned phrases listed. |
| [04](04-visual-design.md) | **Visual design** | Locked palette, fonts, layout, accent rules. The brand kit is the source of truth. |
| [05](05-publishing.md) | **Publishing** | Instagram Graph API only. Rate limits and cap rules. Free-tier hosting only. |
| [06](06-data-capture.md) | **Data capture** | What gets written back to the brain after every run, by which file. |
| [07](07-tooling.md) | **Tooling** | What every script does, when to run it, and the canonical Python path. |
| [08](08-content-pipeline.md) | **Content pipeline** | The five-stage flow from idea to live post. |
| [09](09-prompt-read-order.md) | **Prompt read order** | The exact files an agent loads at session start. |
| [13](13-memory-index.md) | **Memory index discipline** | Every non-trivial change batch must be appended to `MEMORY_INDEX.md`. |
| [14](14-sensitivity.md) | **Sensitivity / controversy filter** | safe / edgy / controversial tiering. Autonomous queue is safe-only. Animal welfare, religion, politics, suicide specifics, etc gated. |
| [15](15-list-posts.md) | **List-format posts** | Curated themed packs (films/TV/etc) via TMDB. Each pack slug ships once, ever. ~1/week cadence, varied domain. |
| [16](16-no-spoilers.md) | **No spoilers** | List-post hooks should not give away third-act reveals or signature scenes. Cultural-knowledge twists are an allowed exception with restraint. |
| [17](17-dynamic-curation.md) | **Dynamic curation (meta)** | Rules are scaffolding, not handcuffs. Ships over polish. Trusts operator. Lists which rules are inviolate vs guidance. |
| [18](18-routine-sync.md) | **Routine sync** | Whenever code changes, update the affected Claude scheduled routines. What triggers an update, how to do it, enforcement. |
| [19](19_reels_strategy.md) | **Reels strategy** (LOCKED) | One Reel = one fact arc (hook→setup→escalation→twist→CTA). 18-28s, cuts every 1-2.2s, British male voice, single keyword emphasis per beat, scripted not transcribed. |

If a rule conflicts with another, the lower-numbered rule wins. If a rule conflicts with a higher-level CLAUDE.md, the higher-level file wins for personal/voice rules; rules here win for pipeline mechanics.

**Read rule 17 first.** It's the meta-rule about when to follow these literally vs trust judgment. Most rules below are guidance you can flex when the curation calls for it; only the named "inviolate" set must never bend.
