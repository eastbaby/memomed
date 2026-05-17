import { Bot, User } from 'lucide-react'
import type { AgentEvent } from '@/types/agent'
import { ProcessEventCard } from './ProcessEventCard'

export function ChatTimeline({ events }: { events: AgentEvent[] }) {
  const workItemGroups = groupWorkItemEvents(events)

  return (
    <div className="space-y-5">
      {events.map((event) => {
        if (event.event_type === 'message.user') {
          return <MessageBubble key={event.id} role="user" content={event.content ?? ''} />
        }

        if (event.event_type === 'message.assistant.completed') {
          return <MessageBubble key={event.id} role="assistant" content={event.content ?? ''} />
        }

        if (event.event_type === 'process.group.started') {
          const groupKey = workItemKey(event)
          const workItem = workItemGroups.get(groupKey)
          if (!workItem || workItem.firstGroupId !== event.id) return null
          return <ProcessEventCard key={groupKey} group={workItem.group} events={workItem.children} />
        }

        return null
      })}
    </div>
  )
}

function MessageBubble({ role, content }: { role: 'user' | 'assistant'; content: string }) {
  return (
    <div className={`flex gap-3 ${role === 'user' ? 'justify-end' : 'justify-start'}`}>
      {role === 'assistant' ? <Bot className="mt-2 text-teal-700" size={20} /> : null}
      <div className={`max-w-[78%] rounded-3xl px-5 py-3 shadow-sm ${role === 'user' ? 'bg-stone-950 text-white' : 'border border-stone-200 bg-white text-stone-950'}`}>
        {content}
      </div>
      {role === 'user' ? <User className="mt-2 text-stone-700" size={20} /> : null}
    </div>
  )
}

function groupWorkItemEvents(events: AgentEvent[]) {
  const grouped = new Map<string, { firstGroupId: string; group: AgentEvent; children: AgentEvent[] }>()

  for (const event of events) {
    if (event.event_type !== 'process.group.started') continue
    const key = workItemKey(event)
    const current = grouped.get(key)
    if (current) {
      current.group = event
      continue
    }
    grouped.set(key, { firstGroupId: event.id, group: event, children: [] })
  }

  for (const event of events) {
    if (event.event_type !== 'process.step') continue
    const key = workItemKey(event)
    const current = grouped.get(key)
    if (!current) continue
    current.children.push(event)
  }

  return grouped
}

function workItemKey(event: AgentEvent) {
  return event.work_item_id ?? event.parent_event_id ?? event.id
}
