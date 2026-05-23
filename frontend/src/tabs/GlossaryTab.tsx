import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, Trash2, Check, X as XIcon, BookOpen } from 'lucide-react'
import { listTerms, createTerm, updateTerm, deleteTerm } from '../api/glossary'
import { LoadingOverlay } from '../components/common/LoadingSpinner'
import type { GlossaryTerm } from '../types'

export function GlossaryTab() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)
  const [newTerm, setNewTerm] = useState({ term: '', definition: '', example: '' })
  const [editing, setEditing] = useState<number | null>(null)
  const [editVals, setEditVals] = useState({ term: '', definition: '', example: '' })

  const { data: terms, isLoading } = useQuery({ queryKey: ['glossary'], queryFn: listTerms })

  const createMut = useMutation({
    mutationFn: createTerm,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['glossary'] }); setAdding(false); setNewTerm({ term: '', definition: '', example: '' }) },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, ...rest }: { id: number; term: string; definition: string; example: string }) =>
      updateTerm(id, rest),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['glossary'] }); setEditing(null) },
  })

  const deleteMut = useMutation({
    mutationFn: deleteTerm,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glossary'] }),
  })

  function startEdit(t: GlossaryTerm) {
    setEditing(t.id)
    setEditVals({ term: t.term, definition: t.definition, example: t.example ?? '' })
  }

  if (isLoading) return <LoadingOverlay label="Loading glossary…" />

  const filtered = (terms ?? []).filter(
    (t) =>
      !search ||
      t.term.toLowerCase().includes(search.toLowerCase()) ||
      t.definition.toLowerCase().includes(search.toLowerCase())
  )

  const defaults = filtered.filter((t) => t.is_default)
  const custom = filtered.filter((t) => !t.is_default)

  return (
    <div className="p-4 flex flex-col gap-4">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search terms…"
          className="flex-1 max-w-xs text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
        <button
          onClick={() => setAdding(true)}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium px-4 py-2 rounded-lg"
        >
          <Plus size={15} /> Add Term
        </button>
      </div>

      {/* Add form */}
      {adding && (
        <div className="bg-brand-50 border border-brand-200 rounded-xl p-4 flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-brand-800">New Term</h3>
          <div className="grid grid-cols-3 gap-3">
            <input value={newTerm.term} onChange={(e) => setNewTerm((p) => ({ ...p, term: e.target.value }))} placeholder="Term" className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500" />
            <input value={newTerm.definition} onChange={(e) => setNewTerm((p) => ({ ...p, definition: e.target.value }))} placeholder="Definition" className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500" />
            <input value={newTerm.example} onChange={(e) => setNewTerm((p) => ({ ...p, example: e.target.value }))} placeholder="Example (optional)" className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500" />
          </div>
          <div className="flex gap-2">
            <button onClick={() => createMut.mutate(newTerm)} disabled={!newTerm.term || !newTerm.definition || createMut.isPending} className="flex items-center gap-1.5 bg-brand-600 text-white text-sm px-3 py-1.5 rounded-lg disabled:opacity-50">
              <Check size={13} /> Save
            </button>
            <button onClick={() => setAdding(false)} className="flex items-center gap-1.5 text-gray-500 text-sm px-3 py-1.5 rounded-lg hover:bg-gray-100">
              <XIcon size={13} /> Cancel
            </button>
          </div>
        </div>
      )}

      {/* Terms list */}
      {[{ label: 'Default Terms', items: defaults }, { label: 'My Terms', items: custom }].map(({ label, items }) =>
        items.length > 0 ? (
          <section key={label}>
            <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">{label}</h2>
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              {items.map((t, i) => (
                <div key={t.id} className={`flex items-start gap-4 px-4 py-3 ${i > 0 ? 'border-t border-gray-100' : ''}`}>
                  <BookOpen size={14} className="mt-0.5 text-brand-500 flex-shrink-0" />
                  {editing === t.id ? (
                    <div className="flex-1 grid grid-cols-3 gap-2">
                      <input value={editVals.term} onChange={(e) => setEditVals((p) => ({ ...p, term: e.target.value }))} className="text-sm border border-gray-200 rounded px-2 py-1" />
                      <input value={editVals.definition} onChange={(e) => setEditVals((p) => ({ ...p, definition: e.target.value }))} className="text-sm border border-gray-200 rounded px-2 py-1" />
                      <input value={editVals.example} onChange={(e) => setEditVals((p) => ({ ...p, example: e.target.value }))} className="text-sm border border-gray-200 rounded px-2 py-1" placeholder="Example" />
                    </div>
                  ) : (
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-semibold text-gray-900">{t.term}</span>
                      {t.is_default && <span className="ml-2 text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">default</span>}
                      <p className="text-sm text-gray-600 mt-0.5">{t.definition}</p>
                      {t.example && <p className="text-xs text-gray-400 mt-0.5 font-mono">{t.example}</p>}
                    </div>
                  )}
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {editing === t.id ? (
                      <>
                        <button onClick={() => updateMut.mutate({ id: t.id, ...editVals })} className="p-1.5 text-green-600 hover:bg-green-50 rounded"><Check size={13} /></button>
                        <button onClick={() => setEditing(null)} className="p-1.5 text-gray-400 hover:bg-gray-50 rounded"><XIcon size={13} /></button>
                      </>
                    ) : (
                      <>
                        {!t.is_default && <button onClick={() => startEdit(t)} className="p-1.5 text-gray-400 hover:text-brand-600 rounded"><Pencil size={13} /></button>}
                        {!t.is_default && <button onClick={() => deleteMut.mutate(t.id)} className="p-1.5 text-gray-400 hover:text-red-500 rounded"><Trash2 size={13} /></button>}
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null
      )}
    </div>
  )
}
