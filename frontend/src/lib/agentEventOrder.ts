import type { AgentEvent } from '../types/agent'

export function compareAgentEvents(left: AgentEvent, right: AgentEvent) {
  return eventSortValue(left) - eventSortValue(right) || eventTypeOrder(left.event_type) - eventTypeOrder(right.event_type)
}

export function eventSortValue(event: AgentEvent) {
  return typeof event.seq === 'number' ? event.seq : Number.MAX_SAFE_INTEGER + event.ordinal
}

function eventTypeOrder(eventType: string) {
  if (eventType === 'message.user') return 0
  if (eventType === 'run.elapsed') return 1
  if (eventType === 'process.group.started') return 2
  if (eventType === 'process.step') return 3
  if (eventType === 'interrupt.requested') return 4
  if (eventType === 'message.assistant.delta') return 5
  if (eventType === 'message.assistant.completed') return 6
  return 10
}
