export const MAX_MESSAGE_LENGTH = 1200;
export const MAX_HISTORY_ITEMS = 12;
export const WELCOME_MESSAGE = 'Bonjour, posez-moi une question sur un client, un projet, un rapport ou un historique d echanges.';
export function prepareOutgoingMessage(draft) {
    const message = draft.trim();
    if (!message || message.length > MAX_MESSAGE_LENGTH) {
        return null;
    }
    return message;
}
export function buildRequestHistory(messages) {
    return messages
        .slice(-MAX_HISTORY_ITEMS)
        .filter((item) => !(item.role === 'agent' && item.content === WELCOME_MESSAGE))
        .map((item) => ({ role: item.role, content: item.content }));
}
