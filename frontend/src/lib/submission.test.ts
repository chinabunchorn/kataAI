import { expect, it } from 'vitest'
import { validateQuestion } from './submission'
it('validates actual backend question bounds', () => {
  expect(validateQuestion('   ')).toBeTruthy()
  expect(validateQuestion('q'.repeat(4096))).toBeUndefined()
  expect(validateQuestion('q'.repeat(4097))).toBeTruthy()
})
