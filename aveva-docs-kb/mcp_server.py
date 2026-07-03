"""
AVEVA Docs MCP Server
─────────────────────
Exposes a single tool: search_aveva_docs(query, n_results=6)

Claude Code calls this automatically whenever AVEVA/PI/AF topics come up.
The server reads the local ChromaDB index built by index_docs.py.

Start manually (for testing):
    python mcp_server.py

Claude Code launches it automatically via settings.json — no need to
start it yourself during normal use.
"""

import sys
from pathlib import Path

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Missing dependencies. Run:\n"
        "  pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

DB_DIR      = Path(__file__).parent / "chroma_db"
MODEL_NAME  = "all-MiniLM-L6-v2"
COLLECTION  = "aveva_docs"

# ── Lazy-load heavy objects once at startup ───────────────────────────────────
_model: SentenceTransformer | None = None
_collection = None


def _get_collection():
    global _model, _collection
    if _collection is None:
        if not DB_DIR.exists():
            raise RuntimeError(
                f"ChromaDB index not found at {DB_DIR}.\n"
                "Run  python index_docs.py  first to build the index."
            )
        client = chromadb.PersistentClient(path=str(DB_DIR))
        _collection = client.get_collection(COLLECTION)
        _model = SentenceTransformer(MODEL_NAME)
    return _collection, _model


# ── MCP server ────────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="aveva-docs",
    instructions=(
        "Search the local AVEVA / PI System / AF SDK documentation. "
        "Use this tool whenever the user mentions AVEVA, PI, PI AF, AF SDK, "
        "AF Analysis, AF Notifications, AF Elements, PI Points, PI tags, "
        "PI Data Archive, PI Vision, PI Web API, or any related OSIsoft/AVEVA topic."
    ),
)


@mcp.tool()
def search_aveva_docs(query: str, n_results: int = 6) -> str:
    """
    Search the local AVEVA documentation knowledge base.

    Args:
        query:     Natural-language question or keyword search.
        n_results: Number of document chunks to return (default 6).

    Returns:
        Relevant documentation excerpts with source file references.
    """
    collection, model = _get_collection()

    embedding = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=embedding,
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    docs      = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    if not docs:
        return "No relevant documentation found for that query."

    parts = [f"## AVEVA Docs — top {len(docs)} results for: *{query}*\n"]
    for i, (doc, meta, dist) in enumerate(zip(docs, metadatas, distances), 1):
        source  = meta.get("source", "unknown")
        header  = meta.get("header", "")
        score   = round((1 - dist) * 100, 1)  # cosine similarity → %
        heading = f"### [{i}] `{source}`"
        if header:
            heading += f" — {header}"
        heading += f"  *(relevance {score}%)*"
        parts.append(heading)
        parts.append(doc.strip())
        parts.append("")

    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run(transport="stdio")
