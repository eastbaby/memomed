import { Send } from 'lucide-react'
import { useState } from 'react'

export function Composer({
  disabled,
  onSend,
}: {
  disabled?: boolean
  onSend: (message: string) => void
}) {
  const [value, setValue] = useState('')

  function submit() {
    const message = value.trim()
    if (!message) return
    onSend(message)
    setValue('')
  }

  return (
    <div className="rounded-3xl border border-stone-200 bg-white p-2 shadow-xl shadow-stone-200/70">
      <div className="flex items-center gap-2">
        <input
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit()
          }}
          placeholder="试试：帮家人存一下这个报告"
          className="min-w-0 flex-1 rounded-2xl px-4 py-3 text-stone-950 outline-none"
        />
        <button
          disabled={disabled || !value.trim()}
          onClick={submit}
          className="rounded-2xl bg-teal-700 p-3 text-white transition hover:bg-teal-600 disabled:bg-stone-300"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  )
}
