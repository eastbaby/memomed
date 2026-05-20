import type { AgentEvent } from '../types/agent'

export function mergeAgentEvents(current: AgentEvent[], incoming: AgentEvent[]) {
  if (incoming.length === 0) return current

  const indexById = new Map(current.map((event, index) => [event.id, index]))
  const merged = [...current]

  for (const event of incoming) {
    if (!shouldKeepEvent(event, merged)) {
      continue
    }
    if (event.event_type === 'message.assistant.delta') {
      mergeAssistantDeltaEvent(merged, event)
      rebuildIndex(indexById, merged)
      continue
    }
    if (event.event_type === 'message.user') {
      removeMatchingOptimisticUserEvent(merged, event)
      removeOptimisticProcessEvents(merged, event.conversation_id)
      rebuildIndex(indexById, merged)
    }
    if (event.event_type === 'process.group.started' || event.event_type === 'message.assistant.completed' || event.event_type === 'interrupt.requested') {
      removeOptimisticProcessEvents(merged, event.conversation_id)
      rebuildIndex(indexById, merged)
    }
    if (event.event_type === 'message.assistant.completed') {
      removeStreamingAssistantDeltaEvents(merged, event)
      rebuildIndex(indexById, merged)
    }
    const index = indexById.get(event.id)
    if (index !== undefined) {
      merged[index] = { ...merged[index], ...event }
      continue
    }
    indexById.set(event.id, merged.length)
    merged.push(event)
  }

  return merged.sort((left, right) => left.seq - right.seq || eventTypeOrder(left.event_type) - eventTypeOrder(right.event_type))
}

function shouldKeepEvent(event: AgentEvent, currentEvents: AgentEvent[]) {
  if (event.event_type !== 'process.step') return true
  if (!isVisibleProcessStep(event)) return false
  return !currentEvents.some((current) => current.event_type === 'process.step' && processStepKey(current) === processStepKey(event))
}

function isVisibleProcessStep(event: AgentEvent) {
  const stepType = readStringPayload(event, 'step_type')
  return stepType === 'tool.started' || stepType === 'tool.observation' || stepType === 'tool.error'
}

function processStepKey(event: AgentEvent) {
  const stepType = readStringPayload(event, 'step_type')
  return [event.work_item_id ?? event.parent_event_id ?? event.run_id, stepType, event.content ?? ''].join('|')
}

function mergeAssistantDeltaEvent(events: AgentEvent[], incoming: AgentEvent) {
  const messageId = readStringPayload(incoming, 'message_id') ?? incoming.run_id ?? incoming.id
  const existingIndex = events.findIndex(
    (event) =>
      event.event_type === 'message.assistant.delta' &&
      (readStringPayload(event, 'message_id') ?? event.run_id ?? event.id) === messageId,
  )
  if (existingIndex < 0) {
    events.push({
      ...incoming,
      id: streamingDeltaEventId(incoming, messageId),
      content: incoming.content ?? '',
      payload: { ...incoming.payload, message_id: messageId, delta_chunks: [deltaChunk(incoming)] },
    })
    return
  }

  const existing = events[existingIndex]
  const chunks = [...readDeltaChunks(existing), deltaChunk(incoming)]
  const uniqueChunks = dedupeDeltaChunks(chunks)
  events[existingIndex] = {
    ...existing,
    ...incoming,
    id: existing.id,
    seq: Math.min(existing.seq, incoming.seq),
    content: uniqueChunks.map((chunk) => chunk.content).join(''),
    payload: {
      ...existing.payload,
      ...incoming.payload,
      message_id: messageId,
      delta_chunks: uniqueChunks,
    },
  }
}

function streamingDeltaEventId(event: AgentEvent, messageId: string) {
  return `stream_delta_${event.conversation_id}_${messageId}`
}

function deltaChunk(event: AgentEvent) {
  return {
    index: readNumberPayload(event, 'delta_index') ?? event.seq,
    content: event.content ?? '',
  }
}

function readDeltaChunks(event: AgentEvent) {
  const chunks = event.payload.delta_chunks
  if (!Array.isArray(chunks)) return []
  return chunks
    .map((chunk) => {
      if (!chunk || typeof chunk !== 'object') return null
      const record = chunk as Record<string, unknown>
      const index = typeof record.index === 'number' ? record.index : null
      const content = typeof record.content === 'string' ? record.content : null
      return index !== null && content !== null ? { index, content } : null
    })
    .filter((chunk): chunk is { index: number; content: string } => chunk !== null)
}

function dedupeDeltaChunks(chunks: Array<{ index: number; content: string }>) {
  const byIndex = new Map<number, { index: number; content: string }>()
  for (const chunk of chunks) {
    byIndex.set(chunk.index, chunk)
  }
  return [...byIndex.values()].sort((left, right) => left.index - right.index)
}

function readStringPayload(event: AgentEvent, key: string) {
  const value = event.payload[key]
  return typeof value === 'string' ? value : null
}

function readNumberPayload(event: AgentEvent, key: string) {
  const value = event.payload[key]
  return typeof value === 'number' ? value : null
}

function rebuildIndex(indexById: Map<string, number>, events: AgentEvent[]) {
  indexById.clear()
  events.forEach((currentEvent, index) => indexById.set(currentEvent.id, index))
}

function removeMatchingOptimisticUserEvent(events: AgentEvent[], incoming: AgentEvent) {
  const index = events.findIndex(
    (event) =>
      event.id.startsWith('local_user_') &&
      event.event_type === 'message.user' &&
      event.conversation_id === incoming.conversation_id &&
      event.content === incoming.content,
  )
  if (index >= 0) events.splice(index, 1)
}

function removeOptimisticProcessEvents(events: AgentEvent[], conversationId: string) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.conversation_id === conversationId && event.id.startsWith('local_process_')) {
      events.splice(index, 1)
    }
  }
}

function removeStreamingAssistantDeltaEvents(events: AgentEvent[], completedEvent: AgentEvent) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (
      event.conversation_id === completedEvent.conversation_id &&
      event.run_id === completedEvent.run_id &&
      event.event_type === 'message.assistant.delta'
    ) {
      events.splice(index, 1)
    }
  }
}

function eventTypeOrder(eventType: string) {
  if (eventType === 'message.user') return 0
  if (eventType === 'process.group.started') return 1
  if (eventType === 'process.step') return 2
  if (eventType === 'interrupt.requested') return 3
  if (eventType === 'message.assistant.delta') return 4
  if (eventType === 'message.assistant.completed') return 5
  return 10
}
