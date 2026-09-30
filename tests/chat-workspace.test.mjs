import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderChat } from '../web/views/chat.js';
import { renderChatMarkdown } from '../web/chat-markdown.js';
import { prepareRetryTurn, chatRequest, isUntitledConversation, conversationTitleFromMessage, applySavedConversation } from '../web/chat-options.js';

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

test('only the latest failed answer offers retry and displays its error', () => {
  const html = renderChat({
    snapshot:{engine:{state:'ready',model:'Qwen'},settings:{},capabilities:{chat:true,streaming:true}},
    chat:{activeId:'one',sessions:[{id:'one',title:'Test'}],messages:[
      {role:'user',content:'First'},
      {role:'assistant',content:'',status:'failed',error:'first error'},
      {role:'user',content:'Second'},
      {role:'assistant',content:'',status:'failed',error:'<last error>'},
    ],options:{},streaming:false},
  });
  assert.equal((html.match(/data-action="chat-retry"/g) ?? []).length, 1);
  assert.match(html, /&lt;last error&gt;/);
  assert.doesNotMatch(html, /<last error>/);
});

test('untitled conversation is recognized across language changes', () => {
  assert.equal(isUntitledConversation('新对话'), true);
  assert.equal(isUntitledConversation('New conversation'), true);
  assert.equal(isUntitledConversation('Custom title'), false);
});

test('display-only tool calls are not replayed as executable calls', () => {
  const request = chatRequest('model', [
    {role:'user',content:'Inspect'},
    {role:'assistant',content:'I can inspect that.',status:'completed',tool_calls:[{id:'call_1',type:'function',function:{name:'inspect',arguments:'{}'}}]},
    {role:'user',content:'Continue'},
  ], {});
  assert.deepEqual(request.messages.map(({role,content}) => [role,content]), [
    ['user','Inspect'],['assistant','I can inspect that.'],['user','Continue'],
  ]);
  assert.equal('tool_calls' in request.messages[1], false);
});

test('a failed retry can be retried again without adding or replaying failed answers', () => {
  const history = [
    {role:'user',content:'Question'},
    {role:'assistant',content:'partial 1',status:'failed'},
    {role:'assistant',content:'partial 2',status:'failed'},
  ];
  const retried = prepareRetryTurn(history, {});
  assert.equal(retried.messages.length, 4);
  assert.deepEqual(chatRequest('model',retried.messages.slice(0,-1),retried.options).messages,[{role:'user',content:'Question'}]);
});

test('conversation title normalizes multiline and control characters', () => {
  assert.equal(conversationTitleFromMessage('  First line\nSecond\tline  '),'First line Second line');
  assert.equal(conversationTitleFromMessage('  '),'New conversation');
  assert.equal(conversationTitleFromMessage('🙂'.repeat(61)), '🙂'.repeat(60));
});

test('late save from another session does not overwrite active revision', () => {
  const chat = {activeId:'B',revision:4,sessions:[{id:'A',revision:0},{id:'B',revision:4}]};
  applySavedConversation(chat,{id:'A',revision:1,title:'A saved'});
  assert.equal(chat.activeId,'B');
  assert.equal(chat.revision,4);
  assert.equal(chat.sessions.find((session) => session.id === 'A').revision,1);
});

test('chat has named conversation, message and generation regions with drawer controls', () => {
  const html = renderChat({snapshot:{engine:{state:'ready',model:'Qwen'},settings:{},capabilities:{chat:true,streaming:true}},chat:{sessions:[],messages:[],options:{},settingsOpen:null}});
  for (const name of ['对话列表','消息','生成设置']) assert.match(html,new RegExp(`aria-label="${name}"`));
  assert.match(html,/data-action="chat-settings-toggle"/);
  assert.match(html,/data-action="chat-settings-close"/);
  assert.match(html,/data-form="chat-settings"/);
  assert.doesNotMatch(html,/\bNaN\b/);
  assert.doesNotMatch(html,/data-action="(?:upload|web-search|tool-execute)"/);
  const css=readFileSync(new URL('../web/app.css',import.meta.url),'utf8');
  assert.match(css,/\.tf-chat-layout\s*\{[^}]*grid-template-columns:[^}]*minmax\(0,1fr\)[^}]*280px/);
  assert.match(css,/\.tf-chat-layout\s*\{[^}]*grid-template-rows:minmax\(0,1fr\)/);
  assert.match(css,/\.tf-chat-settings\s*\{[^}]*position:static;[^}]*height:auto/);
});

test('stopped chat explains the saved conversation is available but inference is not', () => {
  const html=renderChat({snapshot:{engine:{state:'stopped'},settings:{},capabilities:{chat:true,streaming:true}},chat:{sessions:[{id:'one',title:'Saved'}],activeId:'one',messages:[{role:'user',content:'Remember this'}],options:{}}});
  assert.match(html,/Remember this/);
  assert.match(html,/引擎尚未就绪/);
  assert.match(html,/data-action="goto" data-value="models"/);
});

test('language rerender saves and restores composer and generation drafts', () => {
  const app=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
  assert.match(app,/const draft = captureFormDraft\(pageElement\)/);
  assert.match(app,/renderCurrent\(\);\s*restoreFormDraft\(pageElement, draft\)/);
  assert.match(app,/const messageScroll = pageElement\.querySelector\('#chat-messages'\)\?\.scrollTop/);
  assert.match(app,/pageElement\.querySelector\('#chat-messages'\)\.scrollTop = messageScroll/);
});
