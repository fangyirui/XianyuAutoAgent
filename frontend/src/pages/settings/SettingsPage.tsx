import { useEffect, useState } from 'react'
import { getPrompts, updatePrompt } from '@/api/config'

interface Prompt { name: string; content: string }

export default function SettingsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [selected, setSelected] = useState<Prompt | null>(null)
  const [editing, setEditing] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getPrompts().then((data) => {
      setPrompts(data)
      if (data.length > 0) { setSelected(data[0]); setEditing(data[0].content) }
    })
  }, [])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    await updatePrompt(selected.name, editing)
    setPrompts((prev) => prev.map((p) => (p.name === selected.name ? { ...p, content: editing } : p)))
    setSaving(false)
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">提示词配置</h2>
      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        <div className="w-48 space-y-1">
          {prompts.map((p) => (
            <button key={p.name} onClick={() => { setSelected(p); setEditing(p.content) }}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm ${selected?.name === p.name ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'}`}>
              {p.name}
            </button>
          ))}
        </div>
        <div className="flex-1 flex flex-col">
          <textarea value={editing} onChange={(e) => setEditing(e.target.value)}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:border-emerald-400" />
          <button onClick={handleSave} disabled={saving}
            className="mt-3 self-end px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
