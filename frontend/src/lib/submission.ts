export const MAX_QUESTION_LENGTH = 4096
export function validateQuestion(value: string): string | undefined {
  if (!value.trim()) return 'Enter a question about your dataset.'
  if (value.length > MAX_QUESTION_LENGTH) return 'Keep your question to 4,096 characters or fewer.'
  return undefined
}
