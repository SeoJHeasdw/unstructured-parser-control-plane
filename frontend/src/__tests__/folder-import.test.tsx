import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LiveWorkspace from '../LiveWorkspace';

const doc = (id: string, name: string, seq: number, status = 'uploaded') => ({
  id, name, format: name.split('.').pop()!.toUpperCase(), size_bytes: 20, status, seq,
  created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z', parser: null, error: null,
});
const roots = { roots: [{ index: 0, path: 'C:\\vswrk\\samples', name: 'samples' }], notes: [], default: true, setting: 'DOCOPS_AGENT_ROOTS', max_bytes: 100 * 1024 * 1024 };
const file = (path: string, state = 'ready', existing: unknown[] = []) => ({
  path, name: path.split('/').pop(), format: path.split('.').pop()!.toUpperCase(), size_bytes: 2048, modified_at: '2026-11-25T00:00:00Z', state, existing,
});
const rootListing = { root: 0, path: '', parent: null, recursive: false, truncated: false,
  folders: [{ name: 'generated', path: 'generated' }], files: [file('안내.md'), file('묶음.zip', 'no_parser'), file('빈.txt', 'empty')] };
const innerListing = { root: 0, path: 'generated', parent: '', recursive: false, truncated: false, folders: [],
  files: [file('generated/절차서.docx'), file('generated/기록.csv', 'ready', [{ id: 'old', seq: 3, status: 'completed' }])] };

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
beforeEach(() => { history.replaceState(null, '', '/'); });

describe('허용 폴더에서 가져오기', () => {
  it('브라우저로 파일을 보내지 않고 경로만 보내며, 파싱은 사용자가 누를 때만 접수한다', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.split('?')[0] === '/api/live/documents') return json({ documents: [] });
      if (path === '/api/live/import/roots') return json(roots);
      if (path.startsWith('/api/live/import/entries')) {
        const params = new URL(path, 'http://x').searchParams;
        return json(params.get('path') === 'generated' ? innerListing : rootListing);
      }
      if (path === '/api/live/import' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        expect(body).toEqual({ root: 0, paths: ['generated/절차서.docx', 'generated/기록.csv'] });
        return json({ items: [
          { path: 'generated/절차서.docx', outcome: 'imported', document: doc('new', '절차서.docx', 4) },
          { path: 'generated/기록.csv', outcome: 'reused', document: doc('old', '기록.csv', 3, 'completed') },
        ] });
      }
      if (path === '/api/live/documents/new/process') return json({ ...doc('new', '절차서.docx', 4), status: 'processing' }, 202);
      throw new Error(`예상하지 못한 호출 ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<LiveWorkspace />);
    await user.click(await screen.findByRole('button', { name: '폴더에서 가져오기' }));
    const dialog = await screen.findByRole('dialog', { name: '허용 폴더에서 가져오기' });
    expect(within(dialog).getByText('C:\\vswrk\\samples')).toBeTruthy();
    expect(within(dialog).getByText(/기본값: 프로젝트 samples/)).toBeTruthy();
    // 빈 파일은 고를 수 없고, 파서 없는 형식은 표시만 한다.
    expect((await within(dialog).findByLabelText('빈.txt 선택') as HTMLInputElement).disabled).toBe(true);
    expect(within(dialog).getByText('파서 없음')).toBeTruthy();

    await user.click(within(dialog).getByRole('button', { name: 'generated 폴더 열기' }));
    await within(dialog).findByLabelText('generated/절차서.docx 선택');
    expect(within(dialog).getByText('문서함에 있음')).toBeTruthy();
    // '모두 선택'은 문서함에 없는 파일만 고른다.
    await user.click(within(dialog).getByLabelText(/모두 선택/));
    expect((within(dialog).getByLabelText('generated/절차서.docx 선택') as HTMLInputElement).checked).toBe(true);
    expect((within(dialog).getByLabelText('generated/기록.csv 선택') as HTMLInputElement).checked).toBe(false);
    await user.click(within(dialog).getByLabelText('generated/기록.csv 선택'));
    await user.click(within(dialog).getByRole('button', { name: '2개 가져오기' }));

    const result = await screen.findByRole('dialog', { name: '가져오기 결과' });
    expect(within(result).getByText('같은 원본이 이미 있어 그 문서를 씁니다 · generated/기록.csv')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/process'))).toBe(false);
    expect(screen.getByText(/2개 문서를 허용 폴더에서 가져와/)).toBeTruthy();
    // 이미 완료된 문서는 다시 파싱하지 않는다.
    await user.click(within(result).getByRole('button', { name: '1개 파싱 실행' }));
    await waitFor(() => expect(screen.getByText(/1개 문서의 파싱을 접수했습니다/)).toBeTruthy());
    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith('/process')).map(([path]) => String(path))).toEqual(['/api/live/documents/new/process']);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('허용 폴더가 없으면 설정 방법을 보여 준다', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.split('?')[0] === '/api/live/documents') return json({ documents: [] });
      if (path === '/api/live/import/roots') return json({ ...roots, roots: [], default: false, notes: ['허용 폴더가 없음: D:\\없음'] });
      throw new Error(path);
    }));
    const user = userEvent.setup();
    render(<LiveWorkspace />);
    await user.click(await screen.findByRole('button', { name: '폴더에서 가져오기' }));
    expect(await screen.findByText('열 수 있는 허용 폴더가 없습니다')).toBeTruthy();
    expect(screen.getByText('허용 폴더가 없음: D:\\없음')).toBeTruthy();
    expect((screen.getByRole('button', { name: '가져오기' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
