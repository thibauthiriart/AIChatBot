export type ChatMessage = {
  role: 'visitor' | 'agent'
  content: string
}

export const MAX_MESSAGE_LENGTH = 1200
export const MAX_HISTORY_ITEMS = 6
export const WELCOME_MESSAGE =
  'Bonjour, posez-moi une question sur le site. Je peux aussi vous orienter vers un premier echange ou un audit selon votre besoin.'

export function prepareOutgoingMessage(draft: string): string | null {
  const message = draft.trim()
  if (!message || message.length > MAX_MESSAGE_LENGTH) {
    return null
  }
  return message
}

export function buildRequestHistory(messages: ChatMessage[]): ChatMessage[] {
  return messages
    .slice(-MAX_HISTORY_ITEMS)
    .filter((item) => !(item.role === 'agent' && item.content === WELCOME_MESSAGE))
    .map((item) => ({ role: item.role, content: item.content }))
}
