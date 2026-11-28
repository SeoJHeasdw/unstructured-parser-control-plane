import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { displayWidth, isNumeric, parseInline, parseMarkdown, splitRow, tableLines } from '../markdown';
import { ReviewDesk } from '../compare/ReviewDesk';
import type { ResultLocation } from '../api/live';
import { MarkdownView } from '../MarkdownView';
import { ResultBody } from '../LiveDocumentView';

/* Docling 2.150.0이 합성 DOCX에서 실제로 낸 결과(번호 목록 바로 뒤에 표가 빈 줄 없이 붙는다). */
const DOCLING_DOCX = `# 설비 점검 보고서

## 1. 개요

본 보고서는 냉각수 설비 점검 결과를 정리한다. 보관 온도는 ≤ −70℃를 유지해야 한다.

### 1.1 점검 항목

- 펌프 상태
    - 진동 측정값
    - 소음 기준 초과 여부
- 배관 누수

1. 첫째 절차: 전원 차단
2. 둘째 절차: 압력 해제
| 구분            | 기준            | 결과            |
|---------------|---------------|---------------|
| 온도            | ≤ −70℃        | −72℃ 적합       |
| 압력            | 2.0 ± 0.1 bar | 2.05 bar 적합   |
| 재점검 불필요(병합 셀) | 재점검 불필요(병합 셀) | 재점검 불필요(병합 셀) |

<!-- image -->

결론: 모든 항목이 기준을 만족한다.

<!-- docops:supplement -->
## 보충 추출: 파서 결과에 없던 원본 글자

- [글상자 · 시험 조건!B3:D5 도형] 표 위 글상자: 단위 확인 필요`;

afterEach(() => { cleanup(); localStorage.clear(); });

describe('Markdown 블록 해석', () => {
  it('제목·중첩 목록·번호 목록·붙은 표·그림 자리·보충 구획을 나눈다', () => {
    const blocks = parseMarkdown(DOCLING_DOCX);
    expect(blocks.map(block => block.kind)).toEqual(['heading', 'heading', 'paragraph', 'heading', 'list', 'list', 'table', 'figure', 'paragraph', 'supplement', 'heading', 'list']);
    const bullets = blocks[4];
    expect(bullets.kind === 'list' && bullets.items.map(item => [item.depth, item.text])).toEqual([[0, '펌프 상태'], [1, '진동 측정값'], [1, '소음 기준 초과 여부'], [0, '배관 누수']]);
    const table = blocks[6];
    expect(table.kind === 'table' && table.header).toEqual(['구분', '기준', '결과']);
    expect(table.kind === 'table' && table.rows[1]).toEqual(['압력', '2.0 ± 0.1 bar', '2.05 bar 적합']);
    expect(table.line).toBe(16);
  });

  it('줄을 버리지 않는다: 해석하지 못한 줄과 주석도 남긴다', () => {
    const blocks = parseMarkdown('| 머리글만 있는 줄 |\n그냥 문장\n<!-- 다른 주석 -->\n![로고](image1.png)');
    expect(blocks).toEqual([
      { kind: 'paragraph', text: '| 머리글만 있는 줄 |\n그냥 문장', line: 1 },
      { kind: 'comment', text: '다른 주석', line: 3 },
      { kind: 'figure', text: '로고', line: 4 },
    ]);
  });

  it('표 칸의 \\| 와 모자란 칸을 처리한다', () => {
    expect(splitRow('| a \\| b | c |')).toEqual(['a | b', 'c']);
    const [table] = parseMarkdown('| a | b | c |\n|---|:-:|--:|\n| 1 |');
    expect(table.kind === 'table' && [table.rows[0], table.align]).toEqual([['1', '', ''], [null, 'center', 'right']]);
  });

  it('글자 꾸밈과 이스케이프', () => {
    expect(parseInline('**굵게** *기울임* `a_b` \\_밑줄\\_ [링크](http://x/y)')).toEqual([
      { text: '굵게', bold: true }, { text: ' ' }, { text: '기울임', italic: true }, { text: ' ' }, { text: 'a_b', code: true },
      { text: ' _밑줄_ ' }, { text: '링크', href: 'http://x/y' },
    ]);
    expect(['12.5', '−72℃', '2,048', '25 m²', '±0.5'].every(isNumeric)).toBe(true);
    expect(['−72℃ 적합', '적합', 'A-1'].some(isNumeric)).toBe(false);
  });
});

describe('읽기 보기', () => {
  it('표는 표로, 목록은 단계대로 그리고 링크는 열 수 없게 둔다', () => {
    render(<MarkdownView markdown={DOCLING_DOCX + '\n\n[위험](javascript:alert)'} />);
    const table = screen.getByRole('region', { name: '표 · 3행 3열' });
    expect(within(table).getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['구분', '기준', '결과']);
    expect(within(table).getByRole('cell', { name: '2.05 bar 적합' })).toBeTruthy();
    const nested = screen.getByText('진동 측정값').closest('ul');
    expect(nested?.parentElement?.closest('li')?.firstChild?.textContent).toBe('펌프 상태');
    expect(screen.getByRole('heading', { name: '1.1 점검 항목' }).tagName).toBe('H4');
    expect(screen.getByText('그림 자리')).toBeTruthy();
    expect(screen.getByText(/콘솔이 원본에서 보충한 글자/)).toBeTruthy();
    expect(document.querySelector('a')).toBeNull();
    expect(screen.getByText('위험').closest('[data-tip]')?.getAttribute('data-tip')).toBe('javascript:alert');
  });

  it('같은 깊이에서 번호와 글머리표가 섞이면 원래 표지를 보이고, 번호만 있으면 번호 목록으로 그린다', () => {
    const { unmount } = render(<MarkdownView markdown={'- 가 항목\n3. 나 항목\n- 다 항목'} />);
    const mixed = screen.getByText('나 항목').closest('li');
    expect(mixed?.parentElement?.tagName).toBe('UL');
    expect(mixed?.getAttribute('data-marker')).toBe('3.');
    expect(screen.getByText('가 항목').closest('li')?.hasAttribute('data-marker')).toBe(false);
    unmount();
    render(<MarkdownView markdown={'3. 나 항목\n4. 다 항목'} />);
    const list = screen.getByText('나 항목').closest('ol');
    expect(list?.getAttribute('start')).toBe('3');
    expect(list?.querySelector('[data-marker]')).toBeNull();
  });

  it('숫자만 든 열은 오른쪽 정렬한다', () => {
    render(<MarkdownView markdown={'| 항목 | 값 |\n|---|---|\n| 온도 | 12.5 |\n| 면적 | 25 m² |'} />);
    expect((screen.getByRole('cell', { name: '12.5' }) as HTMLElement).style.textAlign).toBe('right');
    expect((screen.getByRole('cell', { name: '온도' }) as HTMLElement).style.textAlign).toBe('');
  });

  it('블록이 많으면 나눠 그린다', async () => {
    render(<MarkdownView markdown={Array.from({ length: 450 }, (_, i) => `문단 ${i + 1}`).join('\n\n')} />);
    expect(screen.queryByText('문단 401')).toBeNull();
    await userEvent.setup().click(screen.getByRole('button', { name: /다음 50개 블록 더 보기/ }));
    expect(screen.getByText('문단 450')).toBeTruthy();
  });

  it('보기 방식을 기억하고, 원문은 저장된 글자 그대로다', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ResultBody markdown={DOCLING_DOCX} />);
    expect(document.querySelector('.md-view')).not.toBeNull();
    await user.click(screen.getByRole('radio', { name: 'Markdown 원문' }));
    expect(document.querySelector('.live-result-content.is-raw')?.textContent).toBe(DOCLING_DOCX);
    unmount();
    render(<ResultBody markdown={DOCLING_DOCX} />);
    expect(screen.getByRole('radio', { name: 'Markdown 원문' }).getAttribute('aria-checked')).toBe('true');
  });
});

describe('원문 대조의 추출 결과', () => {
  it('표 줄은 같은 칸 너비(한글 2칸 폭)로, 줄 번호는 그대로 둔다', async () => {
    expect([displayWidth('구분'), displayWidth('2.0 ± 0.1 bar'), displayWidth('−72℃ 적합')]).toEqual([4, 13, 9]);
    const map = tableLines(DOCLING_DOCX);
    expect([map.get(16)?.role, map.get(17)?.role, map.get(18)?.cells, map.get(20)?.role, map.has(21)]).toEqual(['head', 'rule', ['온도', '≤ −70℃', '−72℃ 적합'], 'row', false]);
    expect(new Set([16, 17, 18, 19, 20].map(line => map.get(line)?.columns)).size).toBe(1);
    const user = userEvent.setup();
    render(<ReviewDesk mode="source" onMode={() => {}} canCompare={false} original={<p>원본</p>} summary={null}
      sourcePane={{ text: DOCLING_DOCX, locations: [], meta: null }} onLocation={() => {}} />);
    const lines = document.querySelectorAll('.source-line');
    expect(lines.length).toBe(DOCLING_DOCX.split('\n').length);
    expect(Array.from(lines[17].querySelectorAll('.source-cells > span')).map(cell => cell.textContent)).toEqual(['온도', '≤ −70℃', '−72℃ 적합']);
    expect(lines[17].querySelector('small')?.textContent).toBe('18');
    await user.click(screen.getByRole('radio', { name: 'Markdown 원문' }));
    expect(document.querySelectorAll('.source-line')[17].textContent).toBe('18| 온도            | ≤ −70℃        | −72℃ 적합       |');
  });
});

describe('원문 대조 근거 버튼', () => {
  it('같은 위치가 여러 줄에 걸치면 첫 줄에만 달고, PPTX는 슬라이드로 부른다', () => {
    const text = '# 측정 결과\n\n| 구분 | 결과 |\n|---|---|\n| 온도 | −72℃ |\n\n다음 슬라이드';
    const locations = [{ start_line: 1, end_line: 5, page: 3 }, { start_line: 7, end_line: 7, page: 4 }] as ResultLocation[];
    render(<ReviewDesk mode="source" onMode={() => {}} canCompare={false} original={<p>원본</p>} summary={null}
      sourcePane={{ text, locations, meta: null, pageUnit: 'slide' }} onLocation={() => {}} />);
    expect(screen.getAllByRole('button', { name: '슬라이드 3' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '슬라이드 4' })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /원문 3쪽/ })).toBeNull();
  });
});
