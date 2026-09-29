function controls(root) {
  return [...(root?.querySelectorAll?.('input, select, textarea') ?? [])];
}

function signature(control) {
  return `${control.tagName ?? ''}:${control.type ?? ''}:${control.id ?? ''}:${control.name ?? ''}`;
}

export function captureFormDraft(root, activeElement = globalThis.document?.activeElement) {
  return controls(root).map((control, index) => control.type === 'file' ? null : ({
    index,
    signature:signature(control),
    name:control.name ?? '',
    value:control.value,
    checked:Boolean(control.checked),
    selectionStart:Number.isInteger(control.selectionStart) ? control.selectionStart : null,
    selectionEnd:Number.isInteger(control.selectionEnd) ? control.selectionEnd : null,
    active:control === activeElement,
  })).filter(Boolean);
}

export function restoreFormDraft(root, draft = []) {
  const next = controls(root);
  for (const item of draft) {
    const control = signature(next[item.index] ?? {}) === item.signature
      ? next[item.index]
      : next.find((candidate) => signature(candidate) === item.signature);
    if (!control) continue;
    if (control.type === 'checkbox' || control.type === 'radio') control.checked = item.checked;
    else control.value = item.value;
    if (item.selectionStart !== null && item.selectionEnd !== null) {
      if (typeof control.setSelectionRange === 'function') control.setSelectionRange(item.selectionStart, item.selectionEnd);
      else {
        control.selectionStart = item.selectionStart;
        control.selectionEnd = item.selectionEnd;
      }
    }
    if (item.active) control.focus?.({ preventScroll:true });
  }
}
