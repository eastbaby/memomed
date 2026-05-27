import { ChevronRight } from 'lucide-react'
import { formatElapsedSeconds } from '@/lib/elapsedTime'

export function ElapsedStatus({
  elapsedSeconds,
  content,
  collapsed = false,
  onToggle,
}: {
  elapsedSeconds?: number
  content?: string | null
  collapsed?: boolean
  onToggle?: () => void
}) {
  const text = content ?? `已处理 ${formatElapsedSeconds(elapsedSeconds ?? 0)}`
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-fit items-center gap-1 rounded-xl px-1 py-0.5 text-sm font-semibold text-stone-500 transition hover:bg-stone-100 hover:text-stone-700"
      aria-expanded={!collapsed}
    >
      <span>{text}</span>
      <ChevronRight className={`transition ${collapsed ? '' : 'rotate-90'}`} size={16} strokeWidth={2.4} />
    </button>
  )
}
