import { useState } from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import { DocumentDrawer } from '../DocumentDrawer';
import type { DocumentItem, Relation } from '../types';

const defaults = {
  source: '예시 문서함', format: 'PDF', size: '1 MB', updated: '오늘', status: '처리 완료',
  stage: '인덱스 반영', parser: 'Docling', ocr: false, note: '', pages: 1, refs: 1, text: '', compare: '',
};
const documents: DocumentItem[] = [
  { ...defaults, id: 'D1', name: '검토 대상.pdf' },
  { ...defaults, id: 'D2', name: '연결 절차서.pdf' },
];
const relations: Relation[] = [{
  id: 'R1', sourceId: 'D1', source: documents[0].name, targetId: 'D2', target: documents[1].name,
  location: '본문 · 2페이지', method: '문서번호 패턴', evidence: '승인된 절차서 참조', status: '연결 완료',
}];

afterEach(cleanup);

it('연결 문서로 이동하고 이전 참조 보기와 열었던 버튼으로 돌아온다', async () => {
  const user = userEvent.setup();
  function TestInventory() {
    const [selected, setSelected] = useState<string>();
    const document = documents.find(item => item.id === selected);
    return <>
      <button type="button" onClick={() => setSelected('D1')}>검토 대상 열기</button>
      {document && <DocumentDrawer doc={document} relations={relations} onClose={() => setSelected(undefined)}
        onCompare={() => {}} onPipeline={() => {}} onOpenRelated={id => { setSelected(id); return true; }} />}
    </>;
  }
  render(<TestInventory />);
  const opener = screen.getByRole('button', { name: '검토 대상 열기' });
  await user.click(opener);

  const dialog = within(screen.getByRole('dialog', { name: '문서 상세' }));
  const info = dialog.getByRole('tab', { name: '문서 정보' });
  await user.click(info);
  await user.keyboard('{End}');
  expect(dialog.getByRole('tab', { name: /문서 간 참조/, selected: true })).toBeTruthy();
  expect(dialog.getByText('나가는 참조')).toBeTruthy();
  expect(dialog.getByText('승인된 절차서 참조')).toBeTruthy();

  await user.click(dialog.getByRole('button', { name: '연결 절차서.pdf 열기' }));
  const linkedHeading = dialog.getByRole('heading', { name: '연결 절차서.pdf' });
  expect(document.activeElement).toBe(linkedHeading);
  await user.click(dialog.getByRole('tab', { name: /문서 간 참조/ }));
  expect(dialog.getByText('들어오는 참조')).toBeTruthy();
  await user.click(dialog.getByRole('button', { name: '검토 대상.pdf' }));
  expect(dialog.getByRole('heading', { name: '검토 대상.pdf' })).toBeTruthy();
  expect(dialog.getByRole('tab', { name: /문서 간 참조/, selected: true })).toBeTruthy();

  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(opener);
});
