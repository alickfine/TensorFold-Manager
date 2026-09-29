const MAX_NATIVE_BYTES = 10 * 1024 * 1024;
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}\.(?:csv|json|txt|log)$/i;

export async function exportTextFile({
  name,
  content,
  webkit = globalThis.window?.webkit,
  documentRef = globalThis.document,
  urlApi = globalThis.URL,
} = {}) {
  if (!SAFE_NAME.test(name) || name.includes('..')) throw new TypeError('Export filename is not safe');
  const text = String(content ?? '');
  const byteLength = new TextEncoder().encode(text).byteLength;
  if (byteLength > MAX_NATIVE_BYTES) throw new RangeError('Export exceeds the 10 MiB native save limit');

  const bridge = webkit?.messageHandlers?.exportFile;
  if (bridge?.postMessage) {
    const reply = await bridge.postMessage({ name, content:text });
    return { saved:Boolean(reply?.saved) };
  }

  if (!documentRef || !urlApi?.createObjectURL) throw new Error('No file export mechanism is available');
  const blob = new Blob([text], { type:'text/plain;charset=utf-8' });
  const url = urlApi.createObjectURL(blob);
  const link = documentRef.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  urlApi.revokeObjectURL(url);
  return { saved:true };
}
