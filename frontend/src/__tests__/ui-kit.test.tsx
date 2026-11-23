import { afterEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HoverMenu, ListBox, Modal, Segmented, Tabs, TooltipLayer } from '../ui';

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

describe('툴팁과 호버 메뉴', () => {
  it('data-tip 요소에 머물면 이름과 단축키를 띄우고, Esc로 닫은 뒤 벗어날 때까지 다시 열지 않는다', async () => {
    const user = userEvent.setup();
    render(<><TooltipLayer/><button aria-label="되돌리기" data-tip="되돌리기" data-tip-key="⌘Z">↶</button><button>다른 곳</button></>);
    await user.hover(screen.getByRole('button', { name: '되돌리기' }));
    const tip = await screen.findByRole('tooltip', {}, { timeout: 1500 });
    expect(tip.textContent).toBe('되돌리기⌘Z');
    // 접근 가능한 이름과 같은 말이면 설명으로 다시 연결하지 않는다.
    expect(screen.getByRole('button', { name: '되돌리기' }).getAttribute('aria-describedby')).toBeNull();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());
    await user.hover(screen.getByRole('button', { name: '되돌리기' }));
    await new Promise(resolve => setTimeout(resolve, 500));
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('툴팁 글이 이름과 다르면 설명으로 연결한다', async () => {
    const user = userEvent.setup();
    render(<><TooltipLayer/><button aria-label="작업 추가" data-tip="파싱·변환 같은 처리 단계">+</button></>);
    await user.hover(screen.getByRole('button', { name: '작업 추가' }));
    await screen.findByRole('tooltip', {}, { timeout: 1500 });
    expect(screen.getByRole('button', { name: '작업 추가', description: '파싱·변환 같은 처리 단계' })).toBeTruthy();
  });

  it('data-tip-overflow는 글자가 잘렸을 때만 전체 이름을 띄운다', async () => {
    const user = userEvent.setup();
    render(<><TooltipLayer/><b data-tip="제조기록서_BMR-2026-0842.pdf" data-tip-overflow>제조기록서_BMR-2026-0842.pdf</b><button>다른 곳</button></>);
    const name = screen.getByText('제조기록서_BMR-2026-0842.pdf');
    await user.hover(name);
    await new Promise(resolve => setTimeout(resolve, 500));
    expect(screen.queryByRole('tooltip')).toBeNull();
    await user.unhover(name);
    Object.defineProperties(name, { scrollWidth: { configurable: true, value: 215 }, clientWidth: { configurable: true, value: 90 } });
    await user.hover(name);
    expect((await screen.findByRole('tooltip', {}, { timeout: 1500 })).textContent).toBe('제조기록서_BMR-2026-0842.pdf');
  });

  it('호버 메뉴는 키보드로 열어 현재 값에서 시작하고, Escape로 닫으면 버튼으로 돌아간다', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<HoverMenu label="자동 정렬" icon={null} items={[
      { id: 'TB', label: '세로 정렬', name: '세로 자동 정렬', checked: false, onSelect: () => onSelect('TB') },
      { id: 'LR', label: '가로 정렬', name: '가로 자동 정렬', checked: true, onSelect: () => onSelect('LR') },
    ]}/>);
    const trigger = screen.getByRole('button', { name: '자동 정렬' });
    trigger.focus();
    await user.keyboard('{ArrowDown}');
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: '가로 자동 정렬' }));
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: '세로 자동 정렬' }));
    await user.keyboard('{Escape}');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(trigger);
    await user.keyboard('{Enter}');
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('LR');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
  });
});
