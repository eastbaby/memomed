import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeAgentEvents } from '../src/lib/agentEventTimeline.ts'
import { buildProcessWorkItems } from '../src/lib/processWorkItems.ts'
import type { AgentEvent } from '../src/types/agent'

test('mergeAgentEvents 只合并真实事件，不负责清理 optimistic UI 占位', () => {
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
    merged.map((item) => item.id),
    ['local_user_thread_1', 'local_process_group_thread_1', 'evt_real_user'],
  )
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

test('实时事件没有会话 seq 时按 ordinal 排序', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({ id: 'evt_run_1_0003', event_type: 'process.step', seq: null, ordinal: 3, payload: { step_type: 'tool.observation' } }),
    event({ id: 'evt_run_1_0004', event_type: 'process.step', seq: null, ordinal: 4, payload: { step_type: 'tool.started' } }),
    event({ id: 'evt_run_1_0001', event_type: 'message.user', seq: null, ordinal: 1, content: '看我老公报告' }),
    event({ id: 'evt_run_1_0002', event_type: 'process.group.started', seq: null, ordinal: 2 }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.id),
    ['evt_run_1_0001', 'evt_run_1_0002', 'evt_run_1_0003', 'evt_run_1_0004'],
  )
})

test('最终落库事件用相同 id 回填 seq，不重复展示实时事件', () => {
  const current = [
    event({ id: 'evt_run_1_0001', event_type: 'message.user', seq: null, ordinal: 1, content: '看我老公报告' }),
    event({ id: 'evt_run_1_0002', event_type: 'message.assistant.completed', seq: null, ordinal: 2, content: '已处理完成。' }),
  ]
  const incoming = [
    event({ id: 'evt_run_1_0001', event_type: 'message.user', seq: 41, ordinal: 1, content: '看我老公报告' }),
    event({ id: 'evt_run_1_0002', event_type: 'message.assistant.completed', seq: 42, ordinal: 2, content: '已处理完成。' }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.equal(merged.length, 2)
  assert.deepEqual(merged.map((item) => item.seq), [41, 42])
})

test('历史耗时事件排在用户消息之后和过程块之前', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({ id: 'evt_process_group', event_type: 'process.group.started', seq: 3 }),
    event({ id: 'evt_elapsed', event_type: 'run.elapsed', seq: 2, content: '已处理 1m 42s' }),
    event({ id: 'evt_user', event_type: 'message.user', seq: 1, content: '看我老公报告' }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.event_type),
    ['message.user', 'run.elapsed', 'process.group.started'],
  )
})

test('历史耗时事件即使来自后续 resume run，也会由 timeline 锚定到用户消息下面', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({ id: 'evt_user', event_type: 'message.user', seq: 1, content: '看我老公报告' }),
    event({ id: 'evt_process_group', event_type: 'process.group.started', seq: 2 }),
    event({ id: 'evt_elapsed', event_type: 'run.elapsed', seq: 3, content: '已处理 18s' }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.event_type),
    ['message.user', 'process.group.started', 'run.elapsed'],
  )
})

test('同一用户回合跨 HITL 的 run.elapsed 按回合合并并保持单调递增', () => {
  const current = [
    event({ id: 'evt_user', event_type: 'message.user', seq: 1, content: '看看笨笨' }),
    event({
      id: 'evt_elapsed_waiting',
      event_type: 'run.elapsed',
      seq: 2,
      run_id: 'run-before-interrupt',
      content: '已处理 31s',
      payload: { elapsed_seconds: 31 },
    }),
    event({ id: 'evt_interrupt', event_type: 'interrupt.requested', seq: 3, run_id: 'run-before-interrupt' }),
  ]
  const incoming = [
    event({
      id: 'evt_elapsed_resume',
      event_type: 'run.elapsed',
      seq: 4,
      run_id: 'run-after-resume',
      content: '已处理 4s',
      payload: { elapsed_seconds: 4 },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)
  const elapsedEvents = merged.filter((item) => item.event_type === 'run.elapsed')

  assert.equal(elapsedEvents.length, 1)
  assert.equal(elapsedEvents[0].content, '已处理 31s')
  assert.equal(elapsedEvents[0].payload.elapsed_seconds, 31)
})

test('同一用户回合收到更大的最终 run.elapsed 时替换等待阶段耗时', () => {
  const current = [
    event({ id: 'evt_user', event_type: 'message.user', seq: 1, content: '看看笨笨' }),
    event({
      id: 'evt_elapsed_waiting',
      event_type: 'run.elapsed',
      seq: 2,
      run_id: 'run-before-interrupt',
      content: '已处理 12s',
      payload: { elapsed_seconds: 12 },
    }),
  ]
  const incoming = [
    event({
      id: 'evt_elapsed_final',
      event_type: 'run.elapsed',
      seq: 4,
      run_id: 'run-after-resume',
      content: '已处理 35s',
      payload: { elapsed_seconds: 35 },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)
  const elapsedEvents = merged.filter((item) => item.event_type === 'run.elapsed')

  assert.equal(elapsedEvents.length, 1)
  assert.equal(elapsedEvents[0].content, '已处理 35s')
  assert.equal(elapsedEvents[0].payload.elapsed_seconds, 35)
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

test('工具调用开始时取消临时助手 delta，避免工具前言残留在页面', () => {
  const current = [
    event({
      id: 'evt_delta',
      event_type: 'message.assistant.delta',
      seq: 2,
      run_id: 'run-1',
      content: '我先确认一下',
      status: 'streaming',
      payload: { message_id: 'msg-1' },
    }),
  ]
  const incoming = [
    event({
      id: 'evt_cancelled',
      event_type: 'message.assistant.cancelled',
      seq: 3,
      run_id: 'run-1',
      visibility: 'hidden',
      payload: { message_id: 'msg-1' },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.event_type),
    ['message.assistant.cancelled'],
  )
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

test('assistant delta 缺少 message_id 时直接报协议错误，不用 run_id 或 event id 兜底', () => {
  assert.throws(
    () =>
      mergeAgentEvents([], [
        event({
          id: 'evt_delta_without_message_id',
          event_type: 'message.assistant.delta',
          seq: null,
          ordinal: 2,
          content: '你好',
          payload: { delta_index: 1 },
        }),
      ]),
    /message\.assistant\.delta 缺少 payload\.message_id/,
  )
})

test('assistant delta 缺少 delta_index 时直接报协议错误，不用 seq 或 ordinal 兜底', () => {
  assert.throws(
    () =>
      mergeAgentEvents([], [
        event({
          id: 'evt_delta_without_delta_index',
          event_type: 'message.assistant.delta',
          seq: null,
          ordinal: 2,
          content: '你好',
          payload: { message_id: 'msg-1' },
        }),
      ]),
    /message\.assistant\.delta 缺少 payload\.delta_index/,
  )
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

test('Agent 首包进度属于可见过程步骤', () => {
  const current: AgentEvent[] = []
  const incoming = [
    event({
      id: 'evt_group',
      event_type: 'process.group.started',
      seq: 1,
      work_item_id: 'wi-progress',
      content: '正在理解需求并选择合适的工具。',
    }),
    event({
      id: 'evt_agent_progress',
      event_type: 'process.step',
      seq: 2,
      work_item_id: 'wi-progress',
      content: '正在理解需求并选择合适的工具。',
      payload: { step_type: 'agent.progress' },
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.id),
    ['evt_group', 'evt_agent_progress'],
  )
})

test('真实过程组到达后不按类型猜测删除启动时的 Agent 过程组', () => {
  const current = [
    event({
      id: 'evt_initial_group',
      event_type: 'process.group.started',
      seq: 2,
      work_item_id: 'wi-agent-progress',
      work_item_type: 'agent_progress',
      content: '正在理解需求并选择合适的工具。',
      payload: { source: 'runtime_start' },
    }),
    event({
      id: 'evt_initial_step',
      event_type: 'process.step',
      seq: 3,
      work_item_id: 'wi-agent-progress',
      work_item_type: 'agent_progress',
      content: '正在理解需求并选择合适的工具。',
      payload: { source: 'runtime_start', step_type: 'agent.progress' },
    }),
  ]
  const incoming = [
    event({
      id: 'evt_subject_group',
      event_type: 'process.group.started',
      seq: 4,
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      content: '需要确认本次健康档案的管理对象。',
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.id),
    ['evt_initial_group', 'evt_initial_step', 'evt_subject_group'],
  )
})

test('相同 work item 里相同过程文本但不同事件 id 都保留', () => {
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
    ['evt_group', 'evt_tool_observation', 'evt_runtime_duplicate'],
  )
})

test('final 过程组不会按 work_item_type 删除另一个不同 work_item_id 的实时过程组', () => {
  const current = [
    event({
      id: 'evt_stream_group_a',
      event_type: 'process.group.started',
      seq: null,
      ordinal: 3,
      run_id: 'run-1',
      work_item_id: 'wi-stream-a',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '正在确认第一个对象。',
      status: 'streaming',
    }),
  ]
  const incoming = [
    event({
      id: 'evt_final_group_b',
      event_type: 'process.group.started',
      seq: 4,
      ordinal: 4,
      run_id: 'run-1',
      work_item_id: 'wi-final-b',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '已确认第二个对象。',
      status: 'completed',
    }),
  ]

  const merged = mergeAgentEvents(current, incoming)

  assert.deepEqual(
    merged.map((item) => item.id),
    ['evt_final_group_b', 'evt_stream_group_a'],
  )
})

test('实时流累积后合入最终 result.events，过程展示必须和刷新历史一致', () => {
  const streamEvents = [
    event({ id: 'evt_user', event_type: 'message.user', seq: null, ordinal: 1, content: '看看笨笨' }),
    event({
      id: 'evt_elapsed',
      event_type: 'run.elapsed',
      seq: null,
      ordinal: 2,
      content: '已处理 4s',
    }),
    event({
      id: 'evt_subject_group',
      event_type: 'process.group.started',
      seq: null,
      ordinal: 3,
      run_id: 'run-1',
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '需要确认本次健康档案的管理对象。',
      status: 'streaming',
      payload: { source: 'langgraph_custom_stream' },
    }),
    event({
      id: 'evt_subject_step',
      event_type: 'process.step',
      seq: null,
      ordinal: 4,
      run_id: 'run-1',
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      content: '已确认这次管理对象是笨笨（宠物）。',
      payload: { source: 'langgraph_custom_stream', step_type: 'tool.observation' },
    }),
    event({
      id: 'evt_query_group',
      event_type: 'process.group.started',
      seq: null,
      ordinal: 5,
      run_id: 'run-1',
      work_item_id: 'wi-query',
      work_item_type: 'health_records_query',
      title: '查询健康报告',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
      status: 'streaming',
      payload: { source: 'langgraph_custom_stream' },
    }),
    event({
      id: 'evt_query_step',
      event_type: 'process.step',
      seq: null,
      ordinal: 6,
      run_id: 'run-1',
      work_item_id: 'wi-query',
      work_item_type: 'health_records_query',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
      payload: { source: 'langgraph_custom_stream', step_type: 'tool.observation' },
    }),
  ]
  const finalEvents = [
    event({ id: 'evt_user', event_type: 'message.user', seq: 1, content: '看看笨笨' }),
    event({ id: 'evt_elapsed_final', event_type: 'run.elapsed', seq: 2, content: '已处理 26s' }),
    event({
      id: 'evt_subject_group',
      event_type: 'process.group.started',
      seq: 3,
      run_id: 'run-1',
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      title: '确认健康档案对象',
      content: '已确认这次管理对象是笨笨（宠物）。',
      status: 'completed',
    }),
    event({
      id: 'evt_subject_step',
      event_type: 'process.step',
      seq: 4,
      run_id: 'run-1',
      work_item_id: 'wi-subject',
      work_item_type: 'subject_resolution',
      content: '已确认这次管理对象是笨笨（宠物）。',
      payload: { step_type: 'tool.observation' },
    }),
    event({
      id: 'evt_query_group',
      event_type: 'process.group.started',
      seq: 5,
      run_id: 'run-1',
      work_item_id: 'wi-query',
      work_item_type: 'health_records_query',
      title: '查询健康报告',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
      status: 'completed',
    }),
    event({
      id: 'evt_query_step',
      event_type: 'process.step',
      seq: 6,
      run_id: 'run-1',
      work_item_id: 'wi-query',
      work_item_type: 'health_records_query',
      content: '已确认健康档案对象，但报告查询工具尚未接入。',
      payload: { step_type: 'tool.observation' },
    }),
    event({
      id: 'evt_answer',
      event_type: 'message.assistant.completed',
      seq: 7,
      run_id: 'run-1',
      content: '已找到笨笨的健康档案，但健康报告查询功能目前尚未接入。',
    }),
  ]

  const realtimeThenFinal = mergeAgentEvents(mergeAgentEvents([], streamEvents), finalEvents)
  const historyOnly = mergeAgentEvents([], finalEvents)

  assert.deepEqual(timelineSignature(realtimeThenFinal), timelineSignature(historyOnly))
})

function timelineSignature(events: AgentEvent[]) {
  const workItems = buildProcessWorkItems(events)
  return events
    .filter((item) => item.event_type !== 'process.step')
    .map((item) => {
      if (item.event_type !== 'process.group.started') {
        return [item.event_type, item.content]
      }
      const workItem = [...workItems.values()].find((candidate) => candidate.firstGroupId === item.id)
      if (!workItem) return null
      return [
        item.event_type,
        workItem.group.work_item_type,
        workItem.group.title,
        workItem.group.content,
        workItem.children.map((child) => [child.payload.step_type, child.content]),
      ]
    })
    .filter(Boolean)
}

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
