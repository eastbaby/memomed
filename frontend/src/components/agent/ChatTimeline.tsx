import { useState } from 'react'
import { Bot, User } from 'lucide-react'
import { buildProcessWorkItems } from '@/lib/processWorkItems'
import { timelineEventsWithOptimisticUi, type OptimisticTimelineUi } from '@/lib/optimisticTimelineUi'
import type { AgentEvent } from '@/types/agent'
import { ElapsedStatus } from './ElapsedStatus'
import { MarkdownMessage } from './MarkdownMessage'
import { ProcessEventCard } from './ProcessEventCard'

export function ChatTimeline({
  events,
  optimisticUi = null,
  runningElapsedSeconds = null,
}: {
  events: AgentEvent[]
  optimisticUi?: OptimisticTimelineUi | null
  runningElapsedSeconds?: number | null
}) {
  const [collapsedProcessAnchors, setCollapsedProcessAnchors] = useState<Set<string>>(() => new Set())
  const displayEvents = timelineEventsWithOptimisticUi(events, optimisticUi)
  const workItemGroups = buildProcessWorkItems(displayEvents)
  const runningStatusAnchorId = runningElapsedSeconds === null ? null : latestUserEventId(displayEvents)

  function toggleProcessAnchor(anchorId: string) {
    setCollapsedProcessAnchors((current) => {
      const next = new Set(current)
      if (next.has(anchorId)) {
        next.delete(anchorId)
      } else {
        next.add(anchorId)
      }
      return next
    })
  }

  return (
    <div className="space-y-5">
      {displayEvents.map((event, index) => {
        if (event.event_type === 'message.user') {
          const elapsedEvent = elapsedEventForUserTurn(displayEvents, index)
          const collapsed = collapsedProcessAnchors.has(event.id)
          return (
            <div key={event.id} className="space-y-5">
              <MessageBubble role="user" content={event.content ?? ''} />
              {event.id === runningStatusAnchorId && runningElapsedSeconds !== null ? (
                <ElapsedStatus elapsedSeconds={runningElapsedSeconds} collapsed={collapsed} onToggle={() => toggleProcessAnchor(event.id)} />
              ) : elapsedEvent ? (
                <ElapsedStatus content={elapsedEvent.content} collapsed={collapsed} onToggle={() => toggleProcessAnchor(event.id)} />
              ) : null}
            </div>
          )
        }

        if (event.event_type === 'run.elapsed') {
          return null
        }

        if (event.event_type === 'message.assistant.delta' || event.event_type === 'message.assistant.completed') {
          return <MessageBubble key={event.id} role="assistant" content={event.content ?? ''} streaming={event.event_type === 'message.assistant.delta'} />
        }

        if (event.event_type === 'process.group.started') {
          const workItem = [...workItemGroups.values()].find((item) => item.firstGroupId === event.id)
          if (!workItem || workItem.firstGroupId !== event.id) return null
          const userAnchorId = userEventIdBefore(displayEvents, index)
          if (userAnchorId && collapsedProcessAnchors.has(userAnchorId)) return null
          return <ProcessEventCard key={workItem.firstGroupId} group={workItem.group} events={workItem.children} />
        }

        return null
      })}
    </div>
  )
}

function latestUserEventId(events: AgentEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.event_type === 'message.user') return event.id
  }
  return null
}

function elapsedEventForUserTurn(events: AgentEvent[], userIndex: number) {
  let elapsedEvent: AgentEvent | null = null
  for (let index = userIndex + 1; index < events.length; index += 1) {
    const event = events[index]
    if (event.event_type === 'message.user') return elapsedEvent
    if (event.event_type === 'run.elapsed' && elapsedSecondsOf(event) >= elapsedSecondsOf(elapsedEvent)) {
      elapsedEvent = event
    }
  }
  return elapsedEvent
}

function userEventIdBefore(events: AgentEvent[], targetIndex: number) {
  for (let index = targetIndex - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.event_type === 'message.user') return event.id
  }
  return null
}

function MessageBubble({ role, content, streaming = false }: { role: 'user' | 'assistant'; content: string; streaming?: boolean }) {
  return (
    <div className={`flex gap-3 ${role === 'user' ? 'justify-end' : 'justify-start'}`}>
      {role === 'assistant' ? <Bot className="mt-2 text-teal-700" size={20} /> : null}
      <div className={`max-w-[78%] rounded-3xl px-5 py-3 shadow-sm ${role === 'user' ? 'bg-stone-950 text-white' : 'border border-stone-200 bg-white text-stone-950'}`}>
        {role === 'assistant' ? <MarkdownMessage content={content} /> : content}
        {streaming ? <span className="ml-1 inline-block h-4 animate-pulse border-r-2 border-teal-700 align-[-0.12em]" /> : null}
      </div>
      {role === 'user' ? <User className="mt-2 text-stone-700" size={20} /> : null}
    </div>
  )
}

function elapsedSecondsOf(event: AgentEvent | null) {
  const value = event?.payload.elapsed_seconds
  return typeof value === 'number' ? Math.max(0, Math.floor(value)) : 0
}
