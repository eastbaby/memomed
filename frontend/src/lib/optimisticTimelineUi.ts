import { mergeAgentEvents } from './agentEventTimeline.ts'
import type { AgentEvent } from '../types/agent'

export type OptimisticTimelineUi = {
  threadId: string
  message: string
  idSuffix: string
}

export function createOptimisticTimelineUi(
  threadId: string,
  message: string,
  idSuffix = Date.now().toString(36),
): OptimisticTimelineUi {
  return { threadId, message, idSuffix }
}

export function timelineEventsWithOptimisticUi(events: AgentEvent[], optimisticUi: OptimisticTimelineUi | null) {
  if (!optimisticUi || hasMatchingRealUserEvent(events, optimisticUi)) return events
  return mergeAgentEvents(events, optimisticEvents(events, optimisticUi))
}

function hasMatchingRealUserEvent(events: AgentEvent[], optimisticUi: OptimisticTimelineUi) {
  return events.some(
    (event) =>
      event.conversation_id === optimisticUi.threadId &&
      event.event_type === 'message.user' &&
      event.role === 'user' &&
      event.content === optimisticUi.message &&
      !event.id.startsWith('local_'),
  )
}

function optimisticEvents(events: AgentEvent[], optimisticUi: OptimisticTimelineUi): AgentEvent[] {
  const userOrdinal = nextLocalOrdinal(events)
  const groupId = `local_process_group_${optimisticUi.threadId}_${optimisticUi.idSuffix}`
  return [
    {
      id: `local_user_${optimisticUi.threadId}_${optimisticUi.idSuffix}`,
      conversation_id: optimisticUi.threadId,
      run_id: null,
      ordinal: userOrdinal,
      seq: null,
      event_type: 'message.user',
      role: 'user',
      visibility: 'visible',
      status: 'completed',
      content: optimisticUi.message,
      payload: { optimistic: true },
    },
    {
      id: groupId,
      conversation_id: optimisticUi.threadId,
      run_id: null,
      work_item_id: groupId,
      work_item_type: 'general_tool_work',
      ordinal: userOrdinal + 1,
      seq: null,
      event_type: 'process.group.started',
      role: 'assistant',
      visibility: 'collapsed',
      status: 'streaming',
      title: 'Agent 过程',
      content: '正在理解需求并选择合适的工具。',
      payload: { optimistic: true },
    },
    {
      id: `local_process_step_${optimisticUi.threadId}_${optimisticUi.idSuffix}`,
      conversation_id: optimisticUi.threadId,
      run_id: null,
      work_item_id: groupId,
      work_item_type: 'general_tool_work',
      ordinal: userOrdinal + 2,
      seq: null,
      event_type: 'process.step',
      role: 'assistant',
      visibility: 'collapsed',
      status: 'streaming',
      parent_event_id: groupId,
      title: '思考过程',
      content: '正在理解需求并选择合适的工具。',
      payload: { optimistic: true, step_type: 'agent.progress' },
    },
  ]
}

function nextLocalOrdinal(events: AgentEvent[]) {
  if (events.length === 0) return 1
  return Math.max(...events.map((event) => event.ordinal)) + 1
}
