import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { installFlowDomMocks } from './flowTestEnv';

const fixture = {
  asOf:'2026-11-12 09:42',
  documents:[
    {id:'D-1',name:'보고서.pdf',source:'예시 문서함',format:'PDF',size:'1 MB',updated:'오늘',status:'처리 완료',stage:'인덱스 반영',parser:'Docling',ocr:false,note:'완료',pages:2,refs:1,text:'예시 원문\n숫자 123',compare:'예시 원문\n숫자 124'},
    {id:'D-2',name:'기록.heic',source:'예시 문서함',format:'HEIC',size:'2 MB',updated:'오늘',status:'형식 확인 필요',stage:'형식 확인',parser:'미지정',ocr:false,note:'경로 확인 필요',pages:0,refs:0,text:'파싱 없음',compare:'파싱 없음'},
    {id:'D-3',name:'대장.xlsx',source:'예시 문서함',format:'XLSX',size:'3 MB',updated:'어제',status:'처리 실패',stage:'파싱',parser:'미지정',ocr:false,note:'실패',pages:0,refs:1,text:'SOP-QC-0040',compare:'SOP-QC-0040'}
  ],
  relations:[{id:'R-1',sourceId:'D-3',source:'대장.xlsx',location:'Sheet1 · B12',target:'SOP-QC-0040',targetId:null,evidence:'SOP-QC-0040 참조',method:'문서번호 패턴',status:'대상 미발견'}],activity:[]
};

beforeEach(()=>{ installFlowDomMocks(); const store=new Map<string,string>(); vi.stubGlobal('localStorage',{getItem:(key:string)=>store.get(key) ?? null,setItem:(key:string,value:string)=>store.set(key,String(value)),removeItem:(key:string)=>store.delete(key),clear:()=>store.clear(),key:(index:number)=>[...store.keys()][index] ?? null,get length(){return store.size}});vi.stubGlobal('fetch',vi.fn(async (url:RequestInfo | URL)=>({ok:true,json:async()=>String(url).includes('/api/live/documents')?{documents:[]}:JSON.parse(JSON.stringify(fixture))}))); });
afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe('문서 운영 Mock 콘솔',()=>{
  it('대시보드 집계에서 예외 목록과 문서 상세·파싱 비교로 이동한다',async()=>{
    const user=userEvent.setup();render(<App/>);
    await screen.findByRole('heading',{name:'운영 대시보드'});
    await user.click(screen.getByRole('button',{name:/확인 필요\s*2건/}));
    expect(screen.getByRole('heading',{name:'문서 탐색'})).toBeTruthy();
    expect(within(document.querySelector('.doc-list-panel') as HTMLElement).queryByText('보고서.pdf')).toBeNull();
    await user.click(within(document.querySelector('.doc-list-panel') as HTMLElement).getAllByRole('button',{name:/기록\.heic/})[0]);
    expect(screen.getByRole('dialog',{name:'문서 상세'})).toBeTruthy();
    await user.click(screen.getByRole('button',{name:/파싱 결과 비교/}));
    expect(screen.getByRole('heading',{name:'파싱 비교'})).toBeTruthy();
    expect(screen.getByLabelText('비교 문서')).toHaveProperty('value','D-2');
  });
  it('파일 드롭은 메타데이터만 로컬 목록에 추가하고 새 형식의 예시 파이프라인으로 연결한다',async()=>{
    const user=userEvent.setup();render(<App/>);
    await screen.findByRole('heading',{name:'운영 대시보드'});
    await user.click(screen.getByRole('button',{name:'문서 탐색'}));
    const drop=screen.getByText('파일을 여기에 놓거나 파일을 선택하세요').closest('.doc-drop');
    expect(drop).toBeTruthy();
    const file=new File(['개인 내용을 전송하지 않음'],'새로운형식.xyz',{type:'application/octet-stream'});
    fireEvent.drop(drop!,{dataTransfer:{files:[file],dropEffect:'copy'}});
    expect(screen.getByRole('status').textContent).toContain('업로드와 파싱은 실행되지 않았습니다');
    expect(screen.getAllByRole('button',{name:/새로운형식\.xyz/}).length).toBeGreaterThan(0);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    await user.click(document.querySelector('.doc-name-button')!);
    await user.click(screen.getByRole('button',{name:'처리 경로 보기'}));
    expect(await screen.findByText(/형식은 아직 처리 경로가 없어/)).toBeTruthy();
    await user.click(screen.getAllByRole('button',{name:/\.xyz 경로 만들기/})[0]);
    expect(screen.getByRole('heading',{name:'.xyz 처리'})).toBeTruthy();
    expect(screen.getByText(/실제 파서는 등록되지 않습니다/)).toBeTruthy();
    expect(vi.mocked(fetch).mock.calls.every(([, options])=>!options?.method || options.method==='GET')).toBe(true);
  });
  it('대시보드 위젯을 이동·숨김·복원하고 파이프라인을 형식별로 전환한다',async()=>{
    const user=userEvent.setup();render(<App/>);
    await screen.findByRole('heading',{name:'운영 대시보드'});
    await user.click(screen.getByRole('button',{name:'위젯 편집'}));
    const grid=document.querySelector('.dash-grid')!;
    expect(grid.querySelector('.dash-widget h3')?.textContent).toBe('처리 단계 현황');
    await user.click(screen.getByRole('button',{name:'처리 단계 현황 뒤로 이동'}));
    expect(grid.querySelector('.dash-widget h3')?.textContent).toBe('파일 형식 분포');
    await user.click(screen.getByRole('button',{name:'파일 형식 분포 숨기기'}));
    expect(within(grid as HTMLElement).queryByText('파일 형식 분포')).toBeNull();
    await user.click(screen.getByRole('button',{name:/\+ 파일 형식 분포/}));
    expect(within(grid as HTMLElement).getByText('파일 형식 분포')).toBeTruthy();
    await user.click(within(screen.getByRole('navigation')).getByRole('button',{name:'처리 파이프라인'}));
    expect(await screen.findByRole('heading',{name:'전체 처리 흐름'})).toBeTruthy();
    await user.click(within(screen.getByRole('navigation',{name:'흐름 페이지'})).getByRole('button',{name:/Office 문서/}));
    expect(screen.getByRole('heading',{name:'Office 문서'})).toBeTruthy();
    expect(screen.getByText('레거시 변환')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'문서 탐색'}));
    await user.click(within(screen.getByRole('complementary',{name:'주 탐색 메뉴'})).getByRole('button',{name:'처리 파이프라인'}));
    expect(screen.getByRole('heading',{name:'Office 문서'})).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'설계'}));
    await user.click(screen.getByRole('button',{name:'작업 추가'}));
    await waitFor(()=>expect(localStorage.getItem('document-ops:flows:v2')).toContain('새 작업'));
  });
  it('대시보드의 처리 흐름에서 주의가 필요한 단계로 바로 들어가 개입한다',async()=>{
    const user=userEvent.setup();render(<App/>);
    await screen.findByRole('heading',{name:'운영 대시보드'});
    const live=screen.getByRole('region',{name:'처리 흐름 현황'});
    expect(within(live).getByRole('heading',{name:'처리 흐름'})).toBeTruthy();
    const first=within(live).getAllByRole('button',{name:/개입/})[0];
    const label=first.querySelector('b')!.textContent!;
    await user.click(first);
    const panel=await screen.findByRole('complementary',{name:'운영 상세'});
    expect(within(panel).getByRole('heading',{name:label})).toBeTruthy();
    expect(vi.mocked(fetch).mock.calls.every(([, options])=>!options?.method || options.method==='GET')).toBe(true);
  });
  it('문서 관계도에서 근거를 확인하고 상세 창을 Escape로 닫는다',async()=>{
    const user=userEvent.setup();render(<App/>);await screen.findByRole('heading',{name:'운영 대시보드'});
    await user.click(screen.getByRole('button',{name:'문서 관계'}));
    expect(screen.getByText('Sheet1 · B12')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:/출발 문서 보기/}));
    expect(screen.getByRole('dialog',{name:'문서 상세'})).toBeTruthy();
    await user.keyboard('{Escape}');
    await waitFor(()=>expect(screen.queryByRole('dialog',{name:'문서 상세'})).toBeNull());
  });
});
