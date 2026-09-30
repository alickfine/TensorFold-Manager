import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const qwen = {id:'/Models/Qwen',name:'Qwen',repo:'org/qwen',path:'/Models/Qwen',installed:true,supported:true,startable:true,config:{}};
const evil = { ...qwen,id:'/Models/<model>',name:'<model>',repo:'org/evil',path:'/Models/'+'very-long-'.repeat(40)+'<model>' };
const state = {snapshot:{models:[qwen,evil],engine:{state:'stopped'},settings:{selected_model:qwen.id},update:{active:{version:'v1'}}},pageData:{profiles:{profiles:[]},catalog:{models:[{repo:'org/qwen',name:'Qwen',supported:true},{repo:'org/no',name:'No',supported:false}]},jobs:{jobs:[{id:'d1',kind:'download',status:'running',params:{repo:'org/qwen'},progress:{}}]}},routeQuery:new URLSearchParams()};

test('model workspace has library and downloads tabs with supported entries and jobs', async () => {
  const {renderModelWorkspace}=await import('../web/views/model-workspace.js');
  const library=renderModelWorkspace(state);
  assert.match(library, /<h1>模型库<\/h1>/);
  assert.ok(library.indexOf('<h1>') < library.indexOf('tf-composed-section'), 'visible page title must precede hidden child headings');
  assert.match(library,/data-value="models:library"/);
  assert.match(library,/data-value="models:downloads"/);
  assert.match(library,/data-form="model-config-save"/);
  const downloads=renderModelWorkspace({...state,routeQuery:new URLSearchParams('section=downloads')});
  assert.match(downloads,/data-form="download-create"/);
  assert.match(downloads,/org\/qwen/);
  assert.doesNotMatch(downloads,/org\/no/);
  assert.match(downloads,/data-action="job-action"/);
});

test('model search matches name, repository and path without mutating source', async () => {
  const {filterModels}=await import('../web/views/model-workspace.js');
  const models=[qwen,evil];
  assert.deepEqual(filterModels(models,'qwen'),[qwen]);
  assert.deepEqual(filterModels(models,'<MODEL>'),[evil]);
  assert.deepEqual(filterModels(models,'org/qwen'),[qwen]);
  assert.deepEqual(filterModels(models,'very-long-'),[evil]);
  assert.deepEqual(models,[qwen,evil]);
});

test('model text is escaped and long paths scroll inside their table', async () => {
  const {renderModelWorkspace}=await import('../web/views/model-workspace.js');
  const output=renderModelWorkspace(state);
  assert.match(output,/&lt;model&gt;/);
  assert.doesNotMatch(output,/<model>/);
  const css=readFileSync(new URL('../web/app.css',import.meta.url),'utf8');
  assert.match(css,/\.tf-model-list\s+\.tf-table-wrap\s*\{[^}]*overflow:auto/);
});
