export function parseChatOptions(values = {}, defaults = {}) {
  const result = { system_prompt:String(values.system_prompt ?? ''), tools_json:String(values.tools_json ?? ''), tool_choice:values.tool_choice ?? 'auto' };
  if (result.system_prompt.length > 65536 || result.tools_json.length > 262144) throw new TypeError('提示词或工具声明过长');
  for (const [name, low, high] of [['temperature',0,5],['top_p',0,1],['max_tokens',1,32768]]) {
    const value = Number(values[name] ?? defaults[name] ?? ({temperature:0.6,top_p:0.95,max_tokens:1024})[name]);
    if (!Number.isFinite(value) || value < low || value > high || (name==='max_tokens' && !Number.isInteger(value))) throw new TypeError(`${name} 超出范围`);
    result[name] = value;
  }
  result.enable_thinking = values.enable_thinking === undefined ? defaults.thinking !== false : ['true',true,'on'].includes(values.enable_thinking);
  if (values.seed !== undefined && values.seed !== '') {
    const seed = Number(values.seed);
    if (!Number.isSafeInteger(seed) || seed < 0 || seed > 2147483647) throw new TypeError('seed 必须为非负整数');
    result.seed = seed;
  }
  if (!['auto','none'].includes(result.tool_choice)) throw new TypeError('不支持的 tool_choice');
  if (result.tools_json.trim()) {
    let tools;
    try { tools = JSON.parse(result.tools_json); } catch { throw new TypeError('工具 JSON 无效'); }
    if (!Array.isArray(tools) || tools.length > 64 || tools.some(tool => tool?.type !== 'function' || !/^[A-Za-z0-9_-]{1,64}$/.test(tool?.function?.name ?? '') || typeof tool.function.parameters !== 'object' || !tool.function.parameters || Array.isArray(tool.function.parameters))) throw new TypeError('工具必须是标准 function 声明数组');
    result.tools = tools;
  }
  return result;
}

export function chatRequest(model, messages, options) {
  const {system_prompt,tools_json,...parameters} = options;
  const history = messages.filter(message => message.role !== 'system').map(({role,content,tool_calls,tool_call_id}) => ({role,content,...(tool_calls ? {tool_calls} : {}),...(tool_call_id ? {tool_call_id} : {})}));
  if (system_prompt) history.unshift({role:'system',content:system_prompt});
  return {model,messages:history,...parameters};
}
