"""Add/rebuild the FTS5 index on an existing DB without a full rebuild:  python -m scripts.build_fts"""
import sys

from recipebot.db import connect, db_path
from recipebot.search import build_fts

if __name__ == "__main__":
    conn = connect(db_path())
    print(f"recipes_fts rows: {build_fts(conn):,}")
    conn.close()
    sys.exit(0)
