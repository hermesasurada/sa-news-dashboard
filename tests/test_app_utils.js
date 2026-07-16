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

console.log('app-utils: ok');
