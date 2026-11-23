import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SearchPipeline from '../SearchPipeline';

afterEach(cleanup);
it('검색 설계 초안에서 단계의 상태를 읽고 관련 분석 도구와 API 계약을 연다', async () => {
  const user = userEvent.setup(), navigate = vi.fn();
  render(<SearchPipeline active onNavigate={navigate}/>);
  const query = screen.getByText('검색 엔드포인트', {selector:'summary'}).closest('details')!;
  expect(query.open).toBe(true);
  expect(screen.getByRole('heading',{name:/리랭커.*후보/})).toBeTruthy();
  await user.click(screen.getAllByRole('button',{name:'임베딩 평가 열기'})[0]);
  expect(navigate).toHaveBeenCalledWith('embedding');
  const contract = screen.getByText(/API 계약/, {selector:'summary'});
  await user.click(contract);
  expect(contract.closest('details')?.open).toBe(true);
  expect(screen.getByText(/POST \/search/, {selector:'pre'})).toBeTruthy();
});
