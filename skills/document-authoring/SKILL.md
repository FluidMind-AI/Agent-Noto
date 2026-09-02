---
name: Document Authoring
description: Create and revise Word (.docx) documents. Every document is a formatted .docx filed under a topic folder; every change becomes a new version carrying real Word tracked changes.
allowed-tools: Bash, Read, Write, Glob
---

# Document Authoring Skill

Triggered whenever the user asks for a **document**, **memo**, **write-up**,
**brief**, **report**, **proposal**, or **one-pager** — anything meant to be
read as a document rather than as a chat reply.

---

## The Rule

**Documents are Word files, not Markdown in the terminal.**

1. Every document is a properly formatted `.docx`.
2. It lives in a folder named for its **topic**, under `documents/`.
3. The first cut is `v1`. Never overwrite it.
4. Every later change writes a **new version** whose differences are real
   **Word tracked changes** — the kind you Accept/Reject in the Review ribbon.

Do not hand back a Markdown block and call it a document. Do not edit a
document in place. Do not simulate a redline with coloured text.

---

## Creating a document

Draft the content as Markdown, then hand it to the tool:

```bash
source "$NOTO_HOME/.venv/bin/activate"
python "$NOTO_HOME/tools/docx_author.py" create \
    --folder "$NOTO_HOME/documents/<topic-folder>" \
    --name "<Document Name>" \
    --title "<Document Title>" \
    --input draft.md
```

Writes `documents/<topic-folder>/<Document Name> v1.docx` and prints the path.

**Refuses to run if a version already exists** — that is deliberate. If you
meant to change an existing document, use `revise`, so the change is tracked.

### Choosing the folder

Name it for the **subject**, not the date or document type. One folder per
topic; related documents sit together.

| Ask | Folder |
|-----|--------|
|  "memo on Q4 hiring plans" | `documents/hiring/` |
| "draft the vendor agreement" | `documents/vendor-contracts/` |
| "write up the Q3 board update" | `documents/board-updates/` |

Check `documents/` for an existing folder that fits before inventing one.
`documents/misc/` means you did not think about it.

### Supported formatting

`#`–`####` headings · `-`/`*` bullets · `1.` numbered lists · `>` quotes ·
`---` rules · `**bold**` · `*italic*` · `` `code` ``.

---

## Revising a document

Write the **complete new text** of the document — not a diff, not just the
changed part. The tool computes the diff and marks it up.

```bash
python "$NOTO_HOME/tools/docx_author.py" revise \
    --folder "$NOTO_HOME/documents/<topic-folder>" \
    --name "<Document Name>" \
    --input revised.md
```

It finds the highest existing version, diffs against it, and writes the next
one. `v2` reports what changed on stderr:
`v1 -> v2: 1 inserted, 0 deleted, 3 edited, 6 unchanged`.

**Versions chain correctly.** `v3` diffs against `v2` as if v2's revisions
were accepted, so it marks only what is new — it does not re-flag v2's
changes. This is why you must never edit a `.docx` by hand: doing so breaks
the chain.

To see what exists:

```bash
python "$NOTO_HOME/tools/docx_author.py" versions \
    --folder "$NOTO_HOME/documents/<topic>" --name "<Name>"
```

---

## After writing

Tell the user the **path** and, for a revision, **what changed** — in words,
not just the counts. They open it in Word and accept or reject each change.

The nightly sync commits `documents/` to the private repo, so versions are
backed up without anyone remembering to commit.

---

## Notes and limits

- **Word only.** For a spreadsheet or slides, say so rather than forcing
  a `.docx`.
- **Tracked changes are paragraph- and word-level.** Rewriting a paragraph
  wholesale reads as one edit, which is usually what you want; moving a
  paragraph reads as a delete plus an insert, not as a move.
- **Tables and images are not supported** by the Markdown subset. If a
  document needs them, say so instead of silently dropping them.
- **Never hand-edit a generated `.docx`.** Revise it through the tool, or
  the version chain breaks.
