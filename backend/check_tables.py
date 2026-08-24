"""Assert the Card C project-tree tables exist in the configured SQLite DB."""

import os
import sqlite3
import sys

EXPECT = {"project_nodes", "project_node_references", "references"}
url = os.environ.get("DATABASE_URL", "sqlite:///bibliogon.db")
if not url.startswith("sqlite:///"):
    raise SystemExit(f"Only sqlite URLs are supported: {url}")
path = url.removeprefix("sqlite:///")
with sqlite3.connect(path) as db:
    got = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
missing = EXPECT - got
print("database:", path)
print("present:", sorted(EXPECT & got))
print("missing:", sorted(missing))
sys.exit(1 if missing else 0)
