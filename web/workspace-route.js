const pages = new Set(['overview', 'models', 'activity', 'settings', 'chat']);
const legacy = {
  stats:['overview'], downloads:['models', 'downloads'],
  logs:['activity', 'logs'], benchmark:['activity', 'benchmark'],
  cache:['settings', 'storage'], 'engine-config':['settings', 'runtime'],
  server:['settings', 'runtime'], api:['settings', 'api'], updates:['settings', 'updates'],
};

export function resolveWorkspaceRoute(hash) {
  const raw = String(hash ?? '').replace(/^#/, '');
  const separator = raw.indexOf('?');
  const candidate = separator < 0 ? raw : raw.slice(0, separator);
  const query = new URLSearchParams(separator < 0 ? '' : raw.slice(separator + 1));
  const [page, section] = legacy[candidate] ?? (pages.has(candidate) ? [candidate] : ['overview']);
  if (section && !query.has('section')) query.set('section', section);
  return { page, query };
}
