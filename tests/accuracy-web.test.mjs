import test from 'node:test';
import assert from 'node:assert/strict';
import { renderAccuracy } from '../web/views/accuracy.js';
test('reference tests show explicit scoring, actual partial results and safe text', () => {
 const result=renderAccuracy({snapshot:{engine:{state:'attached'},capabilities:{accuracy:{supported:true}},jobs:[]},pageData:{accuracy:{cases:[{id:'c',name:'Case',prompt:'<img>',expected:'yes',match:'contains',max_tokens:8}],results:[{id:'r',status:'cancelled',completed:1,total:2,passed:1,agreement_rate:1,results:[{case:{name:'Case',expected:'yes'},output:'<script>',passed:true,metrics:{output_tokens:3}}]}]}}});
 assert.match(result,/参考答案一致性/);assert.match(result,/&lt;script&gt;/);assert.match(result,/cancelled/);assert.match(result,/1 \/ 2/);assert.match(result,/accuracy-run/);assert.doesNotMatch(result,/disabled[^>]*>运行全部/);
});
test('empty reference queue cannot run or imply a measured score', () => {
 const result=renderAccuracy({snapshot:{engine:{state:'stopped'}},pageData:{}});
 assert.match(result,/尚无参考测试结果/);assert.match(result,/请先添加参考测试/);assert.doesNotMatch(result,/100%/);
});
