import type { AgentEvent } from '../types/agent'
import { compareAgentEvents, eventSortValue } from './agentEventOrder.ts'

export function mergeAgentEvents(current: AgentEvent[], incoming: AgentEvent[]) {
  if (incoming.length === 0) return current

  const indexById = new Map(current.map((event, index) => [event.id, index]))
  const merged = [...current]

  for (const rawEvent of incoming) {
    let event = rawEvent
    if (!isRenderableEvent(event)) {
      continue
    }
    if (event.event_type === 'message.assistant.delta') {
      mergeAssistantDeltaEvent(merged, event)
      rebuildIndex(indexById, merged)
      continue
    }
    if (event.event_type === 'message.user') {
      rebuildIndex(indexById, merged)
    }
    if (event.event_type === 'run.elapsed') {
      event = elapsedEventWithMonotonicSeconds(merged, event)
      removePreviousElapsedEvents(merged, event)
      rebuildIndex(indexById, merged)
    }
    if (event.event_type === 'message.assistant.completed') {
      removeStreamingAssistantDeltaEvents(merged, event)
      rebuildIndex(indexById, merged)
    }
    if (event.event_type === 'message.assistant.cancelled') {
      removeCancelledAssistantDeltaEvents(merged, event)
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

  return merged.sort(compareAgentEvents)
}

function isRenderableEvent(event: AgentEvent) {
  if (event.event_type !== 'process.step') return true
  return isVisibleProcessStep(event)
}

function removePreviousElapsedEvents(events: AgentEvent[], incoming: AgentEvent) {
  const incomingTurnStartSeq = userTurnStartSeq(events, incoming)
  removeEventsInPlace(
    events,
    (event) =>
      event.id !== incoming.id &&
      event.event_type === 'run.elapsed' &&
      event.conversation_id === incoming.conversation_id &&
      userTurnStartSeq(events, event) === incomingTurnStartSeq,
  )
}

function elapsedEventWithMonotonicSeconds(events: AgentEvent[], incoming: AgentEvent) {
  const incomingTurnStartSeq = userTurnStartSeq(events, incoming)
  const previous = events
    .filter(
      (event) =>
        event.event_type === 'run.elapsed' &&
        event.conversation_id === incoming.conversation_id &&
        userTurnStartSeq(events, event) === incomingTurnStartSeq,
    )
    .sort((left, right) => elapsedSecondsOf(right) - elapsedSecondsOf(left))[0]
  if (!previous || elapsedSecondsOf(incoming) >= elapsedSecondsOf(previous)) {
    return incoming
  }
  return {
    ...incoming,
    content: previous.content,
    payload: { ...incoming.payload, elapsed_seconds: elapsedSecondsOf(previous) },
  }
}

function userTurnStartSeq(events: AgentEvent[], target: AgentEvent) {
  let startSeq = Number.NEGATIVE_INFINITY
  for (const event of events) {
    if (
      event.conversation_id === target.conversation_id &&
      event.event_type === 'message.user' &&
      eventSortValue(event) < eventSortValue(target) &&
      eventSortValue(event) > startSeq
    ) {
      startSeq = eventSortValue(event)
    }
  }
  return startSeq
}

function elapsedSecondsOf(event: AgentEvent) {
  const value = event.payload.elapsed_seconds
  return typeof value === 'number' ? Math.max(0, Math.floor(value)) : 0
}

function isVisibleProcessStep(event: AgentEvent) {
  const stepType = readStringPayload(event, 'step_type')
  return stepType === 'agent.progress' || stepType === 'tool.started' || stepType === 'tool.observation' || stepType === 'tool.error'
}

function mergeAssistantDeltaEvent(events: AgentEvent[], incoming: AgentEvent) {
  const messageId = requiredStringPayload(incoming, 'message_id')
  const incomingChunk = deltaChunk(incoming)
  const existingIndex = events.findIndex(
    (event) =>
      event.event_type === 'message.assistant.delta' &&
      requiredStringPayload(event, 'message_id') === messageId,
  )
  if (existingIndex < 0) {
    events.push({
      ...incoming,
      id: streamingDeltaEventId(incoming, messageId),
      content: incoming.content ?? '',
      payload: { ...incoming.payload, message_id: messageId, delta_chunks: [incomingChunk] },
    })
    return
  }

  const existing = events[existingIndex]
  const chunks = [...readDeltaChunks(existing), incomingChunk]
  const uniqueChunks = dedupeDeltaChunks(chunks)
  events[existingIndex] = {
    ...existing,
    ...incoming,
    id: existing.id,
    seq: mergedSeq(existing.seq, incoming.seq),
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
    index: requiredNumberPayload(event, 'delta_index'),
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

function requiredStringPayload(event: AgentEvent, key: string) {
  const value = readStringPayload(event, key)
  if (value === null || value.length === 0) {
    throw new Error(`${event.event_type} 缺少 payload.${key}`)
  }
  return value
}

function requiredNumberPayload(event: AgentEvent, key: string) {
  const value = readNumberPayload(event, key)
  if (value === null) {
    throw new Error(`${event.event_type} 缺少 payload.${key}`)
  }
  return value
}

function rebuildIndex(indexById: Map<string, number>, events: AgentEvent[]) {
  indexById.clear()
  events.forEach((currentEvent, index) => indexById.set(currentEvent.id, index))
}

function removeEventsInPlace(events: AgentEvent[], predicate: (event: AgentEvent) => boolean) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (predicate(events[index])) {
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

function removeCancelledAssistantDeltaEvents(events: AgentEvent[], cancelledEvent: AgentEvent) {
  const messageId = readStringPayload(cancelledEvent, 'message_id')
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (
      event.conversation_id === cancelledEvent.conversation_id &&
      event.event_type === 'message.assistant.delta' &&
      (messageId === null || readStringPayload(event, 'message_id') === messageId)
    ) {
      events.splice(index, 1)
    }
  }
}

function mergedSeq(left: number | null, right: number | null) {
  if (typeof left === 'number' && typeof right === 'number') return Math.min(left, right)
  return left ?? right
}
