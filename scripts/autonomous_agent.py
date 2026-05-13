"""Autonomous agent for the factjot Instagram account.

Sandboxed: the model has NO shell access and NO filesystem access. It
calls a small set of typed tools:

  - list_unposted_topics()  -> compact summary of recent posts (post bank)
  - run_reel(...)           -> compose + publish one reel
  - run_carousel(...)       -> compose + publish one carousel
                              (writer prompt switches by --type)
  - skip(reason)            -> abort this run cleanly with no post

The pipelines themselves (make_reel.py, ship_carousel_post.py) run with
full repo access in the host process. Only the model's view is restricted.

Three post modes via --post-mode (fixed daily sequence, cut from 5 slots
on 2026-05-10 per audit Q4 quality bet). Each mode exposes ONLY the tools
it needs and a sharpened, format-locked prompt:

  reel_morning   - 09:00 BST  evergreen reel (run_reel only)
  list_midday    - 14:00 BST  list carousel (run_carousel only)
  reel_night     - 20:30 BST  evergreen reel (run_reel only)

Better to skip a slot than ship a weak post. Each mode must call `skip`
with a one-line reason if nothing clears the quality gate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.brain import fingerprint_similarity, subject_fingerprint
from src.content.carousel_rules import (
    BEAT_DENSITY_RULES,
    PHOTOGRAPHABLE_BEATS_RULES,
)
from src.research.story_scout import (
    ranked_candidates_for_mode,
    build_list_reel_possibilities,
)

# Cap the agent loop to keep cost predictable when the carousel pipeline
# is failing repeatedly. A successful run typically uses 2-4 turns; 12
# was a worst-case ceiling that proved too generous - one bad run on
# 2026-05-08 burned $0.20 doing 9 retries before skipping. With cache
# warming the first turn, subsequent turns are cheap, but turns are also
# proportional to time and that delays the next slot.
MAX_TURNS = 6
MODEL     = "claude-sonnet-4-6"
HISTORY_LIMIT = 30

# Anthropic Sonnet 4.6 pricing (USD per million tokens, May 2026).
PRICE_INPUT_PER_M  = 3.00
PRICE_OUTPUT_PER_M = 15.00
# Prompt caching billing (5-minute ephemeral TTL):
#   write = 1.25x base input, read = 0.10x base input.
PRICE_CACHE_WRITE_PER_M = round(PRICE_INPUT_PER_M * 1.25, 4)
PRICE_CACHE_READ_PER_M  = round(PRICE_INPUT_PER_M * 0.10, 4)

REPO_ROOT        = Path(__file__).resolve().parent.parent
POSTED_LOG       = REPO_ROOT / "insta-brain" / "data" / "posted.jsonl"
REELS_LOG        = REPO_ROOT / "insta-brain" / "data" / "reels.jsonl"
SUBJECT_KEYS_LOG = REPO_ROOT / "insta-brain" / "data" / "subject_keys.jsonl"
COST_LEDGER      = REPO_ROOT / "data" / "ledgers" / "api_usage_costs.jsonl"

# Subject fingerprint dedup window. The 2026-05-06 incident shipped 8 near-
# duplicate "phone with no apps" carousels in 5 hours; 14 days is wide
# enough to catch a slow-burn repeat without forcing the agent to skip
# every legitimate cousin topic.
FINGERPRINT_WINDOW_DAYS = 14
FINGERPRINT_SIMILARITY_THRESHOLD = 0.6

SYSTEM = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).
    You have three typed tools and nothing else. You cannot read files,
    run shell commands, or inspect the repo. The project context you need
    is in this prompt.
    Be concise. British English. No em dashes.
""")

VALID_MODES = (
    "reel_morning",
    "list_midday",
    "reel_night",
)

# Which carousel writer prompt does this mode want?
# (run_reel modes are absent here.)
MODE_FORMAT_TYPE: dict[str, str] = {
    "list_midday": "list",
}

# Which tools is each mode allowed to call?
# Locked at the loadout level: tools not listed here are not even shown
# to the model. list_unposted_topics + skip are universal.
MODE_TOOLS: dict[str, tuple[str, ...]] = {
    "reel_morning": ("list_unposted_topics", "list_story_candidates", "run_reel", "skip"),
    "reel_night": ("list_unposted_topics", "list_story_candidates", "run_reel", "skip"),
    "list_midday": ("list_unposted_topics", "list_story_candidates", "run_carousel", "skip"),
}


# ------------------------------------------------------------------ #
# Posting history summary - the post bank the agent uses to dedupe
# ------------------------------------------------------------------ #

def _entry_subject_text(entry: dict) -> str:
    """Pick the best free-text field on a posted/reel entry to fingerprint.

    Reels store a real reel_title on top of the claim (the script body);
    posts store a slug-shaped claim like "manual:abc:five-biggest-mega-...".
    Fall back to keywords-after-colon for slugged claims so fingerprints
    survive even when claim is opaque.
    """
    reel_title = entry.get("reel_title") or ""
    if reel_title:
        return reel_title
    claim = entry.get("claim", "") or ""
    if claim.startswith(("manual:", "list:", "reel:")) and ":" in claim:
        # Slug shape - take the keywords tail after the last colon and
        # un-slug it.
        tail = claim.rsplit(":", 1)[-1]
        return tail.replace("-", " ").replace("_", " ")
    return claim


def _format_history_entry(entry: dict) -> str | None:
    """Return a richer one-line summary per post for duplicate detection.

    Format: `YYYY-MM-DD [format/CATEGORY] subject - keywords  fp=<fingerprint>`
    """
    date = (entry.get("published_at") or "")[:10]
    if not date:
        return None
    claim_field = entry.get("claim", "")
    category    = (entry.get("category") or "").upper()
    topic       = (entry.get("topic")    or "").lower()

    if category == "REEL":
        fmt = "reel"
    elif claim_field.startswith("list:"):
        fmt = "list"
    else:
        fmt = "carousel"

    label = topic.upper() if fmt == "reel" else (category or topic.upper() or "-")

    if fmt == "carousel" and ":" in claim_field:
        keywords = claim_field.rsplit(":", 1)[-1]
        keywords = keywords.replace("-", " ").replace("_", " ")
    elif fmt == "list" and ":" in claim_field:
        keywords = claim_field.split(":", 1)[-1].replace(":", " / ")
        keywords = keywords.replace("-", " ").replace("_", " ")
    else:
        snippet = claim_field if not claim_field.startswith(("manual:", "list:", "reel:")) else ""
        keywords = (snippet[:140] + "…") if len(snippet) > 140 else snippet
        keywords = keywords or entry.get("post_id") or "(no-keywords)"

    fp = subject_fingerprint(_entry_subject_text(entry))
    fp_tag = f"  fp={fp}" if fp else ""
    return f"- {date} [{fmt}/{label}] {keywords}{fp_tag}"


def _parse_published_at(raw: str) -> datetime | None:
    """Parse the `published_at` ISO string used by both posted.jsonl
    and reels.jsonl. Returns None on parse failure.
    """
    if not raw:
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iter_jsonl(path: Path):
    """Yield decoded rows from a .jsonl file, ignoring blank/bad lines."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_recent_fingerprints(
    *,
    window_days: int = FINGERPRINT_WINDOW_DAYS,
    now: datetime | None = None,
) -> list[tuple[str, str, str]]:
    """Return [(fingerprint, published_at_iso, subject_excerpt), ...] for
    posts within the last `window_days` across posted.jsonl + reels.jsonl.

    Empty-fingerprint entries are skipped. The list is deduplicated by
    fingerprint, keeping the most recent entry per fingerprint.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    seen: dict[str, tuple[str, str, str]] = {}
    for path in (POSTED_LOG, REELS_LOG):
        for row in _iter_jsonl(path):
            ts = _parse_published_at(row.get("published_at", ""))
            if ts is None or ts < cutoff:
                continue
            subject = _entry_subject_text(row)
            fp = subject_fingerprint(subject)
            if not fp:
                continue
            iso = row.get("published_at", "")
            excerpt = subject[:80].strip()
            existing = seen.get(fp)
            if existing is None or iso > existing[1]:
                seen[fp] = (fp, iso, excerpt)
    return list(seen.values())


def load_used_subject_keys() -> set[str]:
    """Return the set of all canonical subject keys ever posted."""
    keys: set[str] = set()
    if not SUBJECT_KEYS_LOG.exists():
        return keys
    with SUBJECT_KEYS_LOG.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                k = row.get("subject_key", "")
                if k:
                    keys.add(k.strip().lower())
            except json.JSONDecodeError:
                continue
    return keys


def _find_key_collision(candidate: str, used: set[str]) -> str | None:
    """Return a stored key that is too similar to `candidate`, or None.

    Jaccard on hyphen-split tokens at threshold 0.4. Catches near-variants
    like 'radium-girl' blocked by 'radium-girls'.
    """
    c_tokens = set(candidate.strip().lower().split("-")) - {""}
    if not c_tokens:
        return None
    for stored in used:
        s_tokens = set(stored.split("-")) - {""}
        if not s_tokens:
            continue
        union = c_tokens | s_tokens
        if union and len(c_tokens & s_tokens) / len(union) >= 0.7:
            return stored
    return None


def find_subject_collision(
    candidate_text: str,
    recent: list[tuple[str, str, str]],
    *,
    threshold: float = FINGERPRINT_SIMILARITY_THRESHOLD,
) -> tuple[str, str, str, float] | None:
    """If `candidate_text` collides with any entry in `recent`, return the
    matched (fingerprint, published_at_iso, subject_excerpt, similarity).
    Otherwise return None.

    Empty candidate fingerprint returns None (cannot characterise it).
    """
    cand_fp = subject_fingerprint(candidate_text)
    if not cand_fp:
        return None
    best: tuple[str, str, str, float] | None = None
    for fp, iso, excerpt in recent:
        sim = fingerprint_similarity(cand_fp, fp)
        if sim >= threshold and (best is None or sim > best[3]):
            best = (fp, iso, excerpt, sim)
    return best


def build_history_summary(limit: int = HISTORY_LIMIT) -> str:
    if not POSTED_LOG.exists() and not REELS_LOG.exists():
        return "(no posts yet)"

    # Merge posted.jsonl + reels.jsonl. Reels live in reels.jsonl with
    # `reel_title` populated (the subject identity); posted.jsonl mirrors
    # them but historically without that field, so reading both lets the
    # agent see correct title-based fingerprints. Dedupe by post_id and
    # sort by published_at so the most recent N posts are shown
    # regardless of which ledger they came from.
    merged: dict[str, dict] = {}
    for path in (POSTED_LOG, REELS_LOG):
        for row in _iter_jsonl(path):
            pid = row.get("post_id") or row.get("reel_id") or row.get("ig_media_id")
            if not pid:
                continue
            existing = merged.get(pid)
            if existing is None:
                merged[pid] = row
                continue
            # Prefer the row that carries reel_title; otherwise keep
            # whichever has the later published_at.
            if row.get("reel_title") and not existing.get("reel_title"):
                merged[pid] = {**existing, **row}
            elif (row.get("published_at") or "") > (existing.get("published_at") or ""):
                merged[pid] = {**existing, **row}
    entries = sorted(
        merged.values(),
        key=lambda r: r.get("published_at") or "",
    )
    recent = entries[-limit:]
    lines = [_format_history_entry(e) for e in recent]
    lines = [ln for ln in lines if ln]
    if not lines:
        return "(no posts yet)"
    header = (
        f"Last {len(lines)} posts (most recent at bottom). Use this to "
        "reject any candidate that overlaps a previous topic, angle, list "
        "idea, ranking, or subject, even when worded differently. The "
        "`fp=` token at the end of each line is the code-level subject "
        "fingerprint; if your candidate's longest content tokens overlap "
        f"any recent fingerprint by {int(FINGERPRINT_SIMILARITY_THRESHOLD * 100)}% or more, the dispatch "
        "will be rejected and you must skip or pick a different subject."
    )
    return header + "\n" + "\n".join(lines)


# ------------------------------------------------------------------ #
# Pipeline executors (the only things the agent can trigger)
# ------------------------------------------------------------------ #

def _run_pipeline(cmd: list[str]) -> str:
    """Run a pipeline subprocess and stream its output line-by-line.

    Streaming is critical for diagnosing hangs: if a pipeline gets stuck
    on a network call we want to see the last printed step in the
    GitHub Actions log immediately, not after the subprocess returns.
    """
    print(f"\n$ {' '.join(repr(c) if (' ' in c or len(c) > 80) else c for c in cmd)}", flush=True)
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(REPO_ROOT),
            bufsize=1,
        )
    except Exception as exc:
        return f"ERROR: failed to start pipeline: {exc}"

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            print(f"  | {line}", flush=True)
            captured.append(line)
        rc = proc.wait(timeout=2400)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        return "ERROR: pipeline timed out after 40 minutes"

    output = "\n".join(captured).strip()
    head = output[-7000:] if output else "(no output)"
    return f"exit_code={rc}\n\n{head}"


def _tag_failure_kind(raw: str, kind_map: list[tuple[str, str]]) -> str:
    """Prefix a `FAILURE_KIND: <kind>` line to the subprocess output.

    `kind_map` is a list of (sentinel_substring, kind_name) pairs,
    checked in order. The first matching sentinel wins. If none match
    and `exit_code=0` is in the output, the result is tagged as `none`.
    Otherwise the kind is `unknown`.
    """
    for sentinel, kind in kind_map:
        if sentinel in raw:
            return f"FAILURE_KIND: {kind}\n\n{raw}"
    if "exit_code=0" in raw:
        return f"FAILURE_KIND: none\n\n{raw}"
    return f"FAILURE_KIND: unknown\n\n{raw}"


def run_reel(args: dict, dry_run: bool) -> str:
    py = sys.executable or "python3"
    cmd = [
        py, "-u", "pipelines/reel/make_reel.py",
        "--script",        args["script"],
        "--title",         args["title"],
        "--topic",         args["topic"],
        "--tone-override", args["tone_override"],
        "--hint",          args["hint"],
    ]
    if args.get("subject_key"):
        cmd += ["--subject-key", args["subject_key"].strip().lower()]
    if dry_run:
        cmd.append("--dry-run")
    raw = _run_pipeline(cmd)
    return _tag_failure_kind(raw, [
        # D.1 fact verification gate (audit Phase D). Listed first so it
        # wins over more generic sentinels when the model writes a
        # contradictory script ("Britain Rationed Bread" + "never rationed")
        # or sneaks "fictional"/"absurdity" framing into the brief.
        ("ERROR: fact verification failed",    "fact_verification_failed"),
        ("ERROR: TTS returned no word timing", "tts_failed"),
        ("ERROR: could not find any footage",  "no_footage"),
        ("reel FAILED ffmpeg",                 "ffmpeg_failed"),
        ("reel FAILED thumbnail",             "thumbnail_failed"),
        ("reel FAILED video upload",           "video_upload_failed"),
        ("reel FAILED publish",                "publish_failed"),
        ("exit_code=10",                       "lock_contention"),
    ])


def run_carousel(args: dict, dry_run: bool, format_type: str = "fact") -> str:
    from src.content.carousel_rules import profile_for_format
    py = sys.executable or "python3"
    cmd = [
        py, "-u", "pipelines/carousel/ship_carousel_post.py",
        "--brief",  args["brief"],
        "--label",  args["label"],
        "--slides", str(args.get("slides", 6)),
        "--type",   format_type,
    ]
    if args.get("subject_key"):
        cmd += ["--subject-key", args["subject_key"].strip().lower()]
    # Layout-profile routing is owned by src/content/carousel_rules.py
    # (single source of truth). The previous inline `if format_type in
    # ("list", "news")` lived here AND in ship_manual_post.py; either
    # could drift. Pass the resolved profile explicitly when it differs
    # from the CLI's per-type default so the agent's intent is visible
    # in the workflow log.
    layout_mode = profile_for_format(format_type)
    cmd.extend(["--layout-mode", layout_mode])
    if dry_run:
        cmd.append("--dry-run")
    raw = _run_pipeline(cmd)
    return _tag_failure_kind(raw, [
        # D.2 list format rule (audit Phase D). Listed first so it wins
        # over CONTENT_SHAPE_MISMATCH when the validator raises a
        # CarouselShapeError carrying the "list format rule failed"
        # message; otherwise the more generic shape sentinel would match
        # first and the agent would not learn to retry the cover with a
        # criterion + source instead of a bare superlative.
        ("ERROR: list format rule failed",  "list_format_failed"),
        # D.1 fact verification gate (audit Phase D). Listed before
        # CONTENT_SHAPE_MISMATCH for the same precedence reason as the
        # list-format sentinel above.
        ("ERROR: fact verification failed", "fact_verification_failed"),
        ("CONTENT_SHAPE_MISMATCH",          "content_shape_mismatch"),
        ("COVER_IMAGE_FAILED",              "cover_image_failed"),
        ("PUBLISH FAILED",                  "publish_failed"),
    ])


# ------------------------------------------------------------------ #
# Tool schemas exposed to the model
# ------------------------------------------------------------------ #

TOOLS = [
    {
        "name": "list_unposted_topics",
        "description": (
            "Return the post bank: a compact summary of the last 30 posts "
            "to @factjot. Each line is `YYYY-MM-DD [format/CATEGORY] "
            "subject keywords`. Use this to reject any candidate that "
            "overlaps a previous topic, angle, list idea, ranking, or "
            "subject, even when reworded. Call this FIRST."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_story_candidates",
        "description": (
            "Return ranked story candidates from the Story Scout pre-selection layer. "
            "Candidates are Reddit-first, scored for hook strength, novelty against post "
            "history, and visual potential. Call this before drafting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "run_reel",
        "description": (
            "Compose and publish one reel. The pipeline finds footage, "
            "narrates with ElevenLabs, renders, and uploads to Instagram. "
            "Call this exactly ONCE per session. Do not retry on failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "70-120 word narration script. First sentence is the hook.",
                },
                "title": {
                    "type": "string",
                    "description": (
                        "3-6 words. Name the subject — not the event. "
                        "Ask: what IS this thing? Not: what happened? "
                        "A good title names the object, person, creature, "
                        "or situation by its defining quality. It does not "
                        "describe a sequence of events. "
                        "GOOD: 'The Demon Core' — names the object. "
                        "GOOD: 'The Soldier Nobody Could Discharge' — names "
                        "the person by their defining situation. "
                        "GOOD: 'The Explosion With No Crater' — names the "
                        "paradox that IS the story. "
                        "GOOD: 'The Army That Surrendered to Emus' — names "
                        "the army by its one defining act. "
                        "BAD: 'The War That Ended For 1 Man In 1974' — "
                        "describes an event, not a subject. "
                        "BAD: 'Australia Lost a War to Birds' — plot summary. "
                        "If it reads like a sentence describing what happened, "
                        "ask instead: what is the NAME of this thing?"
                    ),
                },
                "topic": {
                    "type": "string",
                    "enum": ["history", "science", "biology", "ocean", "earth", "space", "technology"],
                },
                "tone_override": {
                    "type": "string",
                    "enum": ["shocking", "curious", "sober", "wholesome"],
                },
                "hint": {
                    "type": "string",
                    "description": (
                        "Multi-line string containing the ranked footage search terms "
                        "you produced after writing the script. One term per line, "
                        "best-first. Each term should be tuned to how stock libraries "
                        "and image APIs actually index content (era, setting, subject, "
                        "mood, composition as separate terms rather than one compressed "
                        "phrase). Optionally append open-source library search URLs "
                        "(Wikimedia Commons, NASA image library, Wellcome Collection, "
                        "Internet Archive) on their own lines where the imagery there "
                        "is likely more accurate or interesting than generic stock."
                    ),
                },
                "subject_key": {
                    "type": "string",
                    "description": (
                        "Canonical lowercase hyphenated identifier for the real-world subject. "
                        "Name the THING, not the title of the reel. "
                        "GOOD: 'radium-girls', 'great-molasses-flood', 'operation-acoustic-kitty'. "
                        "BAD: 'girls-who-glowed', 'the-flood-that-got-a-refund'. "
                        "Must be specific enough that two posts about the same subject always "
                        "produce the same key. Hard-blocked against all previous posts permanently."
                    ),
                },
            },
            "required": ["script", "title", "topic", "tone_override", "hint", "subject_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_carousel",
        "description": (
            "Compose and publish one carousel. The writer prompt and slide "
            "count are decided by the run mode (news / list / fact), not "
            "by this call. You only supply the brief, the label, and the "
            "number of slides. Call exactly ONCE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": (
                        "2-4 sentence plain-English brief covering angle, "
                        "tone, and what the viewer should understand by the "
                        "end. For list-style posts, name the list (e.g. "
                        "'Five inventions nobody asked for') and list each "
                        "item explicitly so the slide-writer cannot drift."
                    ),
                },
                "label": {
                    "type": "string",
                    "description": "Category label in CAPS (e.g. TECHNOLOGY, HISTORY, SCIENCE).",
                },
                "slides": {
                    "type": "integer",
                    "description": (
                        "Number of slides. Default 6. Use 7 only for a "
                        "5-item list (cover + 5 items + closing)."
                    ),
                },
                "subject_key": {
                    "type": "string",
                    "description": (
                        "Canonical lowercase hyphenated identifier for the real-world subject. "
                        "For list posts: name the list subject, not the title. "
                        "GOOD: 'biggest-dam-failures', 'most-expensive-military-projects'. "
                        "BAD: 'five-dam-failures-by-death-toll'. "
                        "Hard-blocked against all previous posts permanently."
                    ),
                },
            },
            "required": ["brief", "label", "subject_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skip",
        "description": (
            "Abort this run with no post. Use ONLY when no candidate "
            "clears the quality gate. Better to skip a slot than ship a "
            "weak post. The next slot will fire normally."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "One-line reason for skipping. Logged for audit.",
                },
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]


def tools_for_mode(mode: str) -> list[dict]:
    """Return only the tool schemas the given mode is allowed to call."""
    allowed = set(MODE_TOOLS[mode])
    return [t for t in TOOLS if t["name"] in allowed]


def _candidate_subject_text(name: str, args: dict) -> str:
    """Return the free-text the agent supplied for the candidate post.

    For reels, prefer `title` (subject identity) over `script` (body copy).
    Stored reel fingerprints derive from `reel_title`, so candidate must
    use the same source or Jaccard collapses to 0.0. This was the root
    cause of the 2026-05-09 "Top 5 scariest films" double-post: identical
    title, two different scripts, two different fingerprints, both shipped.

    For carousels, prefer `brief` over `label`. `label` is just the
    category in CAPS (TECHNOLOGY, HISTORY, etc) and would false-positive
    every carousel in the same category as a duplicate.
    """
    if name == "run_reel":
        text = args.get("title") or args.get("script") or ""
    elif name == "run_carousel":
        text = args.get("brief") or args.get("label") or ""
    else:
        text = ""
    return (text or "")[:200]


def _format_dedup_rejection(
    candidate_text: str,
    collision: tuple[str, str, str, float],
) -> str:
    """Build the FAILURE_KIND-prefixed message returned to the agent when
    the candidate fingerprint collides with a recent post.
    """
    fp, iso, excerpt, sim = collision
    cand_fp = subject_fingerprint(candidate_text)
    return (
        "FAILURE_KIND: duplicate_subject\n\n"
        "REJECTED at code-level dedup. The candidate subject collides "
        f"with a recent post (Jaccard similarity {sim:.2f}, threshold "
        f"{FINGERPRINT_SIMILARITY_THRESHOLD:.2f}, window "
        f"{FINGERPRINT_WINDOW_DAYS} days).\n"
        f"  candidate fingerprint: {cand_fp}\n"
        f"  matched fingerprint:   {fp}\n"
        f"  matched post date:     {iso[:10]}\n"
        f"  matched subject:       {excerpt}\n\n"
        "Choose a different subject (different proper noun, different "
        "angle, different mechanism) or call skip(reason). Do NOT retry "
        "with the same idea reworded - that produces the same fingerprint."
    )


def execute_tool(
    name: str,
    args: dict,
    dry_run: bool,
    mode: str,
    recent_fingerprints: list[tuple[str, str, str]] | None = None,
    used_subject_keys: set[str] | None = None,
) -> str:
    if name == "list_unposted_topics":
        return build_history_summary()
    if name == "list_story_candidates":
        rows = ranked_candidates_for_mode(mode=mode, top_n=12)
        list_pool = build_list_reel_possibilities(mode=mode, max_outcomes=15)
        lines = []
        lines.append("RANKED_STORY_CANDIDATES")
        if not rows:
            lines.append("(no candidates found)")
        else:
            for i, row in enumerate(rows, 1):
                lines.append(
                    f"{i}. [{row['source']}] ({row['topic']}) score={row['total_score']:.3f} "
                    f"title={row['title']} | weird_bit={row['weird_bit']}"
                )
        lines.append("")
        lines.append("TOP5_LIST_POOL (generated examples, not fixed)")
        if not list_pool:
            lines.append("(no list pool ideas)")
        else:
            for i, idea in enumerate(list_pool, 1):
                lines.append(
                    f"{i}. ({idea['topic']}) {idea['title']}"
                )
        return "\n".join(lines)
    if name == "skip":
        return f"SKIPPED: {args.get('reason', '(no reason given)')}"
    if name in ("run_reel", "run_carousel"):
        # --- Subject-key dedup (permanent, all-time hard block) ---
        # This catches "same real-world story told differently", which fingerprint
        # similarity cannot detect when titles are creatively reframed.
        # 2026-05-13: Radium Girls double-post root cause — title Jaccard = 0.0.
        sk = (args.get("subject_key") or "").strip().lower()
        if sk:
            sk_pool = used_subject_keys if used_subject_keys is not None \
                else load_used_subject_keys()
            if sk in sk_pool:
                print(f"[dedup] subject_key exact block: '{sk}'", flush=True)
                return (
                    f"FAILURE_KIND: duplicate_subject\n\n"
                    f"REJECTED: subject_key '{sk}' has already been posted. "
                    "Choose a different subject or call skip(reason)."
                )
            collision_key = _find_key_collision(sk, sk_pool)
            if collision_key:
                print(
                    f"[dedup] subject_key fuzzy block: '{sk}' ~ '{collision_key}'",
                    flush=True,
                )
                return (
                    f"FAILURE_KIND: duplicate_subject\n\n"
                    f"REJECTED: subject_key '{sk}' is too similar to '{collision_key}' "
                    "(already posted). Choose a different subject or call skip(reason)."
                )
            # Poison in-session so a second turn in the same session is blocked
            # before the on-disk ledger is updated.
            if used_subject_keys is not None:
                used_subject_keys.add(sk)
            print(f"[dedup] subject_key cleared: '{sk}'", flush=True)

        # Code-level subject-fingerprint dedup. Runs before the subprocess
        # fires so we save the cost of running a pipeline only to reject.
        recent = recent_fingerprints if recent_fingerprints is not None \
            else load_recent_fingerprints()
        candidate_text = _candidate_subject_text(name, args)
        collision = find_subject_collision(candidate_text, recent)
        if collision is not None:
            print(
                f"[dedup] code-level reject for {name}: "
                f"sim={collision[3]:.2f} matched={collision[0]} "
                f"date={collision[1][:10]}",
                flush=True,
            )
            return _format_dedup_rejection(candidate_text, collision)
        # Poison this fingerprint in-session BEFORE dispatch. The on-disk
        # ledger update only lands after the subprocess succeeds and the
        # workflow commits state, but the agent may take a second turn
        # in the same session. Without this guard, the second turn reads
        # a stale in-memory cache and bypasses dedup. Live regression:
        # 2026-05-09 "Top 5 scariest films" double-post (21 min apart,
        # same session).
        cand_fp = subject_fingerprint(candidate_text)
        if cand_fp and recent_fingerprints is not None:
            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            recent_fingerprints.append(
                (cand_fp, now_iso, candidate_text[:80].strip())
            )
            print(
                f"[dedup] in-session poison: {cand_fp} "
                f"(cache size now {len(recent_fingerprints)})",
                flush=True,
            )
        if name == "run_reel":
            return run_reel(args, dry_run)
        format_type = MODE_FORMAT_TYPE.get(mode, "fact")
        return run_carousel(args, dry_run, format_type)
    return f"ERROR: unknown tool {name}"


# ------------------------------------------------------------------ #
# Prompt
# ------------------------------------------------------------------ #

SHARED_CORE = textwrap.dedent("""\
    You are running the factjot Instagram account (@factjot).

    Your job is to publish one strong post that feels strange, sharp,
    specific, and worth stopping for.

    factjot is not a trivia page.
    factjot is not a general facts page.
    factjot is not here to explain mildly interesting things politely.
    factjot posts true things where the detail, mechanism, decision,
    consequence, or contradiction makes reality look stranger than it
    should.

    The post should feel like:
    'Here is something ridiculous and true. Do what you want with that.'

    You have NO file access, NO shell access, NO repo browsing. Your
    tools are listed in the MODE block below. Nothing else exists.

    DUPLICATE GUARD - HARD RULE

    Before creating or posting anything, call list_unposted_topics() and
    compare every candidate against the post bank.
    Reject any candidate that repeats:
    - the same subject
    - the same event
    - the same person
    - the same company
    - the same product
    - the same animal
    - the same object
    - the same list idea
    - the same ranking
    - the same angle
    - the same story framed differently
    - a near-duplicate with only minor wording changes
    This applies across every format.

    Every run_reel and run_carousel call MUST include subject_key.
    subject_key is the canonical lowercase hyphenated name for the
    real-world subject (e.g. 'radium-girls', 'great-molasses-flood').
    It is hard-blocked against all previous posts permanently — no
    time window. A repeated subject_key is rejected before the
    pipeline runs, regardless of title or script wording.

    INTERESTINGNESS GATE - HARD RULE

    Do not post a fact because the subject is famous, dramatic, tragic,
    old, scientific, royal, expensive, dangerous, large, rare, cute,
    disgusting, or visually obvious.
    Those things can help, but they are not the reason to post.

    Only post a candidate if it has a clear weird bit.
    The weird bit must be one of these:
    - a contradiction
    - an absurd mechanism
    - a stupid decision
    - a strange consequence
    - an overlooked detail
    - a design failure
    - a system behaving in a way no normal person would expect
    - a true detail that sounds fake without exaggeration
    - a familiar thing made newly strange by one specific fact

    Before posting, ask:
    'What is the actual weird bit?'
    If the answer is just the main event itself, reject it.
    If the answer is only 'this happened', reject it.
    If the answer needs hype words to sound interesting, reject it.
    If the answer is a specific detail, mechanism, decision,
    contradiction, or consequence, it can continue.

    EVENT VS ANGLE RULE

    A subject is not an angle.
    A disaster, invention, animal, law, product, company, trial, war,
    ship, study, place, object, or discovery is only the subject.
    The angle is the reason the subject becomes strange.

    Weak:
    'A ship sank.'
    Strong:
    'The ship sank because the design, decision-making, cargo, rescue
    system, or political context was absurd in a specific way.'

    Weak:
    'A product failed.'
    Strong:
    'A company spent millions solving a problem people did not have,
    then acted surprised when nobody wanted it.'

    Weak:
    'An animal is unusual.'
    Strong:
    'The animal behaves in a way that sounds like a crime, a loophole,
    a scam, or a design bug in nature.'

    This rule does not ban any topic.
    It bans weak angles.

    QUALITY GATE - HARD RULE

    A candidate must pass all four:
    1. The weird bit is specific.
    2. The weird bit can be said in one sentence.
    3. The weird bit is the main hook, not a side detail.
    4. The weird bit would still be interesting without hype words.

    Then it must pass at least one:
    - It sounds fake but is true.
    - It reveals a stupid decision.
    - It has an absurd consequence.
    - It exposes a strange system, rule, design, belief, or behaviour.
    - It makes a familiar subject feel newly strange.
    - It makes the viewer think 'why did nobody stop this?'
    - It makes the viewer think 'how was that allowed?'
    - It makes the viewer think 'sorry, what?'

    If it does not pass, reject it.

    GOOD FACTJOT AREAS

    Good ideas often come from:
    - failed products
    - strange laws
    - odd business decisions
    - badly designed systems
    - obscure historical details
    - animal behaviour
    - weird science
    - internet history
    - forgotten technology
    - corporate overconfidence
    - public information that sounds like satire
    - absurd consequences of normal decisions
    - quiet shutdowns, recalls, bugs, trials, tribunals, or rule changes

    These are only starting points.
    The idea still needs a strong weird bit.

    SAFETY AND TASTE REJECTIONS

    Reject:
    - sexual violence
    - animal cruelty presented for entertainment
    - child harm
    - graphic injury or gore
    - medical advice
    - financial advice
    - defamatory claims about living people
    - unverified criminal accusations
    - active political outrage bait
    - culture-war bait
    - tragedy treated as a joke
    - recent deaths or disasters handled flippantly
    - anything that needs precise live sourcing but cannot be verified

    VOICE

    factjot is:
    - dry
    - direct
    - British English
    - faintly contemptuous of people who are incurious
    - lightly confused by how stupid or strange reality is
    - funny without trying to be a comedian
    - clever without sounding like a TED Talk

    factjot is not:
    - corporate
    - inspirational
    - wholesome by default
    - clickbait
    - fake edgy
    - American YouTube voice
    - a list of fun facts
    - over-explained
    - full of emojis
    - using em dashes
    - using 'did you know'
    - using 'mind-blowing'
    - using 'you won't believe'
    - using 'this changed everything'

    The narrator should sound like someone calmly pointing at reality
    and asking why everyone is pretending this is normal.

    SKIP RULE - HARD RULE

    Better to miss this slot than ship a weak post.
    If no candidate clears the quality gate, call the `skip` tool with
    a one-line reason. Do not call the posting tool with a weak idea.
    The next slot will fire normally.

    UNIVERSAL POSTING RULES

    - Call list_unposted_topics() FIRST.
    - Call exactly one of: the posting tool, OR `skip`. Never both.
    - Do not retry on failure.
    - Do not use em dashes.
    - Do not use hashtags unless the pipeline adds them itself.
    - Only post facts that are specific, named, and well-documented.
    - Prefer facts tied to a named event, person, study, company,
      product, object, animal, law, place, or date.
    - Avoid anything attributed only to 'scientists say', 'studies show',
      'people believe', or 'experts claim'.

    Final test before posting:
    If this appeared in your own feed, would you stop scrolling because
    the idea itself is weird, not because the wording is loud?
    If the answer is no, skip.
""")


REEL_PROMPT = textwrap.dedent("""\

    MODE: EVERGREEN REEL

    Format is locked: this slot publishes a reel and only a reel.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_reel(script, title, topic, tone_override, hint)
    - skip(reason)

    EVERGREEN ONLY

    No news. No current events. No this-week stories. No anything that
    needs the viewer to know what just happened in the world. The reel
    must work the same way next year as it does today.

    Good evergreen subjects:
    - history (named people, named events, with a specific weird angle)
    - science / biology / earth / ocean / space (one striking mechanism)
    - obscure technology, lost or abandoned
    - animal behaviour with a specific named species
    - bureaucratic absurdities, old laws, old rulings, old experiments

    REEL RULES

    - Script must be 70 to 120 words.
    - The first sentence is the hook.
    - The first sentence must contain the weird bit.
    - Do not build up to the fact.
    - Do not start with soft context.
    - Use a specific number, name, place, product, company, animal, or
      object wherever possible.
    - The hook should sound strange without needing hype words.
    - No filler intro.
    - No 'did you know'.
    - No fake suspense.
    - No motivational framing.
    - No fake profundity.

    LIST-TO-REEL FORMAT (allowed and encouraged when strong)

    A list can run as a reel if it is tight and weird-bit first.
    Use this exact structure:
    1) Hook sentence with the weird bit and list frame.
    2) Item 1 in one short sentence (name + hard fact).
    3) Item 2 in one short sentence (name + hard fact).
    4) Item 3 in one short sentence (name + hard fact).
    5) Closing line with one contrast, pattern, or consequence.

    Constraints:
    - 3 items only (not 5). Reel pacing breaks above this.
    - Each item must be a specific proper noun, date, number, or place.
    - Use numeric digits for rankings/dates in script and title (Top 5, 1973, 3 items).
      Do not spell numbers as words unless they are part of a proper name.
    - No ranking fluff ("number three will shock you").
    - No generic categories as items.
    - The hook must still carry the weird bit immediately.

    FOOTAGE QUERIES

    After writing the script, produce a ranked list of 4 to 6 footage
    search strings tuned to how stock libraries and image APIs index
    content. Search strings should separate era, setting, subject,
    object, mood, composition. Where the best visual is oblique, use
    oblique terms. Include open-source library URLs (Wikimedia Commons,
    NASA image library, Wellcome Collection, Internet Archive) on their
    own lines where the imagery is likely more accurate than stock.

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Call list_story_candidates().
    3. Generate at least 5 candidate evergreen ideas from scout results and
       the TOP5_LIST_POOL block (Top 5 biggest/smallest/best/worst/etc.).
    4. Reject duplicates and near-duplicates against the bank.
    5. Reject any current/news/topical idea outright.
    6. For each remaining candidate, name the actual weird bit.
    7. Apply the interestingness, event-vs-angle, and quality gates.
    8. If nothing clears the bar, call skip(reason).
    9. Write the script + ranked footage hints.
    10. Name the subject_key: the canonical lowercase hyphenated identifier
        for the real-world subject (e.g. 'radium-girls', 'molasses-flood-1919').
        This is the name of the THING, not the title of the reel.
        Two posts about the same subject must always produce the same key.
    11. Write a short decision note (chosen idea, weird bit, why it
        passed, why weaker candidates failed). Then call run_reel ONCE.
""")


NEWS_PROMPT = textwrap.dedent("""\

    MODE: NEWS / CURRENT CAROUSEL

    Format is locked: this slot publishes a carousel framed around a
    current or recent story. The pipeline writes the slides; you supply
    the brief and the label.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_carousel(brief, label, slides)   [slides default 6]
    - skip(reason)

    Use your training knowledge to find a current or recent story. The
    bar is the story's STRANGENESS, not its recency. A 30-day-old story
    with a strange angle beats a today-story with a generic angle every
    time. Prefer stories from the last 30 days; the last 7 if available.

    QUALIFYING STORY

    Ask:
    1. 'Would this still be interesting if it happened a year from now?'
       If no, reject. Pure recency is not enough.
    2. 'Is there a strange, revealing, funny, bleak, or absurd angle?'
       If no, reject.
    3. 'Can the angle be said in one clean sentence?'
       If no, reject.

    Look for:
    - under-the-radar tech stories with a specific odd detail
    - weird business decisions and product failures
    - regulatory rulings, tribunals, or trials with absurd context
    - platform shutdowns, feature deletions, quiet recalls
    - internet culture moments that reveal something about a system
    - science / space / environment stories that are current and
      under-discussed
    - obscure updates with surprisingly large consequences

    Reject:
    - generic AI hype
    - earnings or routine product launches
    - vague 'could change everything' framing
    - political outrage bait or culture-war bait
    - celebrity gossip
    - rumours, leaks, unverified claims
    - tragedy treated as content
    - anything you cannot defend factually from training knowledge

    CAROUSEL RULES

    - 6 slides (cover + 5 content). Do not request 7 unless the story
      genuinely needs it.
    - Every slide must do work. No setup-only slides.
    - Brief must include: the story, the angle, what the viewer should
      understand by the end, the named entities involved, and any
      specific dates / numbers / names that anchor it.

    {beat_density_rules}

    The slide writer renders at 16-22 chars per line, hard cap 24, in
    Archivo Black 900 at 42px. If your beat needs more than 3 short
    sentences to express, it is two beats.

    {photographable_beats_rules}

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Call list_story_candidates().
    3. Surface at least 4 candidate current stories from scout results.
    3. Reject duplicates and near-duplicates against the bank.
    4. For each candidate, name the actual weird bit + the angle.
    5. Apply the qualifying-story checks and the quality gate.
    6. If nothing clears the bar, call skip(reason).
    7. Otherwise, write the brief + label.
    8. Decision note (chosen story, angle, why it passed, why weaker
       candidates failed). Call run_carousel ONCE with slides=6.
""")


LIST_PROMPT = textwrap.dedent("""\

    MODE: LIST CAROUSEL

    Format is locked: this slot publishes a ranked / curated
    superlative list. Each item is a standalone ranked entry,
    not a chapter in a thematic essay.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_carousel(brief, label, slides)   [slides default 7]
    - skip(reason)

    LIST RULES

    - 5 items. 7 slides total: cover, 5 items, closing.
    - Phase D.2 list format rule (criterion required).
      Every list MUST state ONE specific defensible criterion
      on the cover. The cover headline must follow EXACTLY one
      of these two shapes:
        a) 'Five [items] by [criterion]'
           e.g. 'Five engineering disasters by death toll'
                'Five films by domestic box office'
                'Five buildings by year of completion'
        b) 'Five [items] that [verifiable condition]'
           e.g. 'Five films that grossed under five million dollars'
                'Five disasters with confirmed casualties over 1,000'
                'Five companies that have traded since before 1700'
    - Allowed superlatives (numeric / defensible only). Each
      MUST be paired with a stated criterion:
        biggest, oldest, fastest, deadliest, longest, tallest,
        largest, richest, youngest, shortest, costliest, smallest,
        newest, slowest, most expensive, most profitable,
        least expensive, least profitable, most catastrophic.
    - BANNED superlatives. Do not use any of these on the cover
      or in the brief, even softened or rephrased:
        scariest, most underrated, strangest, most bizarre,
        best, worst, coolest, weirdest, most surprising,
        funniest, cutest, most iconic, most influential,
        most disturbing, safest, most dangerous, least survivable.
      These are aesthetic / opinion judgements that always
      require fabricated rank reasons. They are forbidden.
    - Bare-superlative covers ('Five scariest films',
      'Five most iconic moments') are explicitly forbidden.
      Use the 'by [criterion]' or 'that [condition]' form.
    - Every item must be a single named, googleable thing
      (a specific disaster, film, animal, country, law, recall,
      product, building, accident, person). One concrete proper
      noun per item, not a concept.
    - The criterion must be measurable from public records: a
      number (USD, km, year, death toll, runtime in minutes), a
      record (BFI Sight & Sound 2022 critics' poll, USGS
      confirmed fatalities, Forbes 2025 net worth), or a
      verifiable yes / no (still trading, still in print).
    - No connective theme requiring every slide to argue a
      mechanism. If two items only make sense together, the
      list is wrong.
    - No BuzzFeed shapes. No 'you won't believe number 4'.
    - If the list would look at home on a generic trivia
      account, reject it AND if it would only make sense as an
      essay, also reject it.

    Good list shapes (criterion stated):
    - 'Five engineering disasters by confirmed death toll'
    - 'Five films by domestic box office'
    - 'Five buildings by year of completion'
    - 'Five companies that have traded since before 1700'
    - 'Five films that grossed under five million dollars'
    - 'Five recalls by total recall cost in USD'
    - 'Five mountains by recorded height'
    - 'Five animals by recorded body length'

    Bad list shapes (rejected):
    - 'Five scariest films ever'                       (banned superlative)
    - 'Five most underrated albums'                    (banned superlative)
    - 'Five strangest laws still on the books'         (banned superlative)
    - 'Five most iconic moments in sport'              (banned superlative)
    - 'Five fixes that became the thing they were meant to solve'  (essay)
    - 'Five amazing facts about space'                 (no criterion)
    - 'Top 5 weirdest animals'                         (banned superlative)
    - 'Things you didn't know about X'                 (no shape)

    Test before accepting a list:
    - Could a viewer screenshot any one item slide and have it
      stand on its own? If items only make sense in sequence,
      reject the list.
    - Does the cover follow 'Five [items] by [criterion]' or
      'Five [items] that [verifiable condition]'? If not, reject.
    - Is the criterion measurable from public records? If you
      cannot point to a source for the ranking, reject.

    BRIEF SHAPE

    Brief MUST include:
    - the list title in the 'by [criterion]' or 'that
      [verifiable condition]' shape (5-9 words, voice-correct,
      banned superlatives forbidden)
    - the criterion source explicitly named (e.g. 'BFI Sight &
      Sound 2022 critics' poll', 'USGS confirmed fatalities,
      1900-present', 'Box Office Mojo, domestic gross', 'Forbes
      2025 net worth list')
    - 5 items, in order, each with:
        * NAME: the single proper-noun subject
        * RANK REASON: one number / fact that earns it the spot
          (e.g. '$200M loss', 'killed 1,134 workers', '0.49 km^2')
        * CONCRETE FACT: one extra hard fact about it (date,
          place, scale, outcome)
        * WHY IT BELONGS: one short clause tying it to the
          criterion
    - the closing slide MUST cite the criterion source
      explicitly (e.g. 'Source: USGS confirmed fatalities,
      1900-present', 'Source: Box Office Mojo'). The closer is
      a source citation, not a moral takeaway.

    If no clean criterion exists for the candidate topic, do
    not ship a bare-superlative carousel. Call skip(reason)
    instead.

    {beat_density_rules}

    Each list item gets ONE slide. That slide carries ONE
    item: its name (red, treated as the item title), the rank
    reason, and the concrete fact. Do not narrate a setup ->
    mechanism -> consequence arc. Do not pack two items in one
    slide. Item slides should read like ranked entries, not
    paragraphs.

    {photographable_beats_rules}

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Call list_story_candidates().
    3. Generate at least 3 candidate superlative lists from scout results.
       Each candidate MUST already have a defensible criterion;
       if the topic has no measurable axis, drop it now.
    4. Reject duplicates and overlap with previous lists.
       Reject any candidate that is a conceptual / thematic
       essay disguised as a list.
    5. For each survivor, name the criterion, name the source,
       and list the 5 items with their rank reason and one
       concrete fact.
    6. If you cannot defend the ranking of all 5 items from the
       criterion source, reject the list (or replace items).
    7. Apply the interestingness + quality gates to the LIST
       as a whole (not to each item individually).
    8. If nothing clears the bar (no criterion, no source, no
       defensible rank), call skip(reason). Do NOT fall back to
       a bare-superlative cover.
    9. Otherwise, write the brief and call run_carousel ONCE
       with slides=7.
""")


FACT_PROMPT = textwrap.dedent("""\

    MODE: FACT CAROUSEL

    Format is locked: this slot publishes a single-subject fact
    carousel. One subject, six slides, told properly.

    AVAILABLE TOOLS
    - list_unposted_topics()
    - run_carousel(brief, label, slides)   [slides default 6]
    - skip(reason)

    A fact carousel is NOT a list. It is one subject with enough
    strangeness or specificity to reward 6 slides of sustained attention.
    Subject can be anything: a person, an event, a place, an object, an
    invention, a phenomenon, a system, a study, a rule, an animal.

    The carousel should build:
    1. cover         - hook the subject and the question / angle
    2. setup         - what the subject is, briefly
    3. mechanism     - how it works / how it happened
    4. consequence   - what it caused / what changed
    5. contradiction - the bit that makes it strange
    6. closing       - the line that makes the viewer think

    These are illustrative slot-types, not strict labels. The point is
    the carousel must move forward. Every slide must add information,
    not restate the cover.

    EVERGREEN

    No news. No current events. The subject can be old or unfamiliar
    but the subject's strangeness must hold up without breaking news.

    Good fact subjects:
    - Concorde, the Voynich Manuscript, Phineas Gage, Gobekli Tepe
    - the Stanford prison experiment, the Antikythera mechanism
    - obscure inventions, abandoned technologies, dead languages
    - bureaucratic failures, lost lawsuits, forgotten experiments
    - specific named animals or species with a strange behaviour
    - geological / astronomical phenomena with a precise mechanism

    Bad fact subjects:
    - 'space is big' / 'the ocean is deep'
    - generic 'top scientist discovers' framing
    - subjects that boil down to one sentence (those belong in reels)
    - subjects you can't defend factually from training knowledge

    BRIEF SHAPE

    Brief MUST include:
    - the subject (canonical proper name)
    - the angle (the weird bit, the contradiction, the consequence)
    - the 5 beats the carousel should hit, in order
    - what the closing slide should make the viewer think

    {beat_density_rules}

    If the story has 7 distinct things worth saying, write 7 beats and
    call run_carousel with slides=8 (cover + 7). Better to have more
    short slides than fewer crowded ones.

    Each line on a slide is rendered in Archivo Black 900 at 42px. The
    writer has 16-22 characters per line, hard cap 24. If your beat
    needs more than 3 short sentences to express, it is two beats.

    {photographable_beats_rules}

    DECISION PROCESS

    1. Call list_unposted_topics().
    2. Call list_story_candidates().
    3. Generate at least 4 candidate fact subjects from scout results.
    3. Reject duplicates and near-duplicates against the bank.
    4. For each, identify the weird bit and the 5 beats it would carry.
    5. Reject any subject whose strangeness is exhausted in 1-2 slides
       (those belong in a reel slot, not here).
    6. Apply the quality gate.
    7. If nothing clears the bar, call skip(reason).
    8. Otherwise, write the brief and call run_carousel ONCE with
       slides=6.
""")


_CAROUSEL_RULE_BINDINGS = dict(
    beat_density_rules         = BEAT_DENSITY_RULES,
    photographable_beats_rules = PHOTOGRAPHABLE_BEATS_RULES,
)

MODE_PROMPTS: dict[str, str] = {
    "reel_morning": REEL_PROMPT,
    "reel_night": REEL_PROMPT,
    "list_midday": LIST_PROMPT.format(**_CAROUSEL_RULE_BINDINGS),
}


def build_prompt(mode: str) -> str:
    return SHARED_CORE + MODE_PROMPTS[mode]


# ------------------------------------------------------------------ #
# Agent loop
# ------------------------------------------------------------------ #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="factjot autonomous agent")
    parser.add_argument(
        "--post-mode",
        choices=VALID_MODES,
        default=os.getenv("POST_MODE", "reel_morning"),
        help="Posting mode (also reads POST_MODE env).",
    )
    args = parser.parse_args(argv)
    mode = args.post_mode

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    dry_run = os.getenv("DRY_RUN", "false").strip().lower() == "true"

    # Phase N (2026-05-11): list_midday bypasses the LLM loop entirely
    # and ships a curated film/TV pack via pipelines/list/ship_curated_list.
    # The 8 hand-curated packs in src/content/list_packs.py rotate by
    # last-used timestamp (backfilled from posted.jsonl history). TMDB
    # provides posters + backdrops + Rotten Tomatoes scores; the list
    # renderer matches the visual vibe of the early film carousels
    # (war_films_definitive, mind_bending_scifi, etc) that shipped
    # 2026-05-01 to 2026-05-06.
    if mode == "list_midday":
        print(f"[autonomous-agent] mode={mode} -> curated list pack", flush=True)
        cmd = [sys.executable or "python3", "-u",
               "-m", "pipelines.list.ship_curated_list"]
        if dry_run:
            cmd.append("--dry-run")
        return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode

    print(
        f"[autonomous-agent] mode={mode} dry_run={dry_run} "
        f"model={MODEL} max_turns={MAX_TURNS}",
        flush=True,
    )

    client   = anthropic.Anthropic(api_key=api_key)
    prompt   = build_prompt(mode)
    tools    = tools_for_mode(mode)
    # Pre-load recent post fingerprints once per agent invocation. The
    # ledgers can grow large (~1k+ posts), and the dedup check runs once
    # per posting tool call - typically once per session, but loop retries
    # happen, so a per-turn re-read is wasteful and racy.
    recent_fingerprints = load_recent_fingerprints()
    print(
        f"[dedup] loaded {len(recent_fingerprints)} unique subject "
        f"fingerprints from last {FINGERPRINT_WINDOW_DAYS} days",
        flush=True,
    )
    # Pre-load all-time subject keys (permanent dedup, no time window).
    used_subject_keys = load_used_subject_keys()
    print(
        f"[dedup] loaded {len(used_subject_keys)} subject keys (all-time)",
        flush=True,
    )
    # The first user message carries the giant per-mode prompt. Marking
    # it cache_control=ephemeral pins the prefix (tools + system + this
    # message) in Anthropic's prompt cache for ~5 minutes, so every turn
    # after the first reads it at 10% of input cost. The agent loop runs
    # 1-12 turns within seconds, so cache hits happen on turn 2 onwards.
    messages: list[dict] = [{
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }]

    total_input          = 0
    total_output         = 0
    total_cache_creation = 0
    total_cache_read     = 0
    final_status         = "unknown"
    exit_code            = 0
    skipped              = False
    last_publish_failure = ""

    try:
        for turn in range(MAX_TURNS):
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM,
                tools=tools,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                total_input          += getattr(usage, "input_tokens",  0) or 0
                total_output         += getattr(usage, "output_tokens", 0) or 0
                total_cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0
                total_cache_read     += getattr(usage, "cache_read_input_tokens", 0) or 0
                # Per-turn visibility: show whether the prefix hit the cache.
                cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cr = getattr(usage, "cache_read_input_tokens", 0) or 0
                if cw or cr:
                    print(
                        f"[cache] turn={turn} cache_write={cw} cache_read={cr}",
                        flush=True,
                    )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                print("\n[autonomous-agent] finished (end_turn).", flush=True)
                final_status = "end_turn"
                break
            if response.stop_reason != "tool_use":
                print(f"[autonomous-agent] unexpected stop_reason: {response.stop_reason}", flush=True)
                final_status = f"stop_{response.stop_reason}"
                exit_code = 1
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"\n[tool] {block.name}({list(block.input.keys())})", flush=True)
                if block.name == "skip":
                    reason = block.input.get("reason", "(no reason given)")
                    print(f"\n[SKIP] mode={mode} reason={reason}", flush=True)
                    final_status = "skipped"
                    skipped = True
                    break
                output = execute_tool(
                    block.name, block.input, dry_run, mode,
                    recent_fingerprints=recent_fingerprints,
                    used_subject_keys=used_subject_keys,
                )
                if block.name in ("run_reel", "run_carousel"):
                    first_line = output.split("\n", 1)[0]
                    if first_line.startswith("FAILURE_KIND:"):
                        kind = first_line.split("FAILURE_KIND:", 1)[1].strip()
                        last_publish_failure = "" if kind == "none" else kind
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output,
                })

            if skipped:
                break

            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"[autonomous-agent] hit max turns ({MAX_TURNS}).", flush=True)
            final_status = "max_turns"

        if last_publish_failure and not skipped:
            exit_code    = 1
            final_status = f"publish_failed:{last_publish_failure}"
            print(
                f"[autonomous-agent] last publish tool failed: {last_publish_failure}",
                flush=True,
            )
    finally:
        _log_cost(
            mode, dry_run,
            total_input, total_output,
            total_cache_creation, total_cache_read,
            final_status,
        )

    return exit_code


def _log_cost(
    mode: str,
    dry_run: bool,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
    status: str,
) -> None:
    """Append per-run cost estimate to data/ledgers/api_usage_costs.jsonl.

    `input_tokens` is the SDK's `usage.input_tokens`, which does NOT include
    cache_creation_input_tokens or cache_read_input_tokens (those are billed
    on separate lines). The total below sums all four.
    """
    from datetime import datetime, timezone
    cost_in        = input_tokens          / 1_000_000 * PRICE_INPUT_PER_M
    cost_out       = output_tokens         / 1_000_000 * PRICE_OUTPUT_PER_M
    cost_cache_w   = cache_creation_tokens / 1_000_000 * PRICE_CACHE_WRITE_PER_M
    cost_cache_r   = cache_read_tokens     / 1_000_000 * PRICE_CACHE_READ_PER_M
    total          = round(cost_in + cost_out + cost_cache_w + cost_cache_r, 6)
    # Naive baseline if caching had been off: cache_read tokens would have
    # been charged at full input rate. cache_creation is already 1.25x of
    # input, so the real "saved" amount is cache_read * (1.0 - 0.10) input.
    baseline_input = (input_tokens + cache_creation_tokens + cache_read_tokens) \
        / 1_000_000 * PRICE_INPUT_PER_M
    baseline_total = round(baseline_input + cost_out, 6)
    saved          = round(baseline_total - total, 6)
    record = {
        "timestamp":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "source":        "autonomous_agent",
        "mode":          mode,
        "dry_run":       dry_run,
        "model":         MODEL,
        "input_tokens":          input_tokens,
        "output_tokens":         output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens":     cache_read_tokens,
        "stop_status":   status,
        "cost_estimate_usd": {
            "anthropic_input":        round(cost_in,      6),
            "anthropic_output":       round(cost_out,     6),
            "anthropic_cache_write":  round(cost_cache_w, 6),
            "anthropic_cache_read":   round(cost_cache_r, 6),
            "total":                  total,
            "baseline_no_cache":      baseline_total,
            "saved_by_cache":         saved,
        },
        "pricing_meta": {
            "input_per_million_usd":        PRICE_INPUT_PER_M,
            "output_per_million_usd":       PRICE_OUTPUT_PER_M,
            "cache_write_per_million_usd":  PRICE_CACHE_WRITE_PER_M,
            "cache_read_per_million_usd":   PRICE_CACHE_READ_PER_M,
        },
    }
    try:
        COST_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with COST_LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(
            f"[cost] in={input_tokens} out={output_tokens} "
            f"cache_w={cache_creation_tokens} cache_r={cache_read_tokens} "
            f"total=${total:.4f} saved=${saved:.4f} (mode={mode}, model={MODEL})",
            flush=True,
        )
    except Exception as exc:
        print(f"[cost] failed to write ledger: {exc}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
