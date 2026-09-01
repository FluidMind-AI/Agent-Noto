---
name: File Processing
description: Process, classify, organize, and index documents. Extracts relevant information to user's memory.
allowed-tools: Bash, Read, Write, Glob
---

# File Processing Skill

When asked to "process", "organize", or "file" documents, follow this complete workflow.

---

## The Workflow

### 1. Read & Understand

Read each document to understand its content:
- PDFs: Use Read tool (supports PDF extraction)
- Images: Use Read tool (multimodal)
- Text files: Use Read tool

Extract key information:
- Document type (ID, legal, medical, business, personal)
- People involved
- Dates and events
- Important facts

### 2. Classify & Organize

Move files to the appropriate folder based on content:

| Document Type | Destination |
|---------------|-------------|
| Personal ID (cédula, passport, police certs) | `/home/user/documents/personal/id/` |
| Military records | `/home/user/documents/personal/military/` |
| Family member docs | `/home/user/documents/personal/{name}/` |
| Legal (divorces, contracts) | `/home/user/documents/legal/{category}/` |
| Migration/immigration | `/home/user/documents/legal/migration/` |
| Medical records, billing | `/home/user/documents/medical/` |
| Company documents | `/home/user/{CompanyName}/documents/` |
| Contact/third-party docs | `/home/user/documents/contacts/{name}/` |

**Important:** Company documents go in the company folder, not personal documents.

### 3. Index Files

Use `file_indexer.py` to add files to the searchable index:

```bash
$NOTO_HOME/tools/files.sh scan /path/to/folder --tags "tag1,tag2"
$NOTO_HOME/tools/files.sh add "/path/to/file.pdf" -d "Description" -t "tags"
```

Or with full command:
```bash
source $NOTO_HOME/.venv/bin/activate
python $NOTO_HOME/tools/file_indexer.py scan /path --tags "tags"
```

**Tagging guidelines:**
- Always include document type: `personal`, `legal`, `medical`, `business`
- Include person name if relevant: `alex`, `sam`, `kim`
- Include category: `id`, `passport`, `divorce`, `migration`

### 4. Extract to Memory

For documents containing personal information about the user or their family, add relevant facts to memory:

```bash
$NOTO_HOME/tools/memory.sh add "Fact extracted from document" --type fact --tags "relevant,tags"
```

Or with full command:
```bash
source $NOTO_HOME/.venv/bin/activate
python $NOTO_HOME/tools/memory_indexer.py add "..." --type fact --tags "..."
```

**What to extract:**
| Document Contains | Memory Type | Example |
|-------------------|-------------|---------|
| Birth date, ID numbers | fact | "The user's ID number is 12,345,678" |
| Events with dates | event | "Sam born January 1, 2010" |
| Relationships | person | "Jamie Example is the user's cousin" |
| Addresses | fact | "Current address: 123 Example Ave..." |
| Financial info | fact | "Medical debt: $1,234.56" |
| Expiration dates | fact | "Sam's passport expires Feb 14, 2030" |

**Don't extract:**
- Redundant information already in memory
- Trivial details
- Sensitive credentials (store securely elsewhere)

---

## Folder Structure Reference

```
/home/user/
├── documents/
│   ├── personal/
│   │   ├── id/           # the user's ID documents
│   │   ├── military/     # Military records
│   │   ├── sam/          # Family member documents
│   │   ├── kim/          # Family member documents
│   │   └── {family}/     # Other family members
│   ├── legal/
│   │   ├── divorces/
│   │   ├── migration/
│   │   └── contracts/
│   ├── medical/
│   └── contacts/
│       └── {name}/       # Third-party documents
└── {Company}/
    └── documents/        # Company docs (one folder per company)
```

---

## Transport Folder

New documents typically arrive in `/srv/fileserver/transport/` (local fileserver).

When processing transport:
1. List all files in transport
2. Process each file through the workflow
3. After successful copy and indexing, originals can remain or be removed

---

## Example Session

```bash
# 1. List what's in transport
ls /mnt/fileserver/transport/

# 2. Read a PDF
# (Use Read tool on each file)

# 3. Create destination folder if needed
mkdir -p /home/user/documents/personal/sam

# 4. Copy file to destination
cp "/mnt/fileserver/transport/Sam Birth Certificate.pdf" \
   "/home/user/documents/personal/sam/"

# 5. Index the file
source $NOTO_HOME/.venv/bin/activate
python $NOTO_HOME/tools/file_indexer.py scan \
  /home/user/documents/personal/sam --tags "personal,sam,family"

# 6. Add to memory
python $NOTO_HOME/tools/memory_indexer.py add \
  "Sam Example born January 1, 2010. Parent: Jordan Example" \
  --type fact --tags "family,sam"
```

---

## Quick Reference

| Action | Command |
|--------|---------|
| Scan folder | `files.sh scan /path --tags "tags"` |
| Add single file | `files.sh add "/path" -d "desc" -t "tags"` |
| Search files | `files.sh find "query"` |
| Add memory | `memory.sh add "fact" --type TYPE --tags "tags"` |
| Search memory | `memory.sh find "query"` |
