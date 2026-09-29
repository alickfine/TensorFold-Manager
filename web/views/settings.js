const STRING_FIELDS = new Set(['selected_model', 'engine_python', 'snapshot_dir']);
const INTEGER_FIELDS = new Set(['engine_port', 'gateway_port', 'context', 'max_tokens', 'top_k', 'parallel']);
const NUMBER_FIELDS = new Set(['temperature', 'top_p', 'prompt_cache_gib', 'mlx_cache_gib']);

export function serializeSettings(values) {
  const output = {};
  for (const [key, raw] of Object.entries(values)) {
    if (raw === undefined) continue;
    if (STRING_FIELDS.has(key)) {
      output[key] = String(raw).trim();
    } else if (key === 'model_dirs') {
      output.model_dirs = (Array.isArray(raw) ? raw : String(raw).split(/\r?\n/))
        .map((item) => String(item).trim())
        .filter(Boolean);
    } else if (key === 'parallel' && raw === 'auto') {
      output.parallel = 'auto';
    } else if (INTEGER_FIELDS.has(key) || NUMBER_FIELDS.has(key)) {
      if (raw === '' || raw === null) throw new TypeError(`${key} must be a number`);
      const number = Number(raw);
      if (!Number.isFinite(number) || (INTEGER_FIELDS.has(key) && !Number.isInteger(number))) {
        throw new TypeError(`${key} must be a valid ${INTEGER_FIELDS.has(key) ? 'integer' : 'number'}`);
      }
      output[key] = number;
    } else if (key === 'thinking') {
      output.thinking = raw === true || raw === 'true' || raw === 'on' || raw === '1';
    }
  }
  return output;
}
