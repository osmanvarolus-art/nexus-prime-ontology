"""Dump the extracted concepts in graph.db to ontology/extracted.json for the Ontoloji screen.

The file holds book quotes, so it is git-ignored; the screen works without it (it just shows the skeleton).
Run after book_ingest.py: python3 ontology/export_json.py
"""
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
db = sqlite3.connect(HERE / "graph.db")

concepts = {}
for id_, isim in db.execute("SELECT id, isim FROM nodes WHERE type = 'Cikarilmis_Kavram'"):
    concepts[id_] = {"isim": isim, "alinti": "", "rels": [], "in": 0}
for node_id, value in db.execute("SELECT node_id, value FROM node_props WHERE key = 'alinti'"):
    if node_id in concepts:
        concepts[node_id]["alinti"] = value

levels = {}  # skeleton level node -> concept ids, most connected first
for lvl, cid in db.execute("SELECT kaynak_id, hedef_id FROM edges WHERE iliski_tipi = 'seviye_altinda'"):
    levels.setdefault(lvl, []).append(cid)
# for relation edges the `kural` column holds the quote that grounds the relation
for src, dst, tip, alinti in db.execute(
        "SELECT kaynak_id, hedef_id, iliski_tipi, kural FROM edges "
        "WHERE iliski_tipi NOT IN ('seviye_altinda', 'bilissel_gecis', 'nuzul_to_uruc')"):
    if src in concepts and dst in concepts:
        concepts[src]["rels"].append({"tip": tip, "hedef": dst, "alinti": alinti})
        concepts[dst]["in"] += 1
degree = lambda c: len(concepts[c]["rels"]) + concepts[c]["in"]
for ids in levels.values():
    ids.sort(key=lambda c: (-degree(c), concepts[c]["isim"]))

out = HERE / "extracted.json"
out.write_text(json.dumps({"levels": levels, "concepts": concepts}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"wrote {out.name}: {len(concepts)} concepts, {sum(len(v) for v in levels.values())} level links, {out.stat().st_size // 1024} KB")
