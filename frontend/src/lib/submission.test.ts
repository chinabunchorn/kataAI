import { describe, expect, it } from 'vitest'
import { prepareSubmission, validateQuestion } from './submission'
describe('payload preparation', () => {
  it('binds a trimmed question to the original File without invented server IDs or runtime fields', () => {
    const file = new File(['a,b\n1,2'], 'sales.csv', { type: 'text/csv' })
    const draft = prepareSubmission(
      '  Which product fell most?  ',
      { file, headers: ['a', 'b'], rowCount: 1, preview: [['1', '2']] },
      'test-client-id',
    )
    expect(draft.attachment).toBe(file)
    expect(draft.metadata).toEqual({
      schema_version: '1.0',
      client_request_id: 'test-client-id',
      question: 'Which product fell most?',
      file: { name: 'sales.csv', size_bytes: file.size, mime_type: 'text/csv', encoding: 'utf-8' },
      client_hints: { row_count: 1, column_names: ['a', 'b'] },
    })
    expect(JSON.stringify(draft.metadata)).not.toContain('preview')
    expect(JSON.stringify(draft.metadata)).not.toContain('runtime')
  })
})
describe('question validation', () => {
  it('bounds questions to 4000 characters', () => {
    expect(validateQuestion('x'.repeat(4001))).toBe(
      'Keep your question to 4,000 characters or fewer.',
    )
    expect(validateQuestion('x'.repeat(4000))).toBeUndefined()
    expect(validateQuestion('Which product fell most?')).toBeUndefined()
  })
  it('requires a meaningful question rather than whitespace', () => {
    expect(validateQuestion('   ')).toBe('Enter a question about your dataset.')
  })
})
