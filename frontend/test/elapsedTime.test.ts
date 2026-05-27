import test from 'node:test'
import assert from 'node:assert/strict'

import {
  elapsedSecondsFromLatestRunEvent,
  elapsedSecondsSince,
  formatElapsedSeconds,
  shouldKeepElapsedTimerRunning,
  startedAtFromElapsedSeconds,
} from '../src/lib/elapsedTime.ts'
import type { AgentRunResult } from '../src/types/agent'
import type { AgentEvent } from '../src/types/agent'

test('60 秒内按秒显示', () => {
  assert.equal(formatElapsedSeconds(0), '0s')
  assert.equal(formatElapsedSeconds(8), '8s')
  assert.equal(formatElapsedSeconds(59), '59s')
})

test('超过 60 秒后按 Codex 风格显示分钟和秒', () => {
  assert.equal(formatElapsedSeconds(60), '1m 00s')
  assert.equal(formatElapsedSeconds(102), '1m 42s')
  assert.equal(formatElapsedSeconds(3599), '59m 59s')
})

test('耗时计算向下取整并避免负数', () => {
  assert.equal(elapsedSecondsSince(1000, 950), 0)
  assert.equal(elapsedSecondsSince(1000, 1999), 0)
  assert.equal(elapsedSecondsSince(1000, 2000), 1)
})

test('HITL 续接时从最近的 run.elapsed 恢复计时起点', () => {
  const events = [
    event({ id: 'elapsed-1', event_type: 'run.elapsed', payload: { elapsed_seconds: 31 } }),
    event({ id: 'interrupt', event_type: 'interrupt.requested', payload: {} }),
  ]

  const elapsedSeconds = elapsedSecondsFromLatestRunEvent(events)
  const startedAt = startedAtFromElapsedSeconds(elapsedSeconds, 100_000)

  assert.equal(elapsedSeconds, 31)
  assert.equal(startedAt, 69_000)
  assert.equal(elapsedSecondsSince(startedAt, 102_000), 33)
})

test('中断等待用户确认时计时器应继续运行，完成或失败后才停止', () => {
  assert.equal(shouldKeepElapsedTimerRunning(runResult({ status: 'interrupted', interrupt: { type: 'confirm', title: '确认' } })), true)
  assert.equal(shouldKeepElapsedTimerRunning(runResult({ status: 'completed', interrupt: null })), false)
  assert.equal(shouldKeepElapsedTimerRunning(runResult({ status: 'error', interrupt: null })), false)
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

function runResult(overrides: Partial<AgentRunResult>): AgentRunResult {
  return {
    thread_id: 'thread-test',
    status: 'completed',
    events: [],
    messages: [],
    interrupt: null,
    ...overrides,
  }
}
