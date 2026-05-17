import type { InteractionRequest } from '@/types/agent'

export function ConfirmCard({
  interaction,
  disabled,
  onConfirm,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onConfirm: (confirmed: boolean) => void
}) {
  return (
    <section className="rounded-3xl border border-sky-200 bg-sky-50 p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-stone-950">{interaction.title}</h2>
      {interaction.description ? <p className="mt-1 text-sm text-stone-600">{interaction.description}</p> : null}
      <div className="mt-4 flex gap-3">
        <button
          disabled={disabled}
          onClick={() => onConfirm(true)}
          className="rounded-xl bg-sky-700 px-4 py-2 text-white disabled:opacity-60"
        >
          确认
        </button>
        <button
          disabled={disabled}
          onClick={() => onConfirm(false)}
          className="rounded-xl border border-sky-200 bg-white px-4 py-2 text-sky-900 disabled:opacity-60"
        >
          取消
        </button>
      </div>
    </section>
  )
}
