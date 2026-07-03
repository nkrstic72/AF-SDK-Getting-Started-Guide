# AVEVA Docs Local Knowledge Base

A local MCP server that lets Claude Code search 10GB+ of AVEVA/PI/AF documentation
without sending the full corpus to the API. Only the relevant chunks (~5-10 KB)
are included in each Claude session.

## How it works

```
Your .md files (10GB)
      │
      ▼  index_docs.py (run once)
  ChromaDB  ◄── local vector index (~500MB on disk)
      │
      ▼  mcp_server.py (auto-started by Claude Code)
   Claude Code
   calls search_aveva_docs("how do PI AF attributes work?")
      │
      ▼
   Top 6 matching chunks → included in Claude's context
```

---

## Setup (one time)

### 1. Install Python dependencies

```powershell
cd AF-SDK-Getting-Started-Guide\aveva-docs-kb
pip install -r requirements.txt
```

> First run downloads the `all-MiniLM-L6-v2` model (~80 MB).

### 2. Build the index

```powershell
python index_docs.py
```

- Walks all `.md` files under `D:\skills\website-building\aveva_docs_scraper\aveva-docs`
- Embeds and stores chunks in `.\chroma_db\` (expect ~500 MB for 10 GB of docs)
- **Re-running is safe** — only new or changed files are re-processed (hash-tracked)
- First run on 10 GB will take **30-90 minutes** depending on your CPU

### 3. Wire up Claude Code

Add the MCP server to Claude Code settings. Two options:

**Option A — global (works in every project)**

Edit `%APPDATA%\Claude\claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "aveva-docs": {
      "command": "python",
      "args": ["D:\\dev\\AF-SDK-Getting-Started-Guide\\aveva-docs-kb\\mcp_server.py"]
    }
  }
}
```

**Option B — this project only**

Create `.claude\settings.json` at the repo root:

```json
{
  "mcpServers": {
    "aveva-docs": {
      "command": "python",
      "args": ["aveva-docs-kb\\mcp_server.py"]
    }
  }
}
```

> Adjust the path to match where you cloned this repo.

### 4. Restart Claude Code

The MCP server starts automatically. You'll see `aveva-docs` listed in `/mcp`.

---

## Usage

Just ask normally — Claude will call `search_aveva_docs` automatically when you
mention AVEVA, PI, AF, PI Points, tags, PI Vision, PI Web API, etc.

```
You: How do I create an AF Element with attributes using the AF SDK?
Claude: [searches local docs → returns relevant chunks → answers]
```

You can also trigger it explicitly:

```
You: Search the AVEVA docs for "event frame templates"
```

---

## Adding more documents

Drop new `.md` files anywhere under the docs folder, then re-run:

```powershell
python index_docs.py
```

Only the new files are indexed; existing ones are skipped (hash check).

---

## Disk usage

| Item | Size |
|------|------|
| Source `.md` files | ~10 GB |
| ChromaDB index | ~400-600 MB |
| Embedding model | ~80 MB |

The index lives at `aveva-docs-kb\chroma_db\` — add it to `.gitignore`
(it's already excluded via the pattern below).
