export const MAX_WORKSHEET_ROW = 1_048_576;
export const MAX_WORKSHEET_COLUMN = 16_384;

export function cellCoordinates(address: string) {
  const match = /^([A-Z]{1,3})([1-9][0-9]{0,6})$/.exec(address);
  if (!match) return;
  const column = Array.from(match[1]).reduce((value, letter) => value * 26 + letter.charCodeAt(0) - 64, 0);
  const row = Number(match[2]);
  if (row <= MAX_WORKSHEET_ROW && column <= MAX_WORKSHEET_COLUMN) return { row, column };
}

export function columnName(column: number): string {
  let label = '';
  for (let index = column; index > 0; index = Math.floor((index - 1) / 26)) {
    label = String.fromCharCode(65 + (index - 1) % 26) + label;
  }
  return label;
}
