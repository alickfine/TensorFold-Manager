import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { shouldPollLivePage } from '../web/contracts.js';

const read = (path) => readFileSync(new URL(path,import.meta.url),'utf8');

test('chrome shows only version in the sidebar and a symbolic language control in the header', () => {
  const html = read('../web/index.html');
  assert.doesNotMatch(html, /id="instance-meta"|id="task-count"|data-action="refresh"|id="language-select"/);
  assert.match(html, /id="app-version"/);
  assert.match(html, /id="language-toggle"[^>]*aria-label=/);
  const app = read('../web/app.js');
  assert.doesNotMatch(app, /更新于 \{time\}|#task-count|#instance-meta/);
  assert.match(app, /getLocale\(\) === 'zh-CN' \? 'en' : 'zh-CN'/);
});

test('new activity and settings routes poll only when the user is not editing', () => {
  for (const page of ['activity','settings']) {
    assert.equal(shouldPollLivePage(page), true);
    assert.equal(shouldPollLivePage(page, {dirty:true}), false);
  }
  assert.equal(shouldPollLivePage('chat'), false);
});

test('tables use intrinsic columns, wrap long text and keep overflow inside the table container', () => {
  const css = read('../web/app.css');
  assert.match(css, /\.tf-table\s*\{[^}]*width:max-content/);
  assert.match(css, /\.tf-table\s*\{[^}]*table-layout:auto/);
  assert.match(css, /\.tf-table-wrap\s*\{[^}]*overflow:auto/);
  assert.match(css, /\.tf-table td\s*\{[^}]*overflow-wrap:anywhere/);
});
