import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LiveWorkspace from '../LiveWorkspace';
import App from '../App';

type MockDoc = {
  id:string; name:string; format:string; size_bytes:number; status:'uploaded'|'processing'|'completed'|'failed'|'unsupported';
  created_at:string; updated_at:string; parser:string|null; error:string|null;
};
const uploaded: MockDoc = {
  id:'test-001',name:'예시.txt',format:'TXT',size_bytes:12,status:'uploaded',
  created_at:'2026-11-12T00:00:00Z',updated_at:'2026-11-12T00:00:00Z',parser:null,error:null,
};
const completed: MockDoc = { ...uploaded, status:'completed', updated_at:'2026-11-12T00:00:01Z', parser:'text' };
const url = '/api/live/documents';
const detailUrl = `${url}/${uploaded.id}`;
const resultText = '테스트 문장\n<script>window.shouldNotExecute = true</script>';
function jsonResponse(body:unknown,status=200):Response {
  return {ok:status>=200&&status<300,status,json:async()=>body} as Response;
}

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
beforeEach(()=>{history.replaceState(null, '', '/');vi.stubGlobal('fetch',vi.fn(async()=>{throw new Error('예상하지 못한 네트워크 호출')}))});

describe('실제 문서 로컬 작업 공간',()=>{
  it('실제 문서에서 이전 성공본을 청킹하면 그 문서 ID로만 나누고 뒤로가기로 복귀한다', async () => {
    const sample = {id:'report',name:'예시 보고서',description:'',composition:{},pages:null};
    const staleDoc = {...uploaded, status:'failed' as const, error:'최근 실행 실패'};
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.split('?')[0] === url) return jsonResponse({documents:[staleDoc]});
      if (path === detailUrl) return jsonResponse(staleDoc);
      if (path === detailUrl + '/result') return jsonResponse({id:uploaded.id,markdown:'이전 본문',parser:'python-text',parser_version:'1',is_stale:true,warnings:[]});
      if (path === detailUrl + '/runs') return jsonResponse({runs:[]});
      if (path.endsWith('/retrieval/documents')) return jsonResponse({documents:[{...staleDoc,is_stale:true}]});
      if (path.endsWith('/retrieval/samples')) return jsonResponse({samples:[sample]});
      if (path.endsWith('/retrieval/config')) return jsonResponse({connections:[],specs:[]});
      if (path.endsWith('/retrieval/chunk')) return jsonResponse({source:{name:uploaded.name,is_stale:true,elements:[],composition:{}},results:[]});
      throw new Error(path + ' ' + init?.method);
    });
    vi.stubGlobal('fetch', fetchMock);
    history.replaceState(null, '', '?view=live&doc=' + uploaded.id);
    const user = userEvent.setup();
    render(<App/>);
    await user.click(await screen.findByRole('link', {name:'이전 성공본 청킹'}));
    expect(location.search).toBe('?view=chunking&doc=' + uploaded.id);
    expect(await screen.findByText('이전 처리 결과')).toBeTruthy();
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/retrieval/chunk'))).toBe(true));
    const bodies = fetchMock.mock.calls.filter(([path]) => String(path).endsWith('/retrieval/chunk')).map(([,init]) => JSON.parse(String(init?.body)));
    expect(bodies.every(body => body.source.doc_id === uploaded.id && !body.source.sample)).toBe(true);
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/process'))).toBe(false);
    history.back();
    expect(await screen.findByRole('link', {name:'이전 성공본 청킹'})).toBeTruthy();
  });
  it('앞서 시작한 목록 조회가 늦게 끝나도 방금 저장한 파일을 유지한다', async () => {
    let resolveList!: (response: Response) => void;
    const pendingList = new Promise<Response>(resolve => { resolveList = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.split('?')[0] === url) return init?.method === 'POST' ? jsonResponse(uploaded, 201) : pendingList;
      if (path === detailUrl) return jsonResponse(uploaded);
      return jsonResponse({}, 404);
    }));
    const user = userEvent.setup();
    render(<LiveWorkspace />);
    await user.upload(screen.getByLabelText('로컬에 업로드할 파일 선택'), new File(['테스트'], uploaded.name));
    await screen.findByText(/1개 파일을 이 컴퓨터의 로컬 저장소에 저장했습니다/);
    await act(async () => { resolveList(jsonResponse({ documents: [] })); });
    await user.click(screen.getByRole('button', { name: '문서함으로' }));
    expect(within(document.querySelector('.live-list') as HTMLElement).getByText(uploaded.name)).toBeTruthy();
  });

  it('여러 파일을 저장할 때 메뉴를 왕복해도 각 파일을 한 번씩 끝까지 저장한다', async () => {
    let resolveUpload!: (response: Response) => void;
    const firstUpload = new Promise<Response>(resolve => { resolveUpload = resolve; });
    const second = { ...uploaded, id: 'test-002', name: '다른 문서.txt' };
    let uploadCount = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/data') return jsonResponse({ asOf: '', documents: [], relations: [], activity: [] });
      if (path.split('?')[0] === url) return init?.method === 'POST' ? (++uploadCount === 1 ? firstUpload : jsonResponse(second, 201)) : jsonResponse({ documents: [] });
      if (path === `${url}/${second.id}`) return jsonResponse(second);
      return jsonResponse({}, 404);
    }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('업로드된 문서가 없습니다');
    await user.upload(screen.getByLabelText('로컬에 업로드할 파일 선택'), [new File(['첫 파일'], uploaded.name), new File(['둘째 파일'], second.name)]);
    const nav = within(screen.getByRole('navigation', {name:'업무 메뉴'}));
    await user.click(nav.getByRole('link', { name: '분석 도구' }));
    expect(screen.getByRole('link', { name: '파일 저장 중' })).toBeTruthy();
    await act(async () => { resolveUpload(jsonResponse(uploaded, 201)); });
    await user.click(nav.getByRole('link', { name: '문서함' }));
    expect(await screen.findByText(/2개 파일을 이 컴퓨터의 로컬 저장소에 저장했습니다/)).toBeTruthy();
    expect(uploadCount).toBe(2);
  });

  it('목록을 조회하고 선택한 문서의 상세를 불러오며 자동으로 업로드하거나 파싱하지 않는다',async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[uploaded]});
      if(path===detailUrl&&method==='GET')return jsonResponse(uploaded);
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    expect(await within(list).findByText(uploaded.name)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path]) => String(path).split('?')[0] === url)).toBe(true);
    expect(fetchMock.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    await waitFor(()=>expect(fetchMock.mock.calls.some(([path,init])=>String(path)===detailUrl&&(!init?.method||init.method==='GET'))).toBe(true));
    expect(screen.getByText('test-001')).toBeTruthy();
    expect(screen.getByRole('button',{name:'파싱 실행'})).toBeTruthy();
    expect(fetchMock.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  });
  it('검색과 상태 필터를 유지하고, 이력 탭을 열 때 조회한 뒤 키보드로 원래 행에 돌아온다', async () => {
    const waiting = { ...uploaded, id: 'pending', name: '다른예시.txt' };
    const historyUrl = detailUrl + '/history';
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      switch (String(input).split('?')[0]) {
        case url: return jsonResponse({ documents: [waiting, completed] });
        case detailUrl: return jsonResponse(completed);
        case detailUrl + '/result': return jsonResponse({ id: completed.id, markdown: resultText, parser: 'text', parser_version: '1', warnings: [], is_stale: false });
        case historyUrl: return jsonResponse({ history: [{ created_at: completed.updated_at, status: 'completed', message: '텍스트 추출 완료' }] });
        default: throw new Error('예상하지 못한 조회');
      }
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<LiveWorkspace />);
    await screen.findByText(waiting.name);
    await user.type(screen.getByRole('textbox', { name: '실제 문서 검색' }), '예시');
    await user.selectOptions(screen.getByRole('combobox', { name: '처리 상태 필터' }), 'completed');
    expect(screen.queryByText(waiting.name)).toBeNull();
    const row = screen.getByRole('link', { name: /예시\.txt/ });
    row.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('heading', { name: completed.name })).toBe(document.activeElement);
    expect(fetchMock.mock.calls.some(([path]) => path === historyUrl)).toBe(false);
    await user.click(screen.getByRole('tab', { name: '추출 결과' }));
    await user.keyboard('{ArrowRight}');
    expect(await screen.findByText('텍스트 추출 완료')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '문서함으로' }));
    expect(screen.getByRole('link', { name: /예시\.txt/ })).toBe(document.activeElement);
    expect(screen.getByRole('textbox', { name: '실제 문서 검색' })).toHaveProperty('value', '예시');
    expect(screen.getByRole('combobox', { name: '처리 상태 필터' })).toHaveProperty('value', 'completed');
  });
  it('여러 파일 중 실패한 파일만 원래 이름으로 다시 저장한다', async () => {
    const names: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (path:string, init?:RequestInit) => {
      if (path.split('?')[0] === url && init?.method === 'POST') {
        const file = (init.body as FormData).get('file') as File;
        names.push(file.name);
        if (file.name === '재시도.txt' && names.length === 2) return jsonResponse({detail:'일시 오류'}, 503);
        return jsonResponse({...uploaded, id:file.name, name:file.name}, 201);
      }
      if (path.split('?')[0] === url) return jsonResponse({documents:[]});
      return jsonResponse({...uploaded,id:'재시도.txt',name:'재시도.txt'});
    }));
    const user = userEvent.setup(); render(<App/>);
    await screen.findByText('업로드된 문서가 없습니다');
    await user.upload(screen.getByLabelText('로컬에 업로드할 파일 선택'), ['완료.txt','재시도.txt'].map(name => new File([name], name)));
    expect((await screen.findByRole('alert')).textContent).toContain('재시도.txt');
    expect(screen.getByRole('heading', {level:1}).textContent).toBe('문서함');
    await user.click(screen.getByRole('button', {name:'실패한 파일만 다시 저장'}));
    await waitFor(() => expect(screen.queryByText('1개 파일 저장 실패')).toBeNull());
    expect(names).toEqual(['완료.txt','재시도.txt','재시도.txt']);
  });

  it('브라우저 뒤로가면 검색어·상태·선택한 행의 초점을 복원한다', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path:string) => jsonResponse(path.split('?')[0] === url ? {documents:[uploaded]} : uploaded)));
    const user = userEvent.setup(); render(<App/>);
    await screen.findByRole('link', {name:/예시\.txt/});
    await user.type(screen.getByRole('textbox',{name:'실제 문서 검색'}), '예시');
    await user.selectOptions(screen.getByRole('combobox',{name:'처리 상태 필터'}),'uploaded');
    await user.click(screen.getByRole('link', {name:/예시\.txt/}));
    expect(location.search).toContain('doc=test-001');
    history.back();
    const row = await screen.findByRole('link', {name:/예시\.txt/});
    expect(screen.getByRole('textbox',{name:'실제 문서 검색'})).toHaveProperty('value','예시');
    expect(screen.getByRole('combobox',{name:'처리 상태 필터'})).toHaveProperty('value','uploaded');
    expect(document.activeElement).toBe(row);
  });

  it('잘못된 문서 주소에는 찾을 수 없음과 문서함 복귀를 제공한다', async () => {
    history.replaceState(null, '', '?view=live&doc=missing&tab=history');
    vi.stubGlobal('fetch', vi.fn(async (path:string) => path.split('?')[0] === url ? jsonResponse({documents:[]}) : jsonResponse({detail:'문서 없음'},404)));
    const user = userEvent.setup(); render(<App/>);
    expect(await screen.findByRole('heading',{name:'문서를 찾을 수 없습니다'})).toBeTruthy();
    await user.click(screen.getByRole('button', {name:'문서함으로'}));
    expect(screen.getByRole('heading',{name:'문서함'})).toBeTruthy();
  });

  it('사용자가 고른 파일을 multipart POST로 저장하고, 업로드만으로 파싱을 실행하지 않는다',async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[]});
      if(path.split('?')[0]===url&&method==='POST')return jsonResponse(uploaded,201);
      if(path===detailUrl&&method==='GET')return jsonResponse(uploaded);
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    await screen.findByText('업로드된 문서가 없습니다');
    expect(fetchMock.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
    const input=screen.getByLabelText('로컬에 업로드할 파일 선택') as HTMLInputElement;
    const file=new File(['테스트 내용'],uploaded.name,{type:'text/plain'});
    await user.upload(input,file);
    await waitFor(()=>expect(fetchMock.mock.calls.some(([path,init])=>String(path).split('?')[0]===url&&init?.method==='POST')).toBe(true));
    const uploadCall=fetchMock.mock.calls.find(([path,init])=>String(path).split('?')[0]===url&&init?.method==='POST');
    expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData);
    const part=(uploadCall?.[1]?.body as FormData).get('file') as File;
    expect(part).toBeInstanceOf(File);expect(part.name).toBe(uploaded.name);expect(part.size).toBe(file.size);
    expect(await screen.findByText(/1개 파일을 이 컴퓨터의 로컬 저장소에 저장했습니다/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path])=>String(path).endsWith('/process'))).toBe(false);
  });
  it('파싱 버튼을 눌렀을 때만 POST하고 결과를 HTML 실행 없이 텍스트로 보여준다',async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[uploaded]});
      if(path===detailUrl&&method==='GET')return jsonResponse(uploaded);
      if(path===`${detailUrl}/process`&&method==='POST')return jsonResponse(completed);
      if(path===`${detailUrl}/result`&&method==='GET')return jsonResponse({id:uploaded.id,markdown:resultText,parser:'text',parser_version:'1.0',is_stale:false,warnings:[]});
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(uploaded.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    expect(fetchMock.mock.calls.some(([path])=>String(path).endsWith('/process'))).toBe(false);
    await user.click(screen.getByRole('button',{name:'파싱 실행'}));
    await waitFor(()=>expect(fetchMock.mock.calls.some(([path,init])=>String(path)===`${detailUrl}/process`&&init?.method==='POST')).toBe(true));
    const result=await screen.findByText(content=>content.includes('<script>window.shouldNotExecute = true</script>'));
    expect(result.closest('.md-view')).not.toBeNull();
    expect(document.querySelector('.md-view script')).toBeNull();
    await user.click(screen.getByRole('radio',{name:'Markdown 원문'}));
    const raw=document.querySelector('.live-result-content.is-raw') as HTMLElement;
    expect(raw.textContent).toBe(resultText);
    expect(raw.querySelector('script')).toBeNull();
    expect(fetchMock.mock.calls.some(([path])=>String(path)===`${detailUrl}/result`)).toBe(true);
  });
  it('파싱 요청이 실패하면 서버가 반환한 오류를 표시하고 결과 조회를 하지 않는다',async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[uploaded]});
      if(path===detailUrl&&method==='GET')return jsonResponse(uploaded);
      if(path===`${detailUrl}/process`&&method==='POST')return jsonResponse({detail:'파서 모델을 찾을 수 없습니다.'},500);
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(uploaded.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    await user.click(screen.getByRole('button',{name:'파싱 실행'}));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent','파서 모델을 찾을 수 없습니다.×');
    expect(fetchMock.mock.calls.some(([path])=>String(path)===`${detailUrl}/result`)).toBe(false);
  });
  it('목록 조회 오류와 다시 시도 경로를 보여준다',async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      if(String(input).split('?')[0]===url&&(!init?.method||init.method==='GET'))return jsonResponse({detail:'로컬 저장소를 읽을 수 없습니다.'},503);
      throw new Error('예상하지 못한 호출');
    });
    vi.stubGlobal('fetch',fetchMock);render(<LiveWorkspace/>);
    expect(await screen.findByText(/로컬 저장소를 읽을 수 없습니다/)).toBeTruthy();
    expect(screen.getByRole('button',{name:'다시 시도'})).toBeTruthy();
  });
});


describe('Mock 데이터와 실제 파일 작업의 독립성',()=>{
  it('Mock 조회가 실패해도 실제 문서를 조회하고, 재시도 후 열린 탭을 유지한다',async()=>{
    let mockAttempts=0;
    const mockDoc={id:'M-1',name:'가상.pdf',source:'예시 원천',format:'PDF',size:'1 KB',updated:'오늘',status:'처리 완료',stage:'인덱스 반영',parser:'Docling',ocr:false,note:'예시',pages:1,refs:0,text:'예시',compare:'예시'};
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path==='/api/data'&&method==='GET'){
        mockAttempts++;
        return mockAttempts===1?jsonResponse({detail:'Mock 조회 실패'},503):jsonResponse({asOf:'예시 시각',documents:[mockDoc],relations:[],activity:[]});
      }
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[uploaded]});
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<App/>);
    await screen.findByText(uploaded.name);
    expect(mockAttempts).toBe(0);
    const nav = within(screen.getByRole('navigation', {name:'업무 메뉴'}));
    await user.click(nav.getByRole('link', {name:'예시 둘러보기'}));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('예시 데이터를 불러오지 못했습니다'));
    await user.click(screen.getByRole('button', {name:'다시 시도'}));
    await screen.findByRole('heading', {name:'확인이 필요한 문서'});
    await user.click(nav.getByRole('link', {name:'문서함'}));
    expect(screen.getByText(uploaded.name)).toBeTruthy();
    expect(mockAttempts).toBe(2);
    expect(fetchMock.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  });
  it('Mock 응답을 기다리는 동안에도 실제 파일 처리 화면을 사용할 수 있다',async()=>{
    const neverResolved=new Promise<Response>(()=>{});
    const fetchMock=vi.fn((input:RequestInfo|URL):Promise<Response>=>{
      if(String(input)==='/api/data')return neverResolved;
      if(String(input).split('?')[0]===url)return Promise.resolve(jsonResponse({documents:[uploaded]}));
      return Promise.reject(new Error('예상하지 못한 호출'));
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<App/>);
    const nav = within(screen.getByRole('navigation', {name:'업무 메뉴'}));
    await user.click(nav.getByRole('link',{name:'예시 둘러보기'}));
    await screen.findByText('예시 데이터를 불러오는 중입니다.');
    await user.click(nav.getByRole('link',{name:'문서함'}));
    expect(await within(document.querySelector('.live-list') as HTMLElement).findByText(uploaded.name)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path])=>String(path).split('?')[0]===url)).toBe(true);
  });
});

describe('비동기 처리 알림',()=>{
  it.each([
    ['completed','파싱이 완료되었습니다.'],
    ['failed','파싱에 실패했습니다.'],
    ['unsupported','지원하지 않는 형식입니다.'],
  ] as const)('처리가 %s에 도달하면 시작 알림을 실제 결과로 교체한다',async(status,expected)=>{
    let started=false;
    const running:MockDoc={...uploaded,status:'processing',updated_at:'2026-11-12T00:00:01Z'};
    const final:MockDoc={...uploaded,status,updated_at:'2026-11-12T00:00:02Z',parser:status==='completed'?'text':null,error:status==='failed'?'파싱 오류':null};
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[started?final:uploaded]});
      if(path===detailUrl&&method==='GET')return jsonResponse(uploaded);
      if(path===`${detailUrl}/process`&&method==='POST'){started=true;return jsonResponse(running)}
      if(path===`${detailUrl}/result`&&method==='GET')return status==='completed'?jsonResponse({id:uploaded.id,markdown:'완료 결과',parser:'text',parser_version:'1.0',is_stale:false,warnings:[]}):jsonResponse({detail:'완료된 파싱 결과가 없습니다.'},409);
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(uploaded.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    await user.click(screen.getByRole('button',{name:'파싱 실행'}));
    expect(await screen.findByText('파싱 작업이 접수되었습니다. 대기 또는 처리 상태를 자동으로 확인합니다.')).toBeTruthy();
    expect(await screen.findByText(new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')),{}, {timeout:4000})).toBeTruthy();
    expect(screen.queryByText('파싱 작업이 접수되었습니다. 대기 또는 처리 상태를 자동으로 확인합니다.')).toBeNull();
  },5000);
});

describe('마지막 성공 결과 및 파싱 경고',()=>{
  it.each(['processing','failed'] as const)('%s 상태에서도 이전 성공 결과와 경고를 표시한다',async(status)=>{
    const doc:MockDoc={...uploaded,status,updated_at:'2026-11-12T00:00:02Z',error:status==='failed'?'새 작업 실패':null};
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[doc]});
      if(path===detailUrl&&method==='GET')return jsonResponse(doc);
      if(path===`${detailUrl}/result`&&method==='GET')return jsonResponse({id:doc.id,markdown:'이전 파싱 본문',parser:'text',parser_version:'1.0',is_stale:true,warnings:['이전 결과의 경고']});
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(uploaded.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    expect(await screen.findByText('이전 성공 결과 · 현재 작업 결과 아님')).toBeTruthy();
    expect(screen.getByText('이전 파싱 본문')).toBeTruthy();
    expect(screen.getByText('이전 결과의 경고')).toBeTruthy();
  });
  it('최신 성공 결과에 파싱 경고가 있으면 눈에 띄게 표시한다',async()=>{
    const pdf:MockDoc={...completed,name:'스캔.pdf',format:'PDF'};
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[pdf]});
      if(path===detailUrl&&method==='GET')return jsonResponse(pdf);
      if(path===`${detailUrl}/result`&&method==='GET')return jsonResponse({id:pdf.id,markdown:'추출된 텍스트',parser:'Docling',parser_version:'1',is_stale:false,warnings:['스캔 페이지가 OCR 없이 누락되었을 수 있습니다.']});
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(pdf.name);
    await user.click(within(list).getByRole('link',{name:/스캔\.pdf/}));
    expect(await screen.findByText('스캔 페이지가 OCR 없이 누락되었을 수 있습니다.')).toBeTruthy();
    expect(screen.getByText('파싱 경고').closest('[role="alert"]')).toBeTruthy();
    expect(screen.queryByText('이전 성공 결과 · 현재 작업 결과 아님')).toBeNull();
  });
  it('이전 성공 결과가 없어 409를 받으면 빈 상태로, 다른 서버 오류는 그대로 표시한다',async()=>{
    const doc:MockDoc={...uploaded,status:'failed'};
    let unavailable=false;
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[doc]});
      if(path===detailUrl&&method==='GET')return jsonResponse(doc);
      if(path===`${detailUrl}/result`&&method==='GET')return unavailable?jsonResponse({detail:'결과 저장소가 응답하지 않습니다.'},503):jsonResponse({detail:'완료된 파싱 결과가 없습니다.'},409);
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(uploaded.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    expect(await screen.findByText('이전에 성공한 파싱 결과가 없습니다.')).toBeTruthy();
    expect(document.querySelector('.live-result-error')).toBeNull();
    unavailable=true;
    // A fresh visit triggers a new result request for the same failed document.
    cleanup();render(<LiveWorkspace/>);
    const refreshedList=document.querySelector('.live-list') as HTMLElement;
    await within(refreshedList).findByText(uploaded.name);
    await user.click(within(refreshedList).getByRole('link',{name:/예시\.txt/}));
    expect(await screen.findByText(/결과 저장소가 응답하지 않습니다/)).toBeTruthy();
    expect(document.querySelector('.live-result-error')).toBeTruthy();
  });
  it('결과 파일 손실에 대한 409는 빈 결과로 숨기지 않고 오류를 표시한다',async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL)=>{
      const path=String(input);
      if(path.split('?')[0]===url)return jsonResponse({documents:[completed]});
      if(path===detailUrl)return jsonResponse(completed);
      if(path===`${detailUrl}/result`)return jsonResponse({detail:'저장된 결과 파일을 찾을 수 없습니다.'},409);
      throw new Error(`예상하지 못한 호출 ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(completed.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    expect(await screen.findByText('저장된 결과 파일을 찾을 수 없습니다.')).toBeTruthy();
    expect(document.querySelector('.live-result-error')).toBeTruthy();
    expect(screen.queryByText('이전에 성공한 파싱 결과가 없습니다.')).toBeNull();
  });
  it('문서 전환 후 늦게 돌아온 이전 요청이 새 문서 결과를 덮어쓰지 않는다',async()=>{
    const other:MockDoc={...completed,id:'test-002',name:'다른 문서.txt'};
    let resolveOld:(response:Response)=>void=()=>{};
    const oldResult=new Promise<Response>(resolve=>{resolveOld=resolve});
    const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const path=String(input);const method=init?.method||'GET';
      if(path.split('?')[0]===url&&method==='GET')return jsonResponse({documents:[completed,other]});
      if(path===detailUrl&&method==='GET')return jsonResponse(completed);
      if(path===`${url}/${other.id}`&&method==='GET')return jsonResponse(other);
      if(path===`${detailUrl}/result`&&method==='GET')return oldResult;
      if(path===`${url}/${other.id}/result`&&method==='GET')return jsonResponse({id:other.id,markdown:'다른 문서의 현재 결과',parser:'text',parser_version:'1',is_stale:false,warnings:[]});
      throw new Error(`예상하지 못한 호출 ${method} ${path}`);
    });
    vi.stubGlobal('fetch',fetchMock);const user=userEvent.setup();render(<LiveWorkspace/>);
    const list=document.querySelector('.live-list') as HTMLElement;
    await within(list).findByText(completed.name);
    await user.click(within(list).getByRole('link',{name:/예시\.txt/}));
    await waitFor(()=>expect(fetchMock.mock.calls.some(([path])=>String(path)===`${detailUrl}/result`)).toBe(true));
    await user.click(screen.getByRole('button',{name:'문서함으로'}));
    expect(document.activeElement?.textContent).toContain(uploaded.name);
    await user.click(screen.getByRole('link',{name:/다른 문서\.txt/}));
    expect(await screen.findByText('다른 문서의 현재 결과')).toBeTruthy();
    resolveOld(jsonResponse({id:completed.id,markdown:'늦게 도착한 이전 문서 결과',parser:'text',parser_version:'1',is_stale:false,warnings:[]}));
    await new Promise(resolve=>setTimeout(resolve,0));
    expect(screen.queryByText('늦게 도착한 이전 문서 결과')).toBeNull();
    expect(screen.getByText('다른 문서의 현재 결과')).toBeTruthy();
  });
});
