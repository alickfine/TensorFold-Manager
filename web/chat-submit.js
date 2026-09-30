import { assertChatCanSubmit } from './contracts.js';

export async function withChatSubmitLock(chat, operation) {
  assertChatCanSubmit(chat.streaming || chat.submitting);
  chat.submitting = true;
  try {
    return await operation();
  } finally {
    chat.submitting = false;
  }
}
