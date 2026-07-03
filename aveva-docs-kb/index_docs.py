"""
One-time indexer: walks all .md files under DOCS_DIR, chunks them,
embeds with a local sentence-transformers model, and stores in ChromaDB.

Usage (from this folder):
    python index_docs.py

Re-running is safe — it upserts, so only new/changed files are re-embedded.
"""

import os
import hashlib
import json
import re
from pathlib import Path
from tqdm import tqdm
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

# ── Configuration ────────────────────────────────────────────────────────────
DOCS_DIR   = Path(r"D:\skills\website-building\aveva_docs_scraper\aveva-docs")
DB_DIR     = Path(__file__).parent / "chroma_db"
MODEL_NAME = "all-MiniLM-L6-v2"   # ~80MB, fast, good quality
CHUNK_SIZE  = 600    # target tokens per chunk  (≈ 2400 chars)
CHUNK_OVERLAP = 80  # token overlap between consecutive chunks
COLLECTION  = "aveva_docs"
# ─────────────────────────────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def split_markdown(text: str, source: str) -> list[dict]:
    """
    Split a markdown document into semantic chunks.
    Tries to break on headers first; falls back to paragraph breaks,
    then hard-splits oversized paragraphs.
    """
    chunks = []

    # Split on level-1 / level-2 / level-3 headers, keeping the header line
    sections = re.split(r"(?m)^(#{1,3} .+)$", text)

    current_header = ""
    buffer = ""

    def flush(buf: str, header: str):
        buf = buf.strip()
        if not buf:
            return
        # Further split if still too large
        if estimate_tokens(buf) <= CHUNK_SIZE:
            chunks.append({"text": buf, "header": header, "source": source})
            return
        # Split on blank lines (paragraphs)
        paras = re.split(r"\n{2,}", buf)
        sub_buf = ""
        for para in paras:
            if estimate_tokens(sub_buf) + estimate_tokens(para) > CHUNK_SIZE:
                if sub_buf.strip():
                    chunks.append({"text": sub_buf.strip(), "header": header, "source": source})
                sub_buf = para
            else:
                sub_buf = (sub_buf + "\n\n" + para).strip()
        if sub_buf.strip():
            chunks.append({"text": sub_buf.strip(), "header": header, "source": source})

    for part in sections:
        if re.match(r"^#{1,3} ", part):
            flush(buffer, current_header)
            current_header = part.strip()
            buffer = current_header + "\n"
        else:
            buffer += part

    flush(buffer, current_header)
    return chunks


def file_hash(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    print(f"Loading embedding model '{MODEL_NAME}' (downloads ~80MB on first run)…")
    model = SentenceTransformer(MODEL_NAME)

    DB_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    # Track already-indexed file hashes to skip unchanged files
    meta_file = DB_DIR / "indexed_hashes.json"
    indexed: dict[str, str] = {}
    if meta_file.exists():
        indexed = json.loads(meta_file.read_text())

    md_files = list(DOCS_DIR.rglob("*.md"))
    print(f"Found {len(md_files):,} .md files under {DOCS_DIR}")

    new_chunks_total = 0
    skipped = 0

    for md_path in tqdm(md_files, desc="Indexing", unit="file"):
        rel = str(md_path.relative_to(DOCS_DIR))
        fhash = file_hash(md_path)

        if indexed.get(rel) == fhash:
            skipped += 1
            continue

        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"  Skip {rel}: {e}")
            continue

        chunks = split_markdown(text, source=rel)
        if not chunks:
            continue

        texts    = [c["text"]   for c in chunks]
        ids      = [f"{rel}::{i}" for i in range(len(chunks))]
        metadatas = [{"source": c["source"], "header": c["header"]} for c in chunks]

        embeddings = model.encode(texts, batch_size=64, show_progress_bar=False).tolist()

        # Upsert in batches of 500 (ChromaDB limit)
        batch = 500
        for start in range(0, len(ids), batch):
            collection.upsert(
                ids=ids[start:start+batch],
                documents=texts[start:start+batch],
                embeddings=embeddings[start:start+batch],
                metadatas=metadatas[start:start+batch],
            )

        indexed[rel] = fhash
        new_chunks_total += len(chunks)

    meta_file.write_text(json.dumps(indexed, indent=2))

    total_in_db = collection.count()
    print(f"\nDone. {len(md_files)-skipped} files processed, {skipped} unchanged skipped.")
    print(f"New chunks added this run : {new_chunks_total:,}")
    print(f"Total chunks in DB        : {total_in_db:,}")
    print(f"Index stored at           : {DB_DIR.resolve()}")


if __name__ == "__main__":
    main()
