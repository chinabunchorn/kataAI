import { describe, expect, it } from 'vitest'
import { inspectCsv, MAX_FILE_BYTES } from './csv'
const file = (text: string, name = 'sales.csv') => new File([text], name, { type: 'text/csv' })
describe('CSV intake', () => {
  it.each([
    ['product,units\n', 'Add at least one data row below the header.'],
    ['product,\nPen,2', 'Every column needs a non-empty header.'],
    ['product, product\nPen,2', 'Column names must be unique after trimming spaces.'],
    ['a,b\n1', 'Row 2 has 1 field; expected 2.'],
    ['a,b\n"unclosed,2', 'The CSV contains malformed quotes. Check the file and try again.'],
    ['a,b\n1,\u0000', 'This file contains unsupported control characters.'],
    [
      Array.from({ length: 101 }, (_, i) => `c${i}`).join(',') +
        '\n' +
        Array(101).fill('1').join(','),
      'Use a CSV with 100 columns or fewer.',
    ],
    ['a\n' + Array(10001).fill('1').join('\n'), 'Use a CSV with 10,000 data rows or fewer.'],
  ])('rejects a CSV that cannot satisfy the intake contract', async (text, error) => {
    await expect(inspectCsv(file(text))).rejects.toThrow(error)
  })
  it('rejects invalid UTF-8 with an actionable error', async () => {
    await expect(
      inspectCsv(new File([new Uint8Array([0xff, 0xfe, 0x00])], 'bad.csv')),
    ).rejects.toThrow('Save your CSV as UTF-8 and try again.')
  })
  it('handles a BOM, blank lines and a safe five-row preview without executing cell contents', async () => {
    const result = await inspectCsv(
      file(
        '\ufeff product , units \n\n' + Array.from({ length: 7 }, (_, i) => `=1+1,${i}`).join('\n'),
      ),
    )
    expect(result.headers).toEqual(['product', 'units'])
    expect(result.rowCount).toBe(7)
    expect(result.preview).toHaveLength(5)
    expect(result.preview[0][0]).toBe('=1+1')
  })
  it.each([
    [file('a,b\n1,2', 'notes.txt'), 'Choose a .csv file. Other formats are not supported yet.'],
    [file(''), 'This file is empty. Choose a CSV with a header and at least one data row.'],
    [file('x'.repeat(MAX_FILE_BYTES + 1)), 'Choose a CSV no larger than 128 KiB.'],
  ])('rejects unsupported or oversized inputs before parsing', async (input, message) => {
    await expect(inspectCsv(input)).rejects.toThrow(message)
  })
  it('parses a UTF-8 CSV with quoted commas into a bounded preview', async () => {
    const result = await inspectCsv(file('product,units\r\n"Pen, blue",45\r\nNotebook,80\r\n'))
    expect(result.headers).toEqual(['product', 'units'])
    expect(result.rowCount).toBe(2)
    expect(result.preview).toEqual([
      ['Pen, blue', '45'],
      ['Notebook', '80'],
    ])
    expect(result.file.name).toBe('sales.csv')
  })
})
