export function dispatchDocumentClick(event, { navigate, handleAction, onError = () => {} }) {
  const pageButton = event.target?.closest?.('button[data-page]');
  if (pageButton) {
    navigate(pageButton.dataset.page);
    return 'navigation';
  }
  const button = event.target?.closest?.('[data-action]');
  if (!button || button.disabled || !button.dataset.action) return null;
  event.preventDefault();
  try {
    Promise.resolve(handleAction(button.dataset.action, button.dataset.value ?? '', button)).catch((error) => onError(error, button.dataset.action));
  } catch (error) {
    onError(error, button.dataset.action);
  }
  return 'action';
}
