const assert = require('node:assert/strict');
const utils = require('../static/app-utils.js');

assert.equal(
  utils.escapeHTML('<img src=x onerror="boom">'),
  '&lt;img src=x onerror=&quot;boom&quot;&gt;',
);
assert.equal(utils.safeExternalURL('javascript:alert(1)', 'http://localhost'), '#');
assert.equal(
  utils.safeExternalURL('https://seekingalpha.com/news/1', 'http://localhost'),
  'https://seekingalpha.com/news/1',
);
assert.equal(utils.formatTime('2026-07-17 01:56 KST'), '07/17 01:56');
assert.deepEqual(utils.formatChangePct(1.234), { text: '+1.23%', cls: 'up' });
assert.equal(utils.formatExtendedMarketState('PRE', '장외'), 'PRE');
assert.equal(utils.formatExtendedMarketState('POSTPOST', '장외'), 'POST');
assert.equal(utils.formatExtendedMarketState('', '장외'), '장외');
assert.equal(utils.isExtendedMarketState('PREPRE'), true);
assert.equal(utils.isExtendedMarketState('REGULAR'), false);
assert.equal(utils.formatSummaryModel('claude-opus-5'), 'Claude Opus 5');
assert.equal(utils.formatSummaryModel('claude-opus-4-8'), 'Claude Opus 4.8');
assert.equal(utils.formatSummaryModel('claude-sonnet-4-5-20250929'), 'Claude Sonnet 4.5');
assert.equal(utils.formatSummaryModel('claude-opus-5-20260801'), 'Claude Opus 5');
assert.equal(utils.formatSummaryModel('claude-haiku-4-5-20251001'), 'Claude Haiku 4.5');

console.log('app-utils: ok');
