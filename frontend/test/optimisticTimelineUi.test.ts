import test from 'node:test'
import assert from 'node:assert/strict'

import { createOptimisticTimelineUi, timelineEventsWithOptimisticUi } from '../src/lib/optimisticTimelineUi.ts'
import type { AgentEvent } from '../src/types/agent'

test('optimistic UI 只在渲染时合成临时事件，不改变真实 events 数组', () => {
  const realEvents = [event({ id: 'evt_history', seq: 7, ordinal: 1 })]
  const optimisticUi = createOptimisticTimelineUi('thread-test', '看看笨笨', 'stamp-1')

  const displayEvents = timelineEventsWithOptimisticUi(realEvents, optimisticUi)

  assert.equal(realEvents.length, 1)
  assert.deepEqual(realEvents.map((item) => item.id), ['evt_history'])
  assert.deepEqual(displayEvents.map((item) => item.id), [
    'evt_history',
    'local_user_thread-test_stamp-1',
    'local_process_group_thread-test_stamp-1',
    'local_process_step_thread-test_stamp-1',
  ])
  assert.deepEqual(displayEvents.slice(1).map((item) => item.seq), [null, null, null])
})

test('真实用户事件已经出现时不再合成 optimistic 用户和过程占位', () => {
  const optimisticUi = createOptimisticTimelineUi('thread-test', '看看笨笨', 'stamp-1')
  const realEvents = [
    event({
      id: 'evt_real_user',
      conversation_id: 'thread-test',
      event_type: 'message.user',
      role: 'user',
      content: '看看笨笨',
      seq: null,
      ordinal: 1,
    }),
  ]

  const displayEvents = timelineEventsWithOptimisticUi(realEvents, optimisticUi)

  assert.deepEqual(displayEvents.map((item) => item.id), ['evt_real_user'])
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
