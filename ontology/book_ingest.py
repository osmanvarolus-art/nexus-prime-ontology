"""Extract concepts from the books in drive_sources/ and attach them to the 8-node skeleton in graph.db.

Flow: read .txt/.md/.pdf -> chunk -> local LLM returns concepts + relations as JSON -> keep only what is
grounded in the chunk (the quoted sentence must occur in the text) -> insert under the skeleton.

Rules that keep the skeleton intact:
  * the 8 skeleton nodes are never changed or deleted;
  * every extracted concept gets an edge FROM the skeleton node of its cognitive level (1..7), so each one is
    reachable from kavram_000_root;
  * relations between extracted concepts are typed mevzu_mahmul / cuz_kull / sebep_sonuc.

Run ontology/ingest.py first (it creates graph.db), then: python3 ontology/book_ingest.py [--selftest]

ponytail: the cognitive level is the model's judgement, not a fact; the quote is kept on every node so a
human can audit it. Re-running is safe (ids come from the concept name; INSERT OR IGNORE).
"""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SOURCES = HERE.parent / "drive_sources"
DB = HERE / "graph.db"
LLM_URL, LLM_MODEL = "http://127.0.0.1:8081/v1/chat/completions", "bonsai-27b"
CHUNK = 1800

LEVELS = {1: ("kavram_001_tahayyul", "Tahayyul"), 2: ("kavram_002_tasavvur", "Tasavvur"),
          3: ("kavram_003_taakkul", "Taakkul"), 4: ("kavram_004_tasdik", "Tasdik"),
          5: ("kavram_005_izan", "Izan"), 6: ("kavram_006_iltizam", "Iltizam"), 7: ("kavram_007_itikad", "Itikad")}
REL_TYPES = ["mevzu_mahmul", "cuz_kull", "sebep_sonuc"]

SCHEMA = {"type": "object", "required": ["concepts", "relations"], "properties": {
    "concepts": {"type": "array", "items": {"type": "object", "required": ["isim", "seviye", "alinti"], "properties": {
        "isim": {"type": "string"}, "seviye": {"type": "integer", "minimum": 1, "maximum": 7}, "alinti": {"type": "string"}}}},
    "relations": {"type": "array", "items": {"type": "object", "required": ["kaynak", "hedef", "tip", "alinti"], "properties": {
        "kaynak": {"type": "string"}, "hedef": {"type": "string"}, "alinti": {"type": "string"},
        "tip": {"type": "string", "enum": REL_TYPES}}}}}}

PROMPT = """Aşağıdaki kitap bölümünden kavramları çıkar. Sadece metinde geçenleri yaz, uydurma.
- concepts: her kavram için isim (metindeki haliyle), seviye ve alinti. alinti metinden AYNEN kopyalanmış tek bir cümle olmalı.
- seviye (bilişsel seviye): """ + "; ".join(f"{k}={v[1]}" for k, v in LEVELS.items()) + """.
  Kavramın metinde hangi bilişsel basamakta ele alındığını seç.
- relations: iki kavram arasındaki ilişki. tip: mevzu_mahmul (özne-yüklem, bir şeyin bir şey olduğu), cuz_kull (parça-bütün),
  sebep_sonuc (neden-sonuç). kaynak ve hedef concepts içindeki isimlerden biri olmalı. alinti metinden aynen bir cümle.
En fazla 8 kavram ve 8 ilişki yaz; alıntılar tek cümle olsun. Metinde kavram yoksa boş liste döndür.

METİN:
"""


def read_source(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
    return path.read_text(encoding="utf-8", errors="replace")


def chunks(text: str, size: int = CHUNK):
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", text)  # PDF line-break hyphens: "olan-\nlarını" -> "olanlarını"
    buf = ""
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        if buf and len(buf) + len(para) > size:
            yield buf
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
        while len(buf) > size * 2:  # one huge paragraph
            yield buf[:size]
            buf = buf[size:]
    if buf:
        yield buf


def ask_llm(prompt: str) -> dict:
    body = {"model": LLM_MODEL, "temperature": 0.1, "max_tokens": 4000,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "concepts", "strict": True, "schema": SCHEMA}}}
    req = urllib.request.Request(LLM_URL, json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.loads(r.read())["choices"][0]["message"]["content"])


norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
cid = lambda isim: "ext_" + hashlib.sha1(norm(isim).encode()).hexdigest()[:10]


def extract(chunk: str, source: str, ask=ask_llm):
    """Returns (concepts, relations, dropped). Anything whose quote is not in the chunk is dropped."""
    data, flat = ask(PROMPT + chunk), norm(chunk)
    grounded = lambda q: len(norm(q)) >= 8 and norm(q) in flat
    concepts, dropped = {}, 0
    for c in data.get("concepts", []):
        isim = c["isim"].strip()
        if isim and c["seviye"] in LEVELS and grounded(c["alinti"]):
            concepts.setdefault(cid(isim), {"id": cid(isim), "isim": isim, "seviye": c["seviye"], "alinti": c["alinti"].strip(), "dosya": source})
        else:
            dropped += 1
    relations = []
    for r in data.get("relations", []):
        a, b = cid(r["kaynak"]), cid(r["hedef"])
        if a in concepts and b in concepts and a != b and r["tip"] in REL_TYPES and grounded(r["alinti"]):
            relations.append({"kaynak": a, "hedef": b, "tip": r["tip"], "alinti": r["alinti"].strip()})
        else:
            dropped += 1
    return list(concepts.values()), relations, dropped


def extract_split(chunk: str, source: str, ask=ask_llm):
    """extract(), but a cut-off model reply (bad JSON) is retried on each half of the chunk instead of lost."""
    try:
        return extract(chunk, source, ask)
    except json.JSONDecodeError:
        if len(chunk) < 400:
            raise
        mid = chunk.rfind(" ", 0, len(chunk) // 2) or len(chunk) // 2
        a, b = extract_split(chunk[:mid], source, ask), extract_split(chunk[mid:], source, ask)
        merged = {c["id"]: c for c in a[0] + b[0]}
        return list(merged.values()), a[1] + b[1], a[2] + b[2]


def insert(db: sqlite3.Connection, concepts, relations) -> tuple[int, int]:
    n = e = 0
    for c in concepts:
        level_id, level_name = LEVELS[c["seviye"]]
        n += db.execute("INSERT OR IGNORE INTO nodes VALUES (?, 'Cikarilmis_Kavram', ?)", (c["id"], c["isim"])).rowcount
        db.executemany("INSERT OR IGNORE INTO node_props VALUES (?, ?, ?)", [
            (c["id"], "bilissel_seviye", f"{c['seviye']}_{level_name}"), (c["id"], "alinti", c["alinti"]),
            (c["id"], "kaynak_dosya", c["dosya"]), (c["id"], "ontolojik_yon", "Kavs-i Uruc")])
        e += db.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, 'seviye_altinda', 'iskelet_seviyesine_baglanti')",
                        (level_id, c["id"])).rowcount
    for r in relations:
        e += db.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?)", (r["kaynak"], r["hedef"], r["tip"], r["alinti"])).rowcount
    return n, e


def check_links(db: sqlite3.Connection) -> None:
    orphans = db.execute("""SELECT id FROM nodes WHERE type='Cikarilmis_Kavram' AND id NOT IN
                            (SELECT hedef_id FROM edges WHERE iliski_tipi='seviye_altinda')""").fetchall()
    assert not orphans, f"concepts not linked to the skeleton: {orphans}"
    assert db.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE 'kavram_%'").fetchone()[0] == 8, "skeleton changed"


def selftest() -> None:
    import tempfile
    sys.path.insert(0, str(HERE))
    import ingest
    text = "Tasdik kabul etmektir. Akıl bir parçadır, insan ise bütün."
    fake = lambda _: {"concepts": [{"isim": "Tasdik", "seviye": 4, "alinti": "Tasdik kabul etmektir."},
                                   {"isim": "Uydurma", "seviye": 2, "alinti": "Bu cümle metinde yok."}],
                      "relations": [{"kaynak": "Tasdik", "hedef": "Uydurma", "tip": "sebep_sonuc", "alinti": "Tasdik kabul etmektir."}]}
    concepts, relations, dropped = extract(text, "t.md", fake)
    assert [c["isim"] for c in concepts] == ["Tasdik"] and not relations and dropped == 2, (concepts, relations, dropped)
    with tempfile.TemporaryDirectory() as d:
        db = sqlite3.connect(Path(d) / "g.db")
        ingest.ingest(db, json.loads((HERE / "graph.json").read_text(encoding="utf-8")))
        assert insert(db, concepts, relations) == (1, 1) and insert(db, concepts, relations) == (0, 0)  # idempotent
        check_links(db)
    print("selftest OK: ungrounded quotes dropped, concept linked under its level, re-run adds nothing")


def main() -> None:
    files = sorted(p for p in SOURCES.glob("**/*") if p.suffix.lower() in {".txt", ".md", ".pdf"})
    if not files:
        sys.exit(f"No .txt/.md/.pdf files in {SOURCES}. Drop the books there first.")
    if not DB.exists():
        sys.exit("graph.db missing. Run: python3 ontology/ingest.py")
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys = ON")
    tot_n = tot_e = tot_d = 0
    for f in files:
        parts = list(chunks(read_source(f)))
        print(f"{f.name}: {len(parts)} chunks", flush=True)
        for i, part in enumerate(parts, 1):
            try:
                concepts, relations, dropped = extract_split(part, f.name)
            except Exception as err:  # one bad chunk must not lose the rest of the book
                print(f"  chunk {i}: skipped ({type(err).__name__}: {err})")
                continue
            n, e = insert(db, concepts, relations)
            db.commit()
            tot_n, tot_e, tot_d = tot_n + n, tot_e + e, tot_d + dropped
            print(f"  chunk {i}/{len(parts)}: +{n} concepts +{e} edges, {dropped} ungrounded dropped", flush=True)
    check_links(db)
    print(f"DONE new concepts={tot_n} new edges={tot_e} dropped={tot_d}; all linked under the skeleton")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
