import test from 'node:test'
import assert from 'node:assert/strict'

import { buildRequestHistory, prepareOutgoingMessage, WELCOME_MESSAGE } from '../.test-dist/chatPayload.js'

test('prepareOutgoingMessage rejects empty and oversized drafts', () => {
  assert.equal(prepareOutgoingMessage('   '), null)
  assert.equal(prepareOutgoingMessage('a'.repeat(1201)), null)
})

test('prepareOutgoingMessage trims valid drafts', () => {
  assert.equal(prepareOutgoingMessage('  bonjour  '), 'bonjour')
})

test('buildRequestHistory keeps only the twelve latest messages and excludes welcome message', () => {
  const history = buildRequestHistory([
    { role: 'agent', content: WELCOME_MESSAGE },
    { role: 'visitor', content: 'm1' },
    { role: 'agent', content: 'm2' },
    { role: 'visitor', content: 'm3' },
    { role: 'agent', content: 'm4' },
    { role: 'visitor', content: 'm5' },
    { role: 'agent', content: 'm6' },
    { role: 'visitor', content: 'm7' },
    { role: 'agent', content: 'm8' },
    { role: 'visitor', content: 'm9' },
    { role: 'agent', content: 'm10' },
    { role: 'visitor', content: 'm11' },
    { role: 'agent', content: 'm12' },
    { role: 'visitor', content: 'm13' }
  ])

  assert.deepEqual(history, [
    { role: 'agent', content: 'm2' },
    { role: 'visitor', content: 'm3' },
    { role: 'agent', content: 'm4' },
    { role: 'visitor', content: 'm5' },
    { role: 'agent', content: 'm6' },
    { role: 'visitor', content: 'm7' },
    { role: 'agent', content: 'm8' },
    { role: 'visitor', content: 'm9' },
    { role: 'agent', content: 'm10' },
    { role: 'visitor', content: 'm11' },
    { role: 'agent', content: 'm12' },
    { role: 'visitor', content: 'm13' }
  ])
})
