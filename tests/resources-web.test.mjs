import test from 'node:test';
import assert from 'node:assert/strict';
import { renderResources } from '../web/views/resources.js';
import { parseApiError } from '../web/api.js';
test('memory UI shows pressure, observed capacity and identified services without inventing zero',()=>{
 const output=renderResources({memory:{physical_bytes:256*1024**3,available_bytes:null,pressure:'warning',swap_used_bytes:2*1024**3,missing:['available_memory']},services:[{pid:123,kind:'tensorfold',model_path:'/models/large',port:8089}],missing:[]});
 assert.match(output,/256.0 GB/);assert.match(output,/未采集/);assert.match(output,/warning/);assert.match(output,/available_memory/);assert.match(output,/123/);assert.match(output,/先释放/);
});
test('resource rejection preserves the actual blocker report for UI',async()=>{
 const report={allowed:false,blockers:['existing_inference_service_must_be_reused_or_stopped_first'],missing:[]};
 const error=await parseApiError(new Response(JSON.stringify({error:{message:'blocked',code:'resource_blocked'},resources:report}),{status:409}));
 assert.deepEqual(error.details?.resources,report);
});
