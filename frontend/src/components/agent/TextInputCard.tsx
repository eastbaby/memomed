import { useState } from 'react'
import type { InteractionRequest } from '@/types/agent'

export function TextInputCard({
  interaction,
  disabled,
  onSubmit,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onSubmit: (value: string) => void
}) {
  const [value, setValue] = useState('')

  return (
    <section className="rounded-3xl border border-lime-200 bg-lime-50 p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-stone-950">{interaction.title}</h2>
      {interaction.description ? <p className="mt-1 text-sm text-stone-600">{interaction.description}</p> : null}
      <div className="mt-4 flex gap-2">
        <input
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          placeholder={interaction.placeholder ?? '请输入补充信息'}
          className="min-w-0 flex-1 rounded-xl border border-lime-200 bg-white px-4 py-2 outline-none focus:border-lime-500"
        />
        <button
          disabled={disabled || !value.trim()}
          onClick={() => onSubmit(value)}
          className="rounded-xl bg-lime-700 px-4 py-2 text-white disabled:opacity-60"
        >
          提交
        </button>
      </div>
    </section>
  )
}
