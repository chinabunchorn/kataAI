import Papa from 'papaparse'
export const MAX_FILE_BYTES = 128 * 1024
export type CsvDataset = { file: File; headers: string[]; rowCount: number; preview: string[][] }
export async function inspectCsv(file: File): Promise<CsvDataset> {
  if (!file.name.toLowerCase().endsWith('.csv'))
    throw new Error('Choose a .csv file. Other formats are not supported yet.')
  if (!file.size)
    throw new Error('This file is empty. Choose a CSV with a header and at least one data row.')
  if (file.size > MAX_FILE_BYTES) throw new Error('Choose a CSV no larger than 128 KiB.')
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = () => reject(new Error('This file could not be read. Please choose it again.'))
    reader.readAsArrayBuffer(file)
  })
  let text: string
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    throw new Error('Save your CSV as UTF-8 and try again.')
  }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text))
    throw new Error('This file contains unsupported control characters.')
  const parsed = Papa.parse<string[]>(text, { delimiter: ',', skipEmptyLines: 'greedy' })
  if (parsed.errors.length)
    throw new Error('The CSV contains malformed quotes. Check the file and try again.')
  const [rawHeaders = [], ...rows] = parsed.data
  const headers = rawHeaders.map((header) => header.trim())
  if (!headers.length || headers.some((header) => !header))
    throw new Error('Every column needs a non-empty header.')
  if (new Set(headers).size !== headers.length)
    throw new Error('Column names must be unique after trimming spaces.')
  if (headers.length > 100) throw new Error('Use a CSV with 100 columns or fewer.')
  if (!rows.length) throw new Error('Add at least one data row below the header.')
  if (rows.length > 10000) throw new Error('Use a CSV with 10,000 data rows or fewer.')
  rows.forEach((row, index) => {
    if (row.length !== headers.length)
      throw new Error(
        `Row ${index + 2} has ${row.length} field${row.length === 1 ? '' : 's'}; expected ${headers.length}.`,
      )
  })
  return { file, headers, rowCount: rows.length, preview: rows.slice(0, 5) }
}
