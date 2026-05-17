import { ChevronDown, CircleAlert, Sparkles, Wrench } from 'lucide-react'
import type { AgentEvent } from '@/types/agent'

export function ProcessEventCard({ group, events }: { group: AgentEvent; events: AgentEvent[] }) {
  if (events.length === 0) return null
  const latest = events[events.length - 1]
  const hasError = events.some((event) => event.status === 'failed')

  return (
    <details className={`group rounded-2xl border text-sm shadow-sm ${hasError ? 'border-red-200/80 bg-red-50 text-red-950' : 'border-teal-200/70 bg-teal-50 text-teal-950'}`}>
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3">
        <span className={`rounded-xl bg-white/80 p-2 shadow-sm ${hasError ? 'text-red-600' : 'text-teal-700'}`}>
          <Sparkles size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 font-semibold">
            <span>{group.title ?? 'Agent 过程'}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${hasError ? 'bg-red-100 text-red-700' : 'bg-teal-100 text-teal-700'}`}>{events.length} 条</span>
          </div>
          <p className={`truncate ${hasError ? 'text-red-900/70' : 'text-teal-900/70'}`}>{latest.content ?? group.content}</p>
        </div>
        <ChevronDown className="shrink-0 transition group-open:rotate-180" size={18} />
      </summary>
      <div className={`space-y-2 border-t px-4 py-3 ${hasError ? 'border-red-200/70' : 'border-teal-200/70'}`}>
        {events.map((event) => (
          <div key={event.id} className="flex gap-3 rounded-xl bg-white/70 px-3 py-2">
            <span className={event.status === 'failed' ? 'mt-0.5 text-red-600' : 'mt-0.5 text-teal-700'}>
              {event.status === 'failed' ? <CircleAlert size={15} /> : <Wrench size={15} />}
            </span>
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-400">{eventLabel(event)}</p>
              <p className={event.status === 'failed' ? 'text-red-700' : 'text-stone-700'}>{event.content}</p>
            </div>
          </div>
        ))}
      </div>
    </details>
  )
}

function eventLabel(event: AgentEvent) {
  if (event.status === 'failed') return 'Error'
  if (event.title) return event.title
  return 'Thinking'
}
