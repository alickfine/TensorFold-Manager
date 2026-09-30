import test from 'node:test';
import assert from 'node:assert/strict';
import { renderChat } from '../web/views/chat.js';
import { renderChatMarkdown } from '../web/chat-markdown.js';
import { prepareRetryTurn, chatRequest } from '../web/chat-options.js';

test('chat Markdown escapes untrusted HTML and unsafe links but keeps code blocks', () => {
  const html = renderChatMarkdown('Hello **world**\n\n```js\n<script>alert(1)</script>\n```\n[bad](javascript:alert(1)) [good](https://example.com)');
  assert.match(html, /<strong>world<\/strong>/);
  assert.match(html, /<pre/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script|href="javascript:/);
  assert.match(html, /href="https:\/\/example.com"/);
});

test('retry keeps the failed attempt visible and does not duplicate the user turn in inference', () => {
  const messages = [
    {role:'user',content:'Question'},
    {role:'assistant',content:'partial',status:'failed'},
  ];
  const retried = prepareRetryTurn(messages, {temperature:0.6});
  assert.equal(retried.messages.length, 3);
  assert.equal(retried.messages[1].content, 'partial');
  const request = chatRequest('model', retried.messages.slice(0,-1), retried.options);
  assert.deepEqual(request.messages.map((item) => item.role), ['user']);
});

test('conversation list and answer surface expose separate sessions and display-only tools', () => {
  const html = renderChat({
    snapshot:{engine:{state:'ready',model:'Qwen'},settings:{},capabilities:{chat:true,streaming:true}},
    chat:{activeId:'one',sessions:[{id:'one',title:'First'},{id:'two',title:'Second'}],messages:[{role:'user',content:'Hello'},{role:'assistant',content:'World',status:'completed',reasoning:'Thought',tool_calls:[{function:{name:'lookup',arguments:'{}'}}]}],options:{},streaming:false},
  });
  assert.match(html, /data-action="chat-open" data-value="two"/);
  assert.match(html, /data-action="chat-rename"/);
  assert.match(html, /data-action="chat-copy"/);
  assert.match(html, /工具调用（仅展示，未执行）/);
  assert.match(html, /<details/);
});
