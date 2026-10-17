/// <reference types="vite/client" />
import React, { useState } from 'react';
import graph from '../ontology/graph.json';

type Node = (typeof graph.nodes)[number];
type Rel = { tip: string; hedef: string; alinti: string };
type Concept = { isim: string; alinti: string; rels: Rel[]; in: number };
type Extracted = { levels: Record<string, string[]>; concepts: Record<string, Concept> };

// ontology/extracted.json is made by export_json.py and holds book quotes (git-ignored). Missing file = skeleton only.
const files = import.meta.glob('../ontology/extracted.json', { eager: true, import: 'default' }) as Record<string, Extracted>;
const extracted: Extracted | undefined = Object.values(files)[0];

const byId = new Map<string, Node>(graph.nodes.map(n => [n.id, n]));
const nextEdge = new Map(graph.edges.map(e => [e.kaynak_id, e]));

// Follows the edges from the root, so the order on screen is the graph's own order, not the file order.
const chain: { node: Node; via?: (typeof graph.edges)[number] }[] = [];
for (let id: string | undefined = 'kavram_000_root', via: (typeof graph.edges)[number] | undefined; id; ) {
  const node = byId.get(id);
  if (!node || chain.some(c => c.node.id === id)) break;
  chain.push({ node, via });
  via = nextEdge.get(id);
  id = via?.hedef_id;
}

const PAGE = 30;
const REL_LABEL: Record<string, string> = { mevzu_mahmul: 'mevzu-mahmul', cuz_kull: 'cüz-küll', sebep_sonuc: 'sebep-sonuç' };

const ConceptList: React.FC<{ ids: string[] }> = ({ ids }) => {
  const [q, setQ] = useState('');
  const [shown, setShown] = useState(PAGE);
  const needle = q.trim().toLocaleLowerCase('tr');
  const hits = needle ? ids.filter(id => extracted!.concepts[id].isim.toLocaleLowerCase('tr').includes(needle)) : ids;
  return (
    <div className="mt-3 border-t border-slate-800 pt-3">
      <input
        value={q}
        onChange={e => { setQ(e.target.value); setShown(PAGE); }}
        placeholder={`${ids.length} kavram içinde ara...`}
        aria-label="Kavram ara"
        className="w-full mb-2 bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
      <ul className="space-y-1">
        {hits.slice(0, shown).map(id => {
          const c = extracted!.concepts[id];
          return (
            <li key={id} className="rounded bg-slate-950/60 px-3 py-2">
              <details>
                <summary className="cursor-pointer text-sm text-slate-200">
                  {c.isim}
                  <span className="ml-2 text-[10px] font-mono text-slate-600">{c.rels.length + c.in} bağ</span>
                </summary>
                <p className="mt-1 text-xs text-slate-400 italic">“{c.alinti}”</p>
                {c.rels.map((r, i) => (
                  <p key={i} className="mt-1 text-[11px] font-mono text-indigo-300">
                    {REL_LABEL[r.tip] ?? r.tip} → <span className="text-slate-300">{extracted!.concepts[r.hedef].isim}</span>
                  </p>
                ))}
              </details>
            </li>
          );
        })}
      </ul>
      {hits.length === 0 && <p className="text-xs text-slate-500">Eşleşme yok.</p>}
      {hits.length > shown && (
        <button onClick={() => setShown(s => s + PAGE)} className="mt-2 text-xs text-indigo-300 hover:text-indigo-200">
          {Math.min(PAGE, hits.length - shown)} tane daha göster ({hits.length - shown} kaldı)
        </button>
      )}
    </div>
  );
};

export const OntologyView: React.FC = () => {
  const [open, setOpen] = useState<string | null>(null);
  const total = extracted ? Object.keys(extracted.concepts).length : 0;
  return (
    <div data-testid="ontology-view" className="p-6 max-w-3xl mx-auto">
      <p className="text-xs font-mono text-slate-500 mb-4">
        {graph.nodes.length} iskelet kavram · {graph.edges.length} geçiş
        {extracted && <> · kitaptan çıkarılan {total} kavram</>} · kaynak: {chain[0]?.node.meta_veri.kaynak}
      </p>
      <ol className="space-y-0">
        {chain.map(({ node, via }) => {
          const ids = extracted?.levels[node.id] ?? [];
          return (
            <li key={node.id}>
              {via && (
                <div className="ml-6 pl-4 py-2 border-l border-indigo-500/40 text-[11px] font-mono text-indigo-300">
                  ↓ {via.kural.replace(/_/g, ' ')} <span className="text-slate-600">({via.iliski_tipi})</span>
                </div>
              )}
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <h3 className="text-base font-semibold text-white">{node.isim}</h3>
                  <span className="text-[10px] font-mono text-slate-500">{node.meta_veri.bilissel_seviye.replace(/_/g, ' ')}</span>
                  <span className="text-[10px] font-mono text-slate-600">{node.meta_veri.ontolojik_yon}</span>
                  {ids.length > 0 && (
                    <button
                      onClick={() => setOpen(open === node.id ? null : node.id)}
                      aria-expanded={open === node.id}
                      className="ml-auto text-xs px-2 py-0.5 rounded-full border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/10"
                    >
                      {ids.length} kavram {open === node.id ? '▲' : '▼'}
                    </button>
                  )}
                </div>
                {'sonuc' in node.meta_veri && (
                  <p className="mt-1 text-sm text-slate-400">Sonuç: <span className="text-amber-400">{(node.meta_veri as { sonuc: string }).sonuc}</span></p>
                )}
                {open === node.id && <ConceptList ids={ids} />}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
