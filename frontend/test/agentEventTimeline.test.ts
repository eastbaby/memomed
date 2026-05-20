import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeAgentEvents } from '../src/lib/agentEventTimeline.ts'
import type { AgentEvent } from '../src/types/agent'

test('真实用户消息到达时移除本地过程占位，避免过程块排在用户消息前面', () => {
  const current = [
    event({ id: 'local_user_thread_1', event_type: 'message.user', seq: 0, content: '看我老公报告' }),
    event({
      id: 'local_process_group_thread_1',
      event_type: 'process.group.started',
      seq: 0.01,
      content: '正在理解需求并选择合适的工具。',
    }),
  ]
  const incoming = [event({ id: 'evt_real_user', event_type: 'message.user', seq: 1, content: '看我老公报告' })]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.event_type),
    ['message.user'],
  )
  assert.equal(merged[0].id, 'evt_real_user')
})

test('相同 seq 下按事件语义排序，用户消息先于过程块', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({ id: 'evt_process_group', event_type: 'process.group.started', seq: 1 }),
    event({ id: 'evt_user', event_type: 'message.user', seq: 1, content: '看我老公报告' }),
    event({ id: 'evt_process_step', event_type: 'process.step', seq: 1, payload: { step_type: 'tool.observation' } }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.event_type),
    ['message.user', 'process.group.started', 'process.step'],
  )
})

test('最终回复到达时移除同一 run 的 streaming delta 气泡', () => {
  const current = [
    event({
      id: 'evt_delta',
      event_type: 'message.assistant.delta',
      seq: 2,
      run_id: 'run-1',
      content: '你好',
      status: 'streaming',
    }),
  ]
  const incoming = [
    event({
      id: 'evt_completed',
      event_type: 'message.assistant.completed',
      seq: 2,
      run_id: 'run-1',
      content: '你好呀',
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.event_type),
    ['message.assistant.completed'],
  )
  assert.equal(merged[0].content, '你好呀')
})

test('同一条助手消息的 delta 事件按 message_id 拼接，而不是用后一个覆盖前一个', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({
      id: 'evt_delta_1',
      event_type: 'message.assistant.delta',
      seq: 2,
      run_id: 'run-1',
      content: '你',
      status: 'streaming',
      payload: { message_id: 'msg-1', delta_index: 1 },
    }),
    event({
      id: 'evt_delta_2',
      event_type: 'message.assistant.delta',
      seq: 3,
      run_id: 'run-1',
      content: '好',
      status: 'streaming',
      payload: { message_id: 'msg-1', delta_index: 2 },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.equal(merged.length, 1)
  assert.equal(merged[0].event_type, 'message.assistant.delta')
  assert.equal(merged[0].content, '你好')
  assert.equal(merged[0].payload.message_id, 'msg-1')
})

test('过程步骤只展示白名单类别，隐藏 runtime.note', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({
      id: 'evt_group',
      event_type: 'process.group.started',
      seq: 1,
      work_item_id: 'wi-1',
      content: '确认健康档案对象',
    }),
    event({
      id: 'evt_tool_started',
      event_type: 'process.step',
      seq: 2,
      work_item_id: 'wi-1',
      content: '正在调用工具：确认健康档案对象。',
      payload: { step_type: 'tool.started' },
    }),
    event({
      id: 'evt_tool_observation',
      event_type: 'process.step',
      seq: 3,
      work_item_id: 'wi-1',
      content: '需要确认本次健康档案的管理对象。',
      payload: { step_type: 'tool.observation' },
    }),
    event({
      id: 'evt_runtime_note',
      event_type: 'process.step',
      seq: 4,
      work_item_id: 'wi-1',
      content: '正在处理你的确认结果。',
      payload: { step_type: 'runtime.note' },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.id),
    ['evt_group', 'evt_tool_started', 'evt_tool_observation'],
  )
})

test('相同 work item 里相同过程文本只保留一条', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({ id: 'evt_group', event_type: 'process.group.started', seq: 1, work_item_id: 'wi-1' }),
    event({
      id: 'evt_tool_observation',
      event_type: 'process.step',
      seq: 2,
      work_item_id: 'wi-1',
      content: '需要确认本次健康档案的管理对象。',
      payload: { step_type: 'tool.observation' },
    }),
    event({
      id: 'evt_runtime_duplicate',
      event_type: 'process.step',
      seq: 3,
      work_item_id: 'wi-1',
      content: '需要确认本次健康档案的管理对象。',
      payload: { step_type: 'tool.observation' },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.id),
    ['evt_group', 'evt_tool_observation'],
  )
})

function event(overrides: Partial<AgentEvent>): AgentEvent {
  return {
    id: 'evt_default',
    conversation_id: 'thread-test',
    run_id: 'run-test',
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
