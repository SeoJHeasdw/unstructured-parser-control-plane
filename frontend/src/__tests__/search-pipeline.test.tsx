import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SearchPipeline from '../SearchPipeline';

beforeEach(()=>{ const store=new Map<string,string>(); vi.stubGlobal('localStorage',{getItem:(key:string)=>store.get(key) ?? null,setItem:(key:string,value:string)=>store.set(key,String(value)),removeItem:(key:string)=>store.delete(key),clear:()=>store.clear(),key:(index:number)=>[...store.keys()][index] ?? null,get length(){return store.size}}); });
afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe('검색 파이프라인 구상도',()=>{
  it('기본 화면은 흐름만 보이고, 에이전트 줄과 참고 자료는 접혀 있다',()=>{
    render(<SearchPipeline active onNavigate={vi.fn()}/>);
    const board=screen.getByRole('region',{name:'검색 파이프라인 구상도'});
    expect(within(board).getByRole('button',{name:/^에이전트 줄/}).getAttribute('aria-expanded')).toBe('false');
    expect(within(board).queryByRole('button',{name:/질의 재작성 · 분해 · 에이전트 측/})).toBeNull();
    expect(within(board).getByRole('button',{name:'리랭커 · 후보'})).toBeTruthy();
    expect(screen.queryByRole('region',{name:'단계 상세'})).toBeNull();
    expect(screen.getByRole('button',{name:/API 계약 \(가안\)/}).getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('POST /search',{exact:false})).toBeNull();
  });

  it('hover하면 설명과 관련 단계 강조를, 클릭하면 상세를 보여 주고 Escape로 닫는다',async()=>{
    const user=userEvent.setup(); const onNavigate=vi.fn();
    render(<SearchPipeline active onNavigate={onNavigate}/>);
    const board=screen.getByRole('region',{name:'검색 파이프라인 구상도'});
    await user.hover(within(board).getByRole('button',{name:'의미 검색 · 후보'}));
    expect(screen.getByRole('tooltip').textContent).toContain('dense 벡터 ANN');
    expect(within(board).getByRole('button',{name:'임베딩 · 후보'}).className).toContain('is-lit');
    expect(within(board).getByRole('button',{name:'DRM 해제 · 미정'}).className).toContain('is-dim');
    await user.unhover(within(board).getByRole('button',{name:'의미 검색 · 후보'}));
    expect(screen.queryByRole('tooltip')).toBeNull();

    await user.click(within(board).getByRole('button',{name:'청킹 · 후보'}));
    const detail=screen.getByRole('region',{name:'단계 상세'});
    expect(within(detail).getByRole('heading',{name:'청킹'})).toBeTruthy();
    await user.click(within(detail).getByRole('button',{name:/청킹 벤치 열기/}));
    expect(onNavigate).toHaveBeenCalledWith('chunking');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('region',{name:'단계 상세'})).toBeNull();
  });

  it('줄과 참고 섹션을 펼치면 상태를 기억하고, 계약 경계선은 API 계약을 연다',async()=>{
    const user=userEvent.setup();
    const { unmount }=render(<SearchPipeline active onNavigate={vi.fn()}/>);
    await user.click(screen.getByRole('button',{name:/^에이전트 줄/}));
    expect(screen.getByRole('button',{name:'질의 재작성 · 분해 · 에이전트 측'})).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'search API 계약'}));
    expect(screen.getByText('POST /search',{exact:false})).toBeTruthy();
    unmount();
    render(<SearchPipeline active onNavigate={vi.fn()}/>);
    expect(screen.getByRole('button',{name:'질의 재작성 · 분해 · 에이전트 측'})).toBeTruthy();
    expect(screen.getByRole('button',{name:/API 계약 \(가안\)/}).getAttribute('aria-expanded')).toBe('true');
  });
});
