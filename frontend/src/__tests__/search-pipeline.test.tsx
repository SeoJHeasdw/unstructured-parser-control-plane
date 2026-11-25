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
  expect(screen.getByRole('heading', {name: '리랭커'})).toBeTruthy();
  expect(screen.getByText('상위 후보를 다시 읽어 순서를 매긴다')).toBeTruthy();
  expect(screen.getAllByText('MRR@10 · nDCG@10').length).toBeGreaterThan(0);
  await user.click(screen.getByRole('button', {name: /자세히/}));
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
