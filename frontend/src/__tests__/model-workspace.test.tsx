import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ModelWorkspace from '../ModelWorkspace';

const configured = { key: 'primary', label: '모델 연결 예시', base_url: 'http://127.0.0.1:9999/v1', model_id: 'demo-text', api_key_set: true, configured: true };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('모델 연결 화면', () => {
  it('미설정 연결에서는 설정 안내를 먼저 열고 게이트웨이 요청을 실행하지 않는다', async () => {
    const fetchMock = vi.fn(async () => json({ connections: [{ ...configured, base_url: '', model_id: '', api_key_set: false, configured: false }] }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ModelWorkspace />);
    const gateway = await screen.findByRole('region', { name: configured.label });
    expect(within(gateway).getByRole('button', { name: '연결 확인' })).toHaveProperty('disabled', true);
    expect(within(gateway).getByRole('button', { name: '모델 목록 조회' })).toHaveProperty('disabled', true);
    expect(screen.getByText('서버에서 연결 설정하기').closest('details')).toHaveProperty('open', true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/models', { signal: expect.any(AbortSignal) });
  });

  it('설정된 연결은 수동 확인 전으로 표시하고 모델 목록에서 ID를 검색할 수 있다', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (url: string) => url.endsWith('/models/primary/models')
      ? json({ ok: true, status: 200, latency_ms: 11, models: ['demo-text', 'demo-image'] })
      : json({ connections: [configured] }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ModelWorkspace />);
    const gateway = await screen.findByRole('region', { name: configured.label });
    expect(within(gateway).getByText('확인 전')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await user.click(within(gateway).getByRole('button', { name: '모델 목록 조회' }));
    const list = await within(gateway).findByRole('region', { name: /반환된 모델 목록/ });
    expect(within(list).getByText('현재 설정')).toBeTruthy();
    await user.type(within(list).getByRole('searchbox'), 'image');
    expect(within(list).getByText('demo-image')).toBeTruthy();
    expect(within(list).queryByText('demo-text')).toBeNull();
    expect(within(gateway).getByText('확인 전')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith('/api/models/primary/models', { method: 'POST' });
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/test'))).toBe(false);
  });

  it('연결 확인 실패에서 원인을 보여 주고, 재확인 성공 후 상태를 바꾼다', async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (!url.endsWith('/test')) return json({ connections: [configured] });
      attempts += 1;
      return attempts === 1 ? json({ ok: false, status: 403, latency_ms: 12, error: 'HTTP 403' })
        : json({ ok: true, status: 200, latency_ms: 27, model: 'demo-text', reply: 'OK' });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ModelWorkspace />);
    const gateway = await screen.findByRole('region', { name: configured.label });
    await user.click(within(gateway).getByRole('button', { name: '연결 확인' }));
    expect(await within(gateway).findByText('확인 실패')).toBeTruthy();
    expect(within(gateway).getByText('서버의 API 키와 게이트웨이 권한을 확인하세요.')).toBeTruthy();
    await user.click(within(gateway).getByRole('button', { name: '연결 확인' }));
    expect(await within(gateway).findByText('응답 확인')).toBeTruthy();
    expect(within(gateway).getByText('27 ms')).toBeTruthy();
    expect(within(gateway).queryByText('HTTP 403')).toBeNull();
  });
});
