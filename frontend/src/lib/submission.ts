import type { CsvDataset } from './csv'
export type PreparedSubmission = ReturnType<typeof prepareSubmission>
export function prepareSubmission(
  question: string,
  dataset: CsvDataset,
  id: string = crypto.randomUUID(),
) {
  return {
    attachment: dataset.file,
    metadata: {
      schema_version: '1.0' as const,
      client_request_id: id,
      question: question.trim(),
      file: {
        name: dataset.file.name,
        size_bytes: dataset.file.size,
        mime_type: dataset.file.type || 'text/csv',
        encoding: 'utf-8' as const,
      },
      client_hints: { row_count: dataset.rowCount, column_names: [...dataset.headers] },
    },
  }
}
export const MAX_QUESTION_LENGTH = 4000
export function validateQuestion(value: string): string | undefined {
  if (!value.trim()) return 'Enter a question about your dataset.'
  if (value.length > MAX_QUESTION_LENGTH) return 'Keep your question to 4,000 characters or fewer.'
  return undefined
}
