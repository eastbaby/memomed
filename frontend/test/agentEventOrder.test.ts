import test from 'node:test'
import assert from 'node:assert/strict'

import { eventSortValue } from '../src/lib/agentEventOrder.ts'
import type { AgentEvent } from '../src/types/agent'

test('落库事件使用 seq 排序，实时事件使用 ordinal 排序', () => {
  assert.equal(eventSortValue(event({ seq: 12, ordinal: 99 })), 12)
  assert.equal(eventSortValue(event({ seq: null, ordinal: 7 })), Number.MAX_SAFE_INTEGER + 7)
})

function event(overrides: Partial<AgentEvent>): AgentEvent {
  return {
    id: 'evt_default',
    conversation_id: 'thread-test',
    run_id: 'run-test',
    ordinal: 1,
    seq: 1,
    event_type: 'message.user',
    role: 'assistant',
    visibility: 'visible',
    status: 'completed',
    content: null,
    payload: {},
    ...overrides,
  }
}
