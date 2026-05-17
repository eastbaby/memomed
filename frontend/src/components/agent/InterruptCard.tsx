import type { InteractionRequest, SelectOption } from '@/types/agent'
import { ConfirmCard } from './ConfirmCard'
import { SelectOneCard } from './SelectOneCard'
import { TextInputCard } from './TextInputCard'

export function InterruptCard({
  interaction,
  disabled,
  onDecision,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onDecision: (decision: Record<string, unknown>) => void
}) {
  if (interaction.type === 'select_one') {
    return (
      <SelectOneCard
        interaction={interaction}
        disabled={disabled}
        onSelect={(option: SelectOption) => onDecision({ value: option.value, label: option.label })}
      />
    )
  }

  if (interaction.type === 'confirm') {
    return <ConfirmCard interaction={interaction} disabled={disabled} onConfirm={(confirmed) => onDecision({ confirmed })} />
  }

  return <TextInputCard interaction={interaction} disabled={disabled} onSubmit={(value) => onDecision({ value })} />
}
