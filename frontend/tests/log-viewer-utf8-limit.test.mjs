import test from 'node:test'
import assert from 'node:assert/strict'
import { retainRecentUtf8Bytes } from '../src/utils/utf8Text.js'

const size = value => new TextEncoder().encode(value).length

test('log tail honors a UTF-8 byte budget for ASCII and Chinese text', () => {
  assert.equal(retainRecentUtf8Bytes('abcdef', 3), 'def')
  assert.equal(retainRecentUtf8Bytes('abc你好', 4), '好')
  assert.equal(retainRecentUtf8Bytes('你好世界', 6), '世界')
  assert.ok(size(retainRecentUtf8Bytes('a你好世界b', 7)) <= 7)
})

test('log tail never displays an incomplete emoji or UTF-8 code point', () => {
  assert.equal(retainRecentUtf8Bytes('start🙂🎉!', 5), '🎉!')
  assert.equal(retainRecentUtf8Bytes('a🙂', 3), '')
  assert.equal(retainRecentUtf8Bytes('a🙂', 4), '🙂')
  assert.equal(retainRecentUtf8Bytes('🙂🙂', 8), '🙂🙂')
})

test('log tail preserves small content and handles invalid bounds', () => {
  assert.equal(retainRecentUtf8Bytes('Hello', 5), 'Hello')
  assert.equal(retainRecentUtf8Bytes('Hello', 0), '')
  assert.equal(retainRecentUtf8Bytes('Hello', -1), '')
  assert.equal(retainRecentUtf8Bytes('', 256), '')
})
