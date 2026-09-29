const MANAGEMENT_PATH = /^\/api(?:\/|$)/;
let bootstrapPromise;

export class ApiError extends Error {
  constructor(message, { code = 'api_error', status = 0, details = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function parseApiError(response) {
  let payload;
  try {
    payload = await response.clone().json();
  } catch {
    payload = null;
  }
  const protocolError = payload?.error;
  return new ApiError(
    typeof protocolError?.message === 'string' && protocolError.message
      ? protocolError.message
      : `请求失败（HTTP ${response.status}）`,
    {
      code: typeof protocolError?.code === 'string' ? protocolError.code : 'http_error',
      status: response.status,
      details: protocolError?.details ?? null,
    },
  );
}

function assertManagementPath(path) {
  if (typeof path !== 'string' || !MANAGEMENT_PATH.test(path) || path.startsWith('//')) {
    throw new TypeError('API target must be a same-origin management path');
  }
}

export async function resolveBootstrapToken({
  location,
  history,
  webkit,
} = globalThis.window ?? {}) {
  const handler = webkit?.messageHandlers?.bootstrap;
  if (handler?.postMessage) {
    const reply = await handler.postMessage({});
    if (typeof reply?.token !== 'string' || !reply.token || typeof reply?.instance_id !== 'string') {
      throw new ApiError('原生认证握手返回无效', { code: 'bootstrap_invalid' });
    }
    return reply.token;
  }

  const params = new URLSearchParams(location?.search ?? '');
  const host = location?.hostname;
  const isLoopback = host === '127.0.0.1' || host === 'localhost' || host === '::1';
  if (params.get('dev') === '1' && isLoopback) {
    const fragment = new URLSearchParams((location?.hash ?? '').replace(/^#/, ''));
    const token = fragment.get('token');
    if (token) {
      history?.replaceState?.(null, '', `${location.pathname || '/'}${location.search || ''}`);
      return token;
    }
  }
  throw new ApiError('Native bootstrap unavailable; browser testing requires loopback ?dev=1 and a token fragment', {
    code: 'bootstrap_unavailable',
  });
}

export function getAdminToken() {
  bootstrapPromise ??= resolveBootstrapToken();
  return bootstrapPromise;
}

export function createApiClient({ getToken = getAdminToken, fetchImpl = globalThis.fetch } = {}) {
  async function authenticatedFetch(path, options = {}) {
    assertManagementPath(path);
    const token = await getToken();
    const headers = {
      Accept: 'application/json',
      ...(options.headers ?? {}),
      Authorization: `Bearer ${token}`,
    };
    const body = options.body;
    if (body !== undefined && body !== null && !(body instanceof FormData)) {
      headers['Content-Type'] ??= 'application/json';
    }
    return fetchImpl(path, {
      ...options,
      headers,
      credentials: 'same-origin',
      body: body !== undefined && body !== null && headers['Content-Type'] === 'application/json'
        ? JSON.stringify(body)
        : body,
    });
  }

  async function request(path, options = {}) {
    const response = await authenticatedFetch(path, options);
    if (!response.ok) throw await parseApiError(response);
    if (response.status === 204) return {};
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      throw new ApiError('服务返回了非 JSON 响应', { code: 'invalid_response', status: response.status });
    }
    return response.json();
  }

  async function download(path) {
    const response = await authenticatedFetch(path);
    if (!response.ok) throw await parseApiError(response);
    return response.blob();
  }

  async function streamChat(payload, { signal, onDelta, onReasoning, onToolCalls, onUsage } = {}) {
    const response = await authenticatedFetch('/api/chat/completions', {
      method: 'POST',
      body: { ...payload, stream: true },
      signal,
      headers: { Accept: 'text/event-stream' },
    });
    if (!response.ok) throw await parseApiError(response);
    if (!response.body) throw new ApiError('服务未返回流式响应', { code: 'stream_missing' });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = '';
    let result = '';
    let sawDone = false;
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split(/\r?\n/);
      pending = lines.pop() ?? '';
      if (done && pending) {
        lines.push(pending);
        pending = '';
      }
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (!data) continue;
        if (data === '[DONE]') {
          sawDone = true;
          continue;
        }
        let event;
        try {
          event = JSON.parse(data);
        } catch {
          throw new ApiError('流式响应包含无效 JSON', { code: 'invalid_stream' });
        }
        if (event.error) throw new ApiError(event.error.message ?? '推理流返回错误', {code:'upstream_error'});
        const value = event?.choices?.[0]?.delta ?? {};
        if (typeof value.reasoning_content === 'string') onReasoning?.(value.reasoning_content);
        if (Array.isArray(value.tool_calls)) onToolCalls?.(value.tool_calls);
        if (event.usage || event.tensorfold) onUsage?.(event);
        const delta = value.content ?? event?.delta ?? '';
        if (typeof delta === 'string' && delta) {
          result += delta;
          onDelta?.(delta, event);
        }
      }
      if (done) break;
    }
    if (!sawDone) {
      throw new ApiError('流式响应在完成标记前中断，已保留收到的部分内容', { code:'stream_interrupted' });
    }
    return result;
  }

  return { request, download, streamChat };
}

export const api = createApiClient();
