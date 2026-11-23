import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ModelWorkspace from '../ModelWorkspace';

const configured = { key: 'primary', label: '모델 연결 예시', base_url: 'http://127.0.0.1:9999/v1', model_id: 'demo-text', api_key_set: true, configured: true };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('모델 연결 화면', () => {
  it('미설정 연결은 화면에서 설정하도록 안내하고 게이트웨이 요청을 실행하지 않는다', async () => {
    const fetchMock = vi.fn(async () => json({ connections: [{ ...configured, base_url: '', model_id: '', api_key_set: false, configured: false }] }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ModelWorkspace />);
    const gateway = await screen.findByRole('region', { name: configured.label });
    expect(within(gateway).getByRole('button', { name: '연결 확인' })).toHaveProperty('disabled', true);
    expect(within(gateway).getByRole('button', { name: '모델 목록 조회' })).toHaveProperty('disabled', true);
    expect(within(gateway).getByRole('button', { name: '연결 설정' })).toBeTruthy();
    expect(screen.getByText('서버 파일로 설정하기 (.env)').closest('details')).toHaveProperty('open', false);
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
    expect(within(gateway).getByText('API 키와 게이트웨이 권한을 확인하세요.')).toBeTruthy();
    await user.click(within(gateway).getByRole('button', { name: '연결 확인' }));
    expect(await within(gateway).findByText('응답 확인')).toBeTruthy();
    expect(within(gateway).getByText('27 ms')).toBeTruthy();
    expect(within(gateway).queryByText('HTTP 403')).toBeNull();
  });

  it('설정 편집 팝업에서 입력한 값으로 먼저 확인하고 저장하며, API 키는 다시 보여 주지 않는다', async () => {
    const user = userEvent.setup();
    const calls: { url: string; method: string; body: Record<string, unknown> | null }[] = [];
    const saved = { ...configured, label: '사내 게이트웨이', base_url: 'http://10.0.0.5:8000/v1', model_id: 'granite', saved: true };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url === '/api/models/draft/test') return json({ ok: true, status: 200, latency_ms: 31, model: 'granite', reply: 'OK' });
      if (url === '/api/models/primary' && init?.method === 'PUT') return json({ connections: [saved], embedding: null });
      return json({ connections: [configured], embedding: null });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ModelWorkspace />);
    const gateway = await screen.findByRole('region', { name: configured.label });
    await user.click(within(gateway).getByRole('button', { name: '설정 편집' }));
    const dialog = screen.getByRole('dialog', { name: '기본 연결 설정' });
    const url = within(dialog).getByRole('textbox', { name: 'Base URL' });
    expect(document.activeElement).toBe(url);
    await user.clear(url); await user.type(url, 'http://10.0.0.5:8000/v1');
    await user.clear(within(dialog).getByRole('textbox', { name: '이름' })); await user.type(within(dialog).getByRole('textbox', { name: '이름' }), '사내 게이트웨이');
    await user.clear(within(dialog).getByRole('textbox', { name: '모델 ID' })); await user.type(within(dialog).getByRole('textbox', { name: '모델 ID' }), 'granite');
    expect(within(dialog).getByLabelText('API 키').getAttribute('placeholder')).toContain('저장된 키 유지');
    await user.click(within(dialog).getByRole('button', { name: '저장 전 확인' }));
    expect(await within(dialog).findByText('31 ms')).toBeTruthy();
    expect(calls.find(c => c.url === '/api/models/draft/test')?.body).toMatchObject({ kind: 'chat', key: 'primary', base_url: 'http://10.0.0.5:8000/v1', model_id: 'granite' });
    expect(calls.find(c => c.url === '/api/models/draft/test')?.body).not.toHaveProperty('api_key');
    await user.click(within(dialog).getByRole('button', { name: '저장' }));
    const put = calls.find(c => c.method === 'PUT')!;
    expect(put.body).toEqual({ label: '사내 게이트웨이', base_url: 'http://10.0.0.5:8000/v1', model_id: 'granite' });
    expect(await screen.findByRole('region', { name: '사내 게이트웨이' })).toBeTruthy();
    expect(screen.getByText(/설정을 저장했습니다/)).toBeTruthy();
    expect(screen.getByText('화면에서 저장')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('임베딩 탭에서 모델 ID를 여러 개 넣어 저장한다', async () => {
    const user = userEvent.setup();
    const embedding = { key: 'embed', label: '임베딩 게이트웨이', base_url: '', models: [], api_key_set: false, configured: false, saved: false };
    let body: Record<string, unknown> | null = null;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/models/embedding' && init?.method === 'PUT') {
        body = JSON.parse(String(init.body));
        return json({ connections: [configured], embedding: { ...embedding, base_url: 'http://10.0.0.7/v1', models: ['BAAI/bge-m3', 'ibm/granite-embedding-278m-multilingual'], configured: true, api_key_set: true, saved: true } });
      }
      return json({ connections: [configured], embedding });
    }));
    render(<ModelWorkspace />);
    await user.click(await screen.findByRole('tab', { name: /임베딩 모델/ }));
    const card = screen.getByRole('region', { name: '임베딩 게이트웨이' });
    await user.click(within(card).getByRole('button', { name: '연결 설정' }));
    const dialog = screen.getByRole('dialog', { name: '임베딩 연결 설정' });
    await user.type(within(dialog).getByRole('textbox', { name: 'Base URL' }), 'http://10.0.0.7/v1');
    const add = within(dialog).getByRole('textbox', { name: '추가할 모델 ID' });
    await user.type(add, 'BAAI/bge-m3{Enter}ibm/granite-embedding-278m-multilingual{Enter}');
    await user.type(within(dialog).getByLabelText('API 키'), 'sk-local');
    await user.click(within(dialog).getByRole('button', { name: '저장' }));
    expect(body).toEqual({ label: '임베딩 게이트웨이', base_url: 'http://10.0.0.7/v1', models: ['BAAI/bge-m3', 'ibm/granite-embedding-278m-multilingual'], api_key: 'sk-local' });
    const saved = await screen.findByRole('region', { name: '임베딩 게이트웨이' });
    expect(within(saved).getByRole('combobox', { name: '확인할 임베딩 모델' })).toHaveProperty('value', 'BAAI/bge-m3');
    expect(within(saved).queryByText('sk-local')).toBeNull();
    expect(within(saved).getByRole('button', { name: '임베딩 확인' })).toBeTruthy();
  });
});
