import { useMemo, useState } from 'react';
import { Image as ImageIcon } from 'lucide-react';
import type { ChunkSource, DocElement, ElementKind, ElementOutcome } from '../api/retrieval';
import { ListBox } from '../ui';
import { ELEMENT_META, OUTCOME_META, outcomeTone } from './elements';
import { ChunkText } from './chunk-detail';
import { elementName, kindLabel, pathText } from './chunk-board';
import type { Column } from './chunk-board';
import { fmtInt } from './shared';

/** 목록 순서: 눈여겨볼 요소(표·그림·캡션) 먼저, 본문 계열, 반복 머리말. 제목은 구조라 뺀다. */
const GROUP_ORDER: ElementKind[] = ['table', 'image', 'caption', 'list', 'text', 'code', 'furniture'];
const outcomeLabel = (kind: ElementKind, outcome: ElementOutcome) =>
  kind === 'furniture' ? (outcome === 'missing' ? '제거' : '남음') : OUTCOME_META[outcome].label;

/** 원문 구성: 요소를 종류별 목록으로 고르고, 오른쪽에서 미리 보기와 전략별 결과를 본다. */
export function ElementsView({ source, columns }: { source: ChunkSource; columns: Column[] }) {
  const items = useMemo(() => GROUP_ORDER.flatMap(kind => source.elements.filter(el => el.kind === kind)), [source.elements]);
  const counts = useMemo(() => new Map(GROUP_ORDER.map(kind => [kind, items.filter(el => el.kind === kind).length])), [items]);
  const [picked, setPicked] = useState<string | null>(null);
  const current = items.find(el => el.id === picked) ?? items[0];
  const lossy = (el: DocElement) => columns.some(c => { const o = c.result.outcomes?.[el.id]; return !!o && outcomeTone(el.kind, o) === 'bad'; });
  if (!items.length) return <div className="ui-empty"><b>요소가 없습니다</b>이 문서는 요소 정보 없이 처리됐습니다.</div>;
  return <div className="cb-split">
    <div className="cb-split-list">
      <ListBox label="원문 요소" items={items} getKey={el => el.id} value={current?.id ?? null} onChange={setPicked}
        groupBy={el => `${kindLabel(el.kind)} ${fmtInt(counts.get(el.kind))}개`}
        render={el => <span className="cb-eopt">
          <i style={{ background: ELEMENT_META[el.kind].color }} />
          <span className="cb-eopt-name">{elementName(el, source.text)}</span>
          {lossy(el) && <span className="cb-dot" aria-label="손실 있음" />}
          {el.page ? <span className="cb-eopt-page">{el.page}쪽</span> : null}
        </span>} />
    </div>
    {current && <ElementPane source={source} el={current} columns={columns} />}
  </div>;
}

function ElementPane({ source, el, columns }: { source: ChunkSource; el: DocElement; columns: Column[] }) {
  const text = source.text.slice(el.start, el.end);
  const target = el.caption_of ? source.elements.find(item => item.id === el.caption_of) : undefined;
  const meta = [el.page ? `${el.page}쪽` : '', pathText(el.heading_path), `${fmtInt(el.chars)}자`].filter(Boolean).join(' · ');
  return <div className="cb-epane" aria-label="요소 상세">
    <h3 className="cb-pane-title"><i className="cb-swatch" style={{ background: ELEMENT_META[el.kind].color }} />{kindLabel(el.kind)} · {elementName(el, source.text, 60)}</h3>
    <p className="cb-pane-meta">{meta}</p>
    <div className="cb-epreview">
      {el.kind === 'image' ? (el.empty
        ? <div className="cb-figure is-empty"><ImageIcon size={20} aria-hidden="true" /><div><b>글자 없는 그림</b><span>캡션·대체 텍스트가 없어 어느 청크에도 내용이 들어가지 않습니다. 글로 옮기려면 시각 모델이 필요합니다.</span></div></div>
        : <div className="cb-figure"><ImageIcon size={20} color={ELEMENT_META.image.color} aria-hidden="true" /><div><b>{el.label}</b><span>{el.caption || text.trim() || '캡션 없음'}</span></div></div>)
        : el.kind === 'table' ? <ChunkText text={text} />
          : <>{target && <p className="cb-pane-meta">설명 대상: {target.label}</p>}<ChunkText text={text} /></>}
    </div>
    <h4 className="cb-h4">전략별 결과</h4>
    <ul className="cb-results">{columns.map(c => {
      const o = c.result.outcomes?.[el.id];
      const bad = !!o && outcomeTone(el.kind, o) === 'bad';
      return <li key={c.id}><span>{c.name}</span><b className={bad ? 'is-bad' : ''}>{c.result.error ? '실패' : o ? outcomeLabel(el.kind, o) : '—'}</b></li>;
    })}</ul>
  </div>;
}
