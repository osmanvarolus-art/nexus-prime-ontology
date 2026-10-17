"""Load graph.json into a SQLite graph (stdlib only) and verify root -> leaf traversal.

ponytail: no graph DB engine is installed on this machine, so nodes/edges are tables and
traversal is a recursive CTE. Swap the INSERT blocks if a real graph engine is adopted.
"""
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
ROOT, LEAF = "kavram_000_root", "kavram_007_itikad"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, isim TEXT NOT NULL);
CREATE TABLE node_props (node_id TEXT NOT NULL REFERENCES nodes(id), key TEXT NOT NULL, value TEXT NOT NULL,
                         PRIMARY KEY (node_id, key));
CREATE TABLE edges (kaynak_id TEXT NOT NULL REFERENCES nodes(id), hedef_id TEXT NOT NULL REFERENCES nodes(id),
                    iliski_tipi TEXT NOT NULL, kural TEXT NOT NULL, PRIMARY KEY (kaynak_id, hedef_id));
"""

WALK = """
WITH RECURSIVE walk(id, path, depth) AS (
  SELECT :root, :root, 0
  UNION ALL
  SELECT e.hedef_id, walk.path || ' > ' || e.hedef_id, walk.depth + 1
  FROM walk JOIN edges e ON e.kaynak_id = walk.id
  WHERE walk.depth < 20
)
"""


def ingest(db: sqlite3.Connection, data: dict) -> None:
    db.executescript(SCHEMA)
    for n in data["nodes"]:
        db.execute("INSERT INTO nodes VALUES (?, ?, ?)", (n["id"], n["type"], n["isim"]))
        db.executemany("INSERT INTO node_props VALUES (?, ?, ?)",
                       [(n["id"], k, v) for k, v in n["meta_veri"].items()])
    db.executemany("INSERT INTO edges VALUES (?, ?, ?, ?)",
                   [(e["kaynak_id"], e["hedef_id"], e["iliski_tipi"], e["kural"]) for e in data["edges"]])
    db.commit()


def verify(db: sqlite3.Connection, data: dict) -> tuple[str, int]:
    count = lambda t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    want_props = sum(len(n["meta_veri"]) for n in data["nodes"])
    assert (count("nodes"), count("edges"), count("node_props")) == (len(data["nodes"]), len(data["edges"]), want_props), \
        "row counts differ from graph.json"
    rows = db.execute(WALK + "SELECT path, depth FROM walk WHERE id = :leaf", {"root": ROOT, "leaf": LEAF}).fetchall()
    assert rows, f"no path from {ROOT} to {LEAF}"
    path, depth = rows[0]
    assert depth == len(data["nodes"]) - 1, "path skips nodes"
    reached = db.execute(WALK + "SELECT COUNT(DISTINCT id) FROM walk", {"root": ROOT}).fetchone()[0]
    assert reached == len(data["nodes"]), "orphan node not reachable from root"
    return path, depth


if __name__ == "__main__":
    data = json.loads((HERE / "graph.json").read_text(encoding="utf-8"))
    out = HERE / "graph.db"
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    ingest(db, data)
    path, depth = verify(db, data)
    print(f"OK nodes={len(data['nodes'])} edges={len(data['edges'])} depth={depth}")
    print(path.replace(" > ", "\n  > "))
