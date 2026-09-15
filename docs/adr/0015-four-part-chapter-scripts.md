# Four-Part Chapter Scripts

## Content Contract

Each chapter exposes four separate parts:

- `plot`: an evidence-based summary of the chapter's events and development.
- `shots`: ordered camera directions with shot type and duration.
- `dialogues`: ordered spoken lines with `kind`, `speaker` and `text`.
  `narration` means voiceover; `dialogue` means a character's evidenced words.
- `visual_prompt`: the overall setting, environment and appearance description.

The script AI must return all four parts. It must not invent quotations. A
chapter without evidenced dialogue can contain only narration entries. The
legacy `narration` field is derived by joining spoken text with newlines, so
downstream timing and segmentation have one canonical spoken sequence.

## Reading and Generation

Interview, script book and studio use the shared `ScriptSections` reader.
Shot lists are filtered to the selected chapter. Script-book generation now
always sends `single_chapter` with an explicit chapter ID and selects that
chapter after the update. Existing books still contain all their saved chapters;
the legacy multi-chapter API remains compatible with existing callers.

Production snapshots include the four parts and their shots. A studio snapshot
must never borrow newer shots from the live project. Actual per-segment visuals
and submitted prompts can be inspected in the studio, but are read-only.
Moderation rewriting and automatic paid retries are outside this change.

Segment narration remains an exact slice of the canonical spoken text. Speaker
assignments are intersected with these slices, preserving character attribution
without adding speaker names or duplicating spoken words.

## Migration and Verification

Migration `20260915_0025` adds nullable `plot` and `dialogues` columns. Back up the
database before applying it and deploy the same source revision for API and web.
Existing records remain readable: narration is presented as voiceover and missing
plot or shot content is explicitly marked absent. There is no automatic AI
backfill, charge, deletion, or modification of historical production snapshots.
The next requested chapter update produces the new content structure.

Tests cover required AI fields, spoken-text derivation, API/workspace persistence,
snapshot isolation, speaker mapping across segment boundaries, chapter selection,
legacy display and safe plain-text rendering of actual prompts. Browser QA uses
synthetic API responses at 1440, 390 and 320 pixels with no paid generation calls.
