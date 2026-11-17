import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { goldCategories, lost, measure, scoreGold } from '../compare/metrics';
import { RunSummary } from '../compare/RunSummary';

afterEach(() => cleanup());

const BEFORE = `# 시험 결과\n\n| 항목 | 결과 |\n| --- | --- |\n| pH | 6.1 |\n| 단백질 | 10.2 mg/mL |\n\n본 로트는 SOP-QC-0040 기준에 적합하다. 보관 온도 5 °C.\n<!-- image -->`;
const AFTER = `# 시험 결과\n\n| 항목 | 결과 |\n| --- | --- |\n| pH | 6.1 |\n| 단백질 | 10.2 mg/m� |\n\n본 로트는 기준에 적합하다. 보관 온도 5 °C.`;

describe('파싱 실행 비교 수치', () => {
  it('표·칸·그림 자리·숫자·문서번호·깨진 글자를 센다', () => {
    const a = measure(BEFORE); const b = measure(AFTER);
    expect([a.tables, a.cells, a.headings, a.images]).toEqual([1, 6, 1, 1]);
    expect([...a.numbers].sort()).toEqual(['10.2mg/mL', '5°C']);
    expect([...a.docNumbers]).toEqual(['SOP-QC-0040']);
    expect(b.broken).toBe(1);
    expect(lost(a.numbers, b.numbers)).toEqual(['10.2mg/mL']);
    expect(lost(a.docNumbers, b.docNumbers)).toEqual(['SOP-QC-0040']);
  });

  it('정답 자료의 값을 띄어쓰기와 무관하게 찾는다', () => {
    const categories = goldCategories({ key_values: [{ label: '로트', value: '2026A031' }], tables: [{ header: ['항목', '결과'], rows: [['단백질', '10.2 mg/mL']] }], numbers_with_units: ['10.2 mg/mL'] });
    const scores = scoreGold(BEFORE, categories);
    expect(scores.find(row => row.id === 'key_values')).toMatchObject({ total: 1, found: 0, missing: ['2026A031'] });
    expect(scores.find(row => row.id === 'cells')).toMatchObject({ total: 4, found: 4 });
    expect(scoreGold(AFTER, categories).find(row => row.id === 'numbers')).toMatchObject({ found: 0 });
  });

  it('요약 줄은 처리 시간 변화와 사라진 숫자를 보여 주고, 팝업에서 정답 자료로 두 실행을 잰다', async () => {
    const user = userEvent.setup();
    render(<RunSummary before={{ text: BEFORE, label: '10/14 · v1', durationMs: 2000 }} after={{ text: AFTER, label: '10/16 · v2', durationMs: 1500 }} />);
    const strip = screen.getByRole('region', { name: '두 실행의 변화' });
    expect(within(strip).getByText('1.50 초')).toBeTruthy();
    expect(within(strip).getByText(/−500 ms \(−25%\)/).className).toContain('is-good');
    expect(within(strip).getByText('1개 사라짐')).toBeTruthy();
    await user.click(within(strip).getByRole('button', { name: /정답 대조/ }));
    const dialog = screen.getByRole('dialog', { name: '두 실행 비교' });
    const gold = new File([JSON.stringify({ title: '시험 결과', numbers_with_units: ['10.2 mg/mL', '5 °C'] })], 'gold.json', { type: 'application/json' });
    await user.upload(within(dialog).getByLabelText('정답 자료 파일'), gold);
    const total = await within(dialog).findByText('전체');
    const row = total.closest('tr')!;
    expect(row.textContent).toContain('100.0%');
    expect(row.textContent).toContain('50.0%');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
