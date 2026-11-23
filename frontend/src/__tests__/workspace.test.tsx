import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { installFlowDomMocks } from './flowTestEnv';
import lineage from './fixtures/lineage.json';

const fixture = {
  asOf:'2026-11-12 09:42',
  documents:[
    {id:'D-1',name:'보고서.pdf',source:'예시 문서함',format:'PDF',size:'1 MB',updated:'오늘',status:'처리 완료',stage:'인덱스 반영',parser:'Docling',ocr:false,note:'완료',pages:2,refs:1,text:'예시 원문\n숫자 123',compare:'예시 원문\n숫자 124'},
    {id:'D-2',name:'기록.heic',source:'예시 문서함',format:'HEIC',size:'2 MB',updated:'오늘',status:'형식 확인 필요',stage:'형식 확인',parser:'미지정',ocr:false,note:'경로 확인 필요',pages:0,refs:0,text:'파싱 없음',compare:'파싱 없음'},
    {id:'D-3',name:'대장.xlsx',source:'예시 문서함',format:'XLSX',size:'3 MB',updated:'어제',status:'처리 실패',stage:'파싱',parser:'미지정',ocr:false,note:'실패',pages:0,refs:1,text:'SOP-QC-0040',compare:'SOP-QC-0040'}
  ],
  relations:[{id:'R-1',sourceId:'D-3',source:'대장.xlsx',location:'Sheet1 · B12',target:'SOP-QC-0040',targetId:null,evidence:'SOP-QC-0040 참조',method:'문서번호 패턴',status:'대상 미발견'}],activity:[]
};

beforeEach(()=>{ history.replaceState(null, "", "/"); installFlowDomMocks(); const store=new Map<string,string>(); vi.stubGlobal('localStorage',{getItem:(key:string)=>store.get(key) ?? null,setItem:(key:string,value:string)=>store.set(key,String(value)),removeItem:(key:string)=>store.delete(key),clear:()=>store.clear(),key:(index:number)=>[...store.keys()][index] ?? null,get length(){return store.size}});vi.stubGlobal('fetch',vi.fn(async (url:RequestInfo | URL)=>({ok:true,json:async()=>String(url).startsWith('/api/lineage')?{...JSON.parse(JSON.stringify(lineage)),source:String(url).includes('source=example')?'example':'live'}:String(url).includes('/api/live/documents')?{documents:[]}:JSON.parse(JSON.stringify(fixture))}))); });
afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe('문서 운영 Mock 콘솔',()=>{
  it('화면 찾기를 키보드로 열고 이동하며 Escape로 닫으면 실행 버튼에 초점을 돌린다', async () => {
    const user = userEvent.setup();
    render(<App />);
    const trigger = screen.getByRole('button', { name: '화면 찾기' });
    await user.click(trigger);
    const search = screen.getByRole('combobox', { name: '화면 검색' });
    expect(document.activeElement).toBe(search);
    await user.type(search, '없는화면');
    expect(screen.getByText(/일치하는 화면이 없습니다/)).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(document.activeElement).toBe(trigger);
    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox', { name: '화면 검색' }), '파일 업로드');
    await user.keyboard('{Enter}');
    const heading = screen.getByRole('heading', { level: 1, name: '문서함' });
    expect(document.activeElement).toBe(heading);
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  });

  it('실제 문서함에서 분석 도구로 이동한 뒤 기존 명칭으로 찾을 수 있다', async () => {
    const user = userEvent.setup();
    render(<App/>);
    expect(screen.getByRole('heading',{name:'문서함'})).toBeTruthy();
    expect(screen.getByRole('button',{name:'파일 추가'})).toBeTruthy();
    await user.click(screen.getByRole('link',{name:'분석 도구'}));
    expect(screen.getByRole('link',{name:/청킹 비교/}).getAttribute('href')).toContain('view=chunking');
    await user.click(screen.getByRole('button',{name:'화면 찾기'}));
    await user.type(screen.getByRole('combobox',{name:'화면 검색'}),'청킹 벤치');
    expect(screen.getByRole('option').textContent).toContain('청킹 비교');
  });

  it('예시 처리 현황에서 예외 목록과 검수를 열고 예시 출처를 유지한다', async () => {
    const user = userEvent.setup();
    render(<App/>);
    await user.click(screen.getByRole('link',{name:'예시 둘러보기'}));
    await user.click(await screen.findByRole('button',{name:/확인 필요 2건/}));
    expect(screen.getByRole('heading',{name:'예시 문서'})).toBeTruthy();
    expect(screen.queryByText('보고서.pdf')).toBeNull();
    await user.click(screen.getAllByRole('button',{name:/기록\.heic/})[0]);
    await user.click(screen.getByRole('button',{name:/파싱 결과 비교/}));
    expect(screen.getByLabelText('비교 문서')).toHaveProperty('value','D-2');
    expect(screen.getByText('예시 데이터')).toBeTruthy();
    expect(location.search).toContain('doc=D-2');
  });

  it('기존 시뮬레이터 주소를 열고 브라우저 이력으로 복귀한다', async () => {
    history.replaceState(null, '', '?view=pipeline');
    const user=userEvent.setup(); render(<App/>);
    expect(await screen.findByRole('heading',{name:'전체 처리 흐름'})).toBeTruthy();
    await user.click(screen.getByRole('link',{name:'문서함'}));
    history.back();
    expect(await screen.findByRole('heading',{name:'전체 처리 흐름'})).toBeTruthy();
  });
});
