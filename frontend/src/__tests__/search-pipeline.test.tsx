import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SearchPipeline from '../SearchPipeline';

afterEach(cleanup);

it('흐름 지도에서 단계를 누르면 하는 일 · 후보 · 재는 것 · 정할 것과 관련 도구가 보인다', async () => {
  const user = userEvent.setup(), navigate = vi.fn();
  render(<SearchPipeline active onNavigate={navigate}/>);
  expect(screen.getByText(/단계를 누르면/)).toBeTruthy();
  await user.click(screen.getByRole('button', {name: '리랭커 · 후보'}));
  const inspector = screen.getByRole('heading', {name: '리랭커'}).closest('.sp-inspect') as HTMLElement;
  expect(within(inspector).getByText('상위 후보를 다시 읽어 순서를 매긴다')).toBeTruthy();
  expect(within(inspector).getByText('MRR@10 · nDCG@10')).toBeTruthy();
  expect(within(inspector).getByText('결과 융합', {exact: false})).toBeTruthy();
  await user.click(within(inspector).getByRole('button', {name: /자세히/}));
  expect(screen.getByText(/앞 단계가 가져오지 못한 청크는 리랭커가 살릴 수 없습니다/)).toBeTruthy();

  await user.click(screen.getByRole('button', {name: '의미 검색 · 후보'}));
  await user.click(screen.getByRole('button', {name: /임베딩 평가 열기/}));
  expect(navigate).toHaveBeenCalledWith('embedding');
});

it('보는 사람에 따라 지도의 초점을 바꾸고, 정할 것에서 해당 단계로 간다', async () => {
  const user = userEvent.setup();
  render(<SearchPipeline active onNavigate={vi.fn()}/>);
  const lens = screen.getByRole('group', {name: '누가 보나'});
  await user.click(within(lens).getByRole('button', {name: /운영자/}));
  expect(screen.getByText('어디서 놓쳤는지 압니다')).toBeTruthy();
  expect(screen.getByRole('button', {name: '요청 확인 · 미정'}).getAttribute('data-dim')).toBe('true');
  expect(screen.getByRole('button', {name: '리랭커 · 후보'}).getAttribute('data-dim')).toBeNull();

  await user.click(within(lens).getByRole('button', {name: /설계자/}));
  expect(screen.getByText(/미정 \d+곳을 함께 정합니다/)).toBeTruthy();

  const asks = screen.getByText('응답 시간 목표와 리랭커 재채점 개수').closest('li')!;
  await user.click(within(asks).getByRole('button', {name: /리랭커/}));
  expect(screen.getByRole('heading', {name: '리랭커'})).toBeTruthy();
  expect(within(lens).getByRole('button', {name: /전체/}).getAttribute('aria-pressed')).toBe('true');
});

it('책임 경계와 API 계약을 그림으로 보이고, JSON 원문은 펼쳐서 본다', async () => {
  const user = userEvent.setup();
  render(<SearchPipeline active onNavigate={vi.fn()}/>);
  expect(screen.getByText('검색 횟수 · 재검색 판단')).toBeTruthy();
  expect(screen.getByText('doc_version · is_latest')).toBeTruthy();
  expect(screen.queryByText(/POST \/search/, {selector: 'pre'})).toBeNull();
  await user.click(screen.getByRole('button', {name: /JSON 원문 보기/}));
  expect(screen.getByText(/POST \/search/, {selector: 'pre'})).toBeTruthy();
});

it('에이전트 · 색인 줄은 접혀 있다가 캡슐이나 줄 이름으로 펼치고, 보는 사람을 고르면 필요한 줄이 펼쳐진다', async () => {
  const user = userEvent.setup();
  render(<SearchPipeline active onNavigate={vi.fn()}/>);
  expect(screen.queryByRole('button', {name: '청킹 · 후보'})).toBeNull();
  await user.click(screen.getByRole('button', {name: /펼치기: 원천 수집/}));
  expect(screen.getByRole('button', {name: '청킹 · 후보'})).toBeTruthy();
  const lane = screen.getByRole('button', {name: /색인 파이프라인 · 미리 해 두는 일.*접기/});
  expect(lane.getAttribute('aria-expanded')).toBe('true');
  await user.click(lane);
  expect(screen.queryByRole('button', {name: '청킹 · 후보'})).toBeNull();

  expect(screen.queryByRole('button', {name: '재작성 · 분해 · 에이전트 측'})).toBeNull();
  await user.click(within(screen.getByRole('group', {name: '누가 보나'})).getByRole('button', {name: /설계자/}));
  expect(screen.getByRole('button', {name: '재작성 · 분해 · 에이전트 측'})).toBeTruthy();
  expect(screen.getByRole('button', {name: '원천 수집 · 미정'})).toBeTruthy();
});

it('단계에 올리면 하는 일과 앞 · 다음 단계를 짚고, Esc나 닫기로 고른 단계를 닫는다', async () => {
  const user = userEvent.setup();
  render(<SearchPipeline active onNavigate={vi.fn()}/>);
  const fuse = screen.getByRole('button', {name: '결과 융합 · 후보'});
  await user.hover(fuse);
  const card = screen.getByRole('tooltip');
  expect(within(card).getByText('두 순위를 하나로 합친다')).toBeTruthy();
  expect(within(card).getByText('의미 검색 · 키워드 검색')).toBeTruthy();
  expect(within(card).getByText('리랭커')).toBeTruthy();
  expect(screen.getByRole('button', {name: '의미 검색 · 후보'}).getAttribute('data-trace')).toBe('true');
  expect(screen.getByRole('button', {name: '후처리 · 미정'}).getAttribute('data-trace')).toBeNull();
  await user.unhover(fuse);
  expect(screen.queryByRole('tooltip')).toBeNull();

  const legend = screen.getByRole('list', {name: '상태별 단계 수'});
  await user.hover(within(legend).getByText(/^미정/));
  expect(screen.getByRole('button', {name: '요청 확인 · 미정'}).getAttribute('data-ring')).toBe('true');
  expect(screen.getByRole('button', {name: '리랭커 · 후보'}).getAttribute('data-ring')).toBeNull();

  await user.click(fuse);
  expect(screen.getByRole('heading', {name: '결과 융합'})).toBeTruthy();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('heading', {name: '결과 융합'})).toBeNull();
  await user.click(fuse);
  await user.click(screen.getByRole('button', {name: '고른 단계 닫기'}));
  expect(screen.getByText(/단계를 누르면/)).toBeTruthy();
});
