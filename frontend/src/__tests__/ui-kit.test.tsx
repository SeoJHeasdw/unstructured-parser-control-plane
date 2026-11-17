import { afterEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ListBox, Modal, Segmented, Tabs } from '../ui';

afterEach(() => cleanup());

function ModalHarness({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return <>
    <button onClick={() => setOpen(true)}>열기</button>
    <Modal open={open} onClose={() => { onClose?.(); setOpen(false); }} title="파티션 qc" subtitle="청크 14개" footer={<button>확인</button>}>
      <input aria-label="검색" />
    </Modal>
  </>;
}

describe('공통 화면 부품', () => {
  it('팝업은 열면 본문에 초점을 두고, Escape로 닫으면 연 버튼으로 초점을 돌려준다', async () => {
    const user = userEvent.setup(); const onClose = vi.fn();
    render(<ModalHarness onClose={onClose} />);
    await user.click(screen.getByRole('button', { name: '열기' }));
    const dialog = screen.getByRole('dialog', { name: '파티션 qc' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: '검색' }));
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '열기' }));
  });

  it('팝업 안에서 Tab은 밖으로 나가지 않는다', async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    await user.click(screen.getByRole('button', { name: '열기' }));
    await user.tab(); // 검색 → 확인
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '확인' }));
    await user.tab(); // 마지막에서 처음(닫기)으로
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '닫기' }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '확인' }));
  });

  it('탭은 화살표로 옮기고 선택된 내용만 그린다', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [tab, setTab] = useState<'a' | 'b'>('a');
      return <Tabs label="보기" value={tab} onChange={setTab} items={[{ id: 'a', label: '개요' }, { id: 'b', label: '청크', badge: 3 }]}>{active => <p>{active === 'a' ? '개요 내용' : '청크 내용'}</p>}</Tabs>;
    }
    render(<Harness />);
    expect(screen.getByText('개요 내용')).toBeTruthy();
    screen.getByRole('tab', { name: '개요' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: /청크/ }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText('청크 내용')).toBeTruthy();
  });

  it('리스트 박스는 ↑/↓로 바로 선택하고 묶음 머리를 붙인다', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [value, setValue] = useState<string | null>('1');
      const items = [{ id: '1', g: '표', t: '표 1' }, { id: '2', g: '표', t: '표 2' }, { id: '3', g: '그림', t: '그림 1' }];
      return <ListBox label="요소" items={items} getKey={i => i.id} value={value} onChange={setValue} groupBy={i => i.g} render={i => i.t} />;
    }
    render(<Harness />);
    expect(screen.getByText('그림', { selector: '.ui-listbox-group' })).toBeTruthy();
    screen.getByRole('listbox', { name: '요소' }).focus();
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(screen.getByRole('option', { name: '그림 1' }).getAttribute('aria-selected')).toBe('true');
  });

  it('선택 버튼 묶음은 하나만 선택된다', async () => {
    const user = userEvent.setup(); const onChange = vi.fn();
    render(<Segmented label="지표" value="hit5" onChange={onChange} options={[{ id: 'hit1', label: 'Hit@1' }, { id: 'hit5', label: 'Hit@5' }]} />);
    expect(screen.getByRole('radio', { name: 'Hit@5' }).getAttribute('aria-checked')).toBe('true');
    await user.click(screen.getByRole('radio', { name: 'Hit@1' }));
    expect(onChange).toHaveBeenCalledWith('hit1');
  });
});
