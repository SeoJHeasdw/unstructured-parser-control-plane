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

describe('OCR 모델 연결', () => {
  const defaults = { mode: 'region', text_prompt: 'OCR:', table_prompt: 'Table Recognition:', page_prompt: 'document parsing.' };
  const ocr = { key: 'ocr', label: 'OCR 모델', base_url: 'http://127.0.0.1:8090/v1', model_id: 'demo-ocr', api_key_set: true, configured: true,
    mode: 'region', text_prompt: 'OCR:', table_prompt: 'Table Recognition:', page_prompt: 'document parsing.', saved: false, defaults };
  type Call = { url: string; method: string; body: Record<string, unknown> | null };
  function serveOcr(respond: (call: Call) => Response | undefined) {
    const calls: Call[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
      calls.push(call);
      return respond(call) ?? json({ connections: [configured], embedding: null, ocr });
    }));
    return calls;
  }
  async function openOcrTab() {
    const user = userEvent.setup();
    render(<ModelWorkspace />);
    await user.click(await screen.findByRole('tab', { name: /OCR 모델/ }));
    return { user, card: screen.getByRole('region', { name: 'OCR 모델' }) };
  }

  it('카드에 방식·지시문과 키 설정 여부만 보이고, 확인은 누를 때만 시험 그림을 읽힌다', async () => {
    const calls = serveOcr(call => call.url === '/api/models/ocr/test' ? json({ ok: true, status: 200, latency_ms: 812, model: 'demo-ocr', reply: 'OCR TEST 12.5 mg/mL' }) : undefined);
    const { user, card } = await openOcrTab();
    expect(within(card).getByText('demo-ocr')).toBeTruthy();
    expect(within(card).getByText('영역 방식')).toBeTruthy();
    expect(within(card).getByText('Table Recognition:')).toBeTruthy();
    expect(within(card).getByText('설정됨 (표시하지 않음)')).toBeTruthy();
    expect(within(card).getByText(/라이브러리 OCR\(EasyOCR 등\)은 쓰지 않습니다/)).toBeTruthy();
    expect(within(card).getByText('확인 전')).toBeTruthy();
    expect(calls.some(call => call.url.endsWith('/test'))).toBe(false);
    await user.click(within(card).getByRole('button', { name: 'OCR 확인' }));
    expect(await within(card).findByText('812 ms')).toBeTruthy();
    expect(within(card).getByText(/OCR TEST 12\.5 mg\/mL/)).toBeTruthy();
    expect(calls.find(call => call.url === '/api/models/ocr/test')).toEqual({ url: '/api/models/ocr/test', method: 'POST', body: null });
  });

  it('편집 팝업에서 쪽 방식과 지시문을 고르고 저장 전에 확인한 뒤 저장한다', async () => {
    const saved = { ...ocr, label: '사내 OCR', mode: 'page', page_prompt: '<image>\nFree OCR.', saved: true };
    const calls = serveOcr(call => {
      if (call.url === '/api/models/draft/test') return json({ ok: false, status: 200, latency_ms: 40, model: 'demo-ocr', reply: 'hello', error: '응답은 왔지만 시험 그림의 글자를 읽지 못했습니다.' });
      if (call.url === '/api/models/ocr' && call.method === 'PUT') return json({ connections: [configured], embedding: null, ocr: saved });
      return undefined;
    });
    const { user, card } = await openOcrTab();
    await user.click(within(card).getByRole('button', { name: '설정 편집' }));
    const dialog = screen.getByRole('dialog', { name: 'OCR 모델 연결 설정' });
    expect(within(dialog).queryByRole('button', { name: /게이트웨이 모델 목록/ })).toBeNull();
    expect(within(dialog).getByRole('radio', { name: /영역 방식/ })).toHaveProperty('checked', true);
    expect(within(dialog).getByRole('textbox', { name: '글자 지시문' }).getAttribute('placeholder')).toBe('OCR:');
    await user.click(within(dialog).getByRole('radio', { name: /쪽 방식\(쪽 전체를 한 번 호출 · Schift·Unlimited-OCR 등\)/ }));
    expect(within(dialog).queryByRole('textbox', { name: '글자 지시문' })).toBeNull();
    const pagePrompt = within(dialog).getByRole('textbox', { name: '쪽 지시문' });
    expect(pagePrompt).toHaveProperty('value', '');
    expect(pagePrompt.getAttribute('placeholder')).toBe('document parsing.');
    await user.clear(within(dialog).getByRole('textbox', { name: '이름' })); await user.type(within(dialog).getByRole('textbox', { name: '이름' }), '사내 OCR');
    await user.click(pagePrompt); await user.paste('<image> Free OCR.');
    await user.click(within(dialog).getByRole('button', { name: '저장 전 확인' }));
    expect(await within(dialog).findByText('응답은 왔지만 확인 기준을 통과하지 못했습니다. 모델과 설정을 확인하세요.')).toBeTruthy();
    expect(within(dialog).getByText('모델 응답: hello')).toBeTruthy();
    const draft = calls.find(call => call.url === '/api/models/draft/test')!.body;
    expect(draft).toMatchObject({ kind: 'ocr', base_url: ocr.base_url, model_id: 'demo-ocr', mode: 'page', text_prompt: '', table_prompt: '' });
    expect(draft).not.toHaveProperty('api_key');
    await user.click(within(dialog).getByRole('button', { name: '저장' }));
    const put = calls.find(call => call.method === 'PUT')!;
    expect(put.url).toBe('/api/models/ocr');
    expect(put.body).toEqual({ label: '사내 OCR', base_url: ocr.base_url, model_id: 'demo-ocr', mode: 'page', text_prompt: '', table_prompt: '', page_prompt: put.body!.page_prompt });
    expect(String(put.body!.page_prompt)).toContain('Free OCR.');
    const updated = await screen.findByRole('region', { name: '사내 OCR' });
    expect(within(updated).getByText('쪽 방식')).toBeTruthy();
    expect(within(updated).getByText('화면에서 저장')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('새 키는 보내기만 하고 화면에 다시 보이지 않으며, 저장값을 지우면 .env 값으로 돌아간다', async () => {
    const saved = { ...ocr, saved: true };
    let current: Record<string, unknown> = saved;
    const calls = serveOcr(call => {
      if (call.url === '/api/models/ocr' && call.method === 'PUT') return json({ connections: [configured], embedding: null, ocr: current });
      if (call.url === '/api/models/ocr/saved' && call.method === 'DELETE') { current = { ...ocr, base_url: 'http://env-host/v1', saved: false }; return json({ connections: [configured], embedding: null, ocr: current }); }
      return json({ connections: [configured], embedding: null, ocr: current });
    });
    const { user, card } = await openOcrTab();
    await user.click(within(card).getByRole('button', { name: '설정 편집' }));
    let dialog = screen.getByRole('dialog', { name: 'OCR 모델 연결 설정' });
    expect(within(dialog).getByLabelText('API 키').getAttribute('placeholder')).toContain('저장된 키 유지');
    await user.type(within(dialog).getByLabelText('API 키'), 'sk-ocr-secret');
    await user.click(within(dialog).getByRole('button', { name: '저장' }));
    expect(calls.find(call => call.method === 'PUT')!.body).toMatchObject({ api_key: 'sk-ocr-secret', mode: 'region' });
    const after = await screen.findByRole('region', { name: 'OCR 모델' });
    expect(within(after).queryByText(/sk-ocr-secret/)).toBeNull();
    await user.click(within(after).getByRole('button', { name: '설정 편집' }));
    dialog = screen.getByRole('dialog', { name: 'OCR 모델 연결 설정' });
    await user.click(within(dialog).getByRole('button', { name: '.env 값으로 되돌리기' }));
    expect(calls.some(call => call.url === '/api/models/ocr/saved' && call.method === 'DELETE')).toBe(true);
    expect(await screen.findByText('화면에서 저장한 값을 지우고 .env 값으로 되돌렸습니다.')).toBeTruthy();
    const reverted = screen.getByRole('region', { name: 'OCR 모델' });
    expect(within(reverted).getByText('http://env-host/v1')).toBeTruthy();
    expect(within(reverted).getByText('.env')).toBeTruthy();
  });

  it('예전 서버처럼 OCR 정보가 없으면 탭에서 그 사실만 알린다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ connections: [configured], embedding: null })));
    const user = userEvent.setup();
    render(<ModelWorkspace />);
    await user.click(await screen.findByRole('tab', { name: /OCR 모델/ }));
    expect(screen.getByText(/OCR 모델 연결 정보를 읽지 못했습니다/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'OCR 확인' })).toBeNull();
  });
});
