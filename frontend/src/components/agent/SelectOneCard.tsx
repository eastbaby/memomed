import type { InteractionRequest, SelectOption } from '@/types/agent'

export function SelectOneCard({
  interaction,
  disabled,
  onSelect,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onSelect: (option: SelectOption) => void
}) {
  return (
    <section className="rounded-3xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">需要你确认</p>
      <h2 className="mt-2 text-lg font-semibold text-stone-950">{interaction.title}</h2>
      {interaction.description ? <p className="mt-1 text-sm text-stone-600">{interaction.description}</p> : null}
      <div className="mt-4 grid grid-cols-2 gap-3">
        {(interaction.options ?? []).map((option) => (
          <button
            key={option.value}
            disabled={disabled}
            onClick={() => onSelect(option)}
            className="rounded-2xl border border-amber-200 bg-white px-4 py-3 text-left font-medium text-stone-900 transition hover:-translate-y-0.5 hover:border-amber-400 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60"
          >
            {option.label}
          </button>
        ))}
      </div>
    </section>
  )
}
