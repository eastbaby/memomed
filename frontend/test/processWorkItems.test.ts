import test from 'node:test'
import assert from 'node:assert/strict'

import { buildProcessWorkItems } from '../src/lib/processWorkItems.ts'
import type { AgentEvent } from '../src/types/agent'

test('同一轮同类型同标题但不同 work_item_id 的过程组必须拆开展示', () => {
  const items = buildProcessWorkItems([
    event({ id: 'user-1', event_type: 'message.user', seq: 1, role: 'user', content: '看看笨笨' }),
    event({
      id: 'group-start',
      event_type: 'process.group.started',
      seq: 2,
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '正在理解需求并选择合适的工具。',
    }),
    event({
      id: 'group-final',
      event_type: 'process.group.started',
      seq: 8,
      work_item_id: 'wi-final',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
    }),
  ])

  assert.equal(items.size, 2)
  assert.deepEqual(
    [...items.values()].map((item) => item.firstGroupId),
    ['group-start', 'group-final'],
  )
})

test('同一个 work_item_id 的过程组更新为最新状态', () => {
  const items = buildProcessWorkItems([
    event({
      id: 'group-start',
      event_type: 'process.group.started',
      seq: 2,
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '正在理解需求并选择合适的工具。',
    }),
    event({
      id: 'group-final',
      event_type: 'process.group.started',
      seq: 9,
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
    }),
  ])

  assert.equal(items.size, 1)
  const item = [...items.values()][0]
  assert.equal(item.firstGroupId, 'group-start')
  assert.equal(item.group.id, 'group-final')
})

test('同一过程块内不同事件 id 的步骤都展示，并按进度、工具调用、工具结果展示', () => {
  const items = buildProcessWorkItems([
    event({ id: 'user-1', event_type: 'message.user', seq: 1, role: 'user', content: '看看笨笨' }),
    event({
      id: 'group-start',
      event_type: 'process.group.started',
      seq: 2,
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '正在理解需求并选择合适的工具。',
    }),
    event({
      id: 'group-final',
      event_type: 'process.group.started',
      seq: 8,
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
    }),
    event({
      id: 'tool-result-a',
      event_type: 'process.step',
      seq: 7,
      work_item_id: 'wi-subject',
      content: '需要确认本次健康档案的管理对象。',
      payload: { step_type: 'tool.observation' },
    }),
    event({
      id: 'tool-started',
      event_type: 'process.step',
      seq: 5,
      work_item_id: 'wi-subject',
      content: '正在调用工具：确认健康档案对象。',
      payload: { step_type: 'tool.started' },
    }),
    event({
      id: 'agent-progress',
      event_type: 'process.step',
      seq: 10,
      work_item_id: 'wi-subject',
      content: '正在理解需求并选择合适的工具。',
      payload: { step_type: 'agent.progress' },
    }),
    event({
      id: 'tool-result-b',
      event_type: 'process.step',
      seq: 11,
      work_item_id: 'wi-subject',
      content: '需要确认本次健康档案的管理对象。',
      payload: { step_type: 'tool.observation' },
    }),
  ])

  const children = [...items.values()][0].children
  assert.deepEqual(
    children.map((item) => item.id),
    ['agent-progress', 'tool-started', 'tool-result-a', 'tool-result-b'],
  )
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
