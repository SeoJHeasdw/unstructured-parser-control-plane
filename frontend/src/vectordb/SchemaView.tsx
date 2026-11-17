import { Info, TriangleAlert } from 'lucide-react';
import type { CollectionDetail } from '../api/vectordb';
import { Disclosure, fmtCount, fmtValue, loadLabel, ROLE_LABEL } from './ui';

const yes = (v: boolean | null | undefined) => v === null || v === undefined ? '—' : v ? '예' : '아니오';

/** 스키마·인덱스. 청크 표와 번갈아 보이도록 탭 안에 둔다. */
export default function SchemaView({ detail }: { detail: CollectionDetail }) {
  const roles: Record<string, string[]> = {};
  Object.entries(detail.detected).forEach(([role, name]) => { if (name) (roles[name] ??= []).push(role); });
  const emb = detail.embedding;
  const facts: [string, string][] = [
    ['행 수', fmtCount(detail.row_count)], ['로드 상태', `${loadLabel(detail.load_state)}${detail.load_progress !== null && detail.load_progress < 100 ? ` ${detail.load_progress}%` : ''}`],
    ['일관성 수준', detail.consistency_level ?? '—'], ['샤드', fmtCount(detail.shards)], ['파티션', fmtCount(detail.partitions_num)],
    ['자동 ID', yes(detail.auto_id)], ['동적 필드', yes(detail.enable_dynamic_field)], ['별칭', detail.aliases.length ? detail.aliases.join(', ') : '없음'],
  ];
  return <div className="vdb-schema">
    <dl className="vdb-facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>

    <div className={`vdb-embed ${emb.model ? '' : 'is-missing'}`}>
      {emb.model ? <Info size={15} aria-hidden /> : <TriangleAlert size={15} aria-hidden />}
      <div>
        <b>{emb.model ? <>임베딩 모델 <code>{emb.model}</code> · {emb.dim ?? '—'}차원</> : <>임베딩 모델 기록 없음 · 벡터 {emb.dim ?? '—'}차원</>}</b>
        <span>{emb.model ? `${emb.recorded_in}에 기록된 값입니다.` : '컬렉션 속성·설명과 벡터 필드 설명에서 모델 이름을 찾지 못했습니다. 차원만 확인됩니다.'}
          {emb.dim_mismatch && ` 기록된 차원(${emb.recorded_dim})과 벡터 필드 차원(${emb.dim})이 다릅니다.`} 벡터 차원은 컬렉션을 만들 때 고정되므로, 차원이 다른 모델로 바꾸면 새 컬렉션에 다시 적재해야 합니다.</span>
      </div>
    </div>

    <div className="vdb-vectors">{detail.vector_fields.map(v => <div key={v.name} className="vdb-vector-row">
      <b>{v.name}</b><span className="vdb-dim">{v.dim ?? '—'}d</span>
      <span className="vdb-chip">{v.metric ?? '측정 방식 미확인'}</span><span className="vdb-chip">{v.index_type ?? '인덱스 없음'}</span>
      {v.index_params ? Object.entries(v.index_params).map(([k, val]) => <span key={k} className="vdb-chip is-param">{k} <b>{fmtValue(val)}</b></span>) : v.index_type ? <span className="vdb-muted">인덱스 매개변수 제공 안 됨</span> : null}
      {v.index_state && <span className={`vdb-chip ${v.index_state === 'Finished' ? 'is-ok' : 'is-warn'}`}>{v.index_state}{v.total_rows !== null ? ` · ${fmtCount(v.indexed_rows)}/${fmtCount(v.total_rows)}` : ''}{v.pending_rows ? ` · 대기 ${fmtCount(v.pending_rows)}` : ''}</span>}
      {v.fail_reason && <span className="vdb-chip is-warn" title={v.fail_reason}>실패: {fmtValue(v.fail_reason, 40)}</span>}
    </div>)}{!detail.vector_fields.length && <p className="vdb-muted">벡터 필드가 없습니다.</p>}</div>

    <div className="vdb-table-wrap">
      <table className="vdb-table is-schema">
        <thead><tr><th scope="col">필드</th><th scope="col">타입</th><th scope="col">차원·최대 길이</th><th scope="col">기본 키</th><th scope="col">null 허용</th><th scope="col">파티션 키</th><th scope="col">인덱스</th><th scope="col">화면에서 쓰는 역할</th><th scope="col">설명</th></tr></thead>
        <tbody>{detail.fields.map(f => <tr key={f.name}>
          <td><code>{f.name}</code></td>
          <td>{f.type}{f.element_type ? `<${f.element_type}>` : ''}</td>
          <td>{f.dim ? `${f.dim}차원` : f.max_length ? `${fmtCount(f.max_length)}자` : f.max_capacity ? `최대 ${f.max_capacity}개` : '—'}</td>
          <td>{f.primary_key ? (f.auto_id ? '예 · 자동' : '예') : ''}</td>
          <td>{yes(f.nullable)}</td>
          <td>{f.partition_key ? '예' : ''}</td>
          <td>{f.index_type ?? ''}</td>
          <td>{(roles[f.name] ?? []).filter(r => r !== 'pk').map(r => <span key={r} className="vdb-role">{ROLE_LABEL[r]}</span>)}</td>
          <td className="is-desc" title={f.description}>{f.description || ''}</td>
        </tr>)}</tbody>
      </table>
    </div>

    <Disclosure id="schema-props" title="설명·속성" summary={`속성 ${detail.properties.length}개`}>
      <p className="vdb-desc">{detail.description || '컬렉션 설명이 없습니다.'}</p>
      {detail.properties.length ? <dl className="vdb-kv">{detail.properties.map(p => <div key={p.key}><dt>{p.key}</dt><dd>{fmtValue(p.value, 300)}</dd></div>)}</dl> : <p className="vdb-muted">속성이 없습니다.</p>}
    </Disclosure>
    {detail.warnings.length > 0 && <Disclosure id="schema-warnings" title="읽지 못한 정보" summary={`${detail.warnings.length}건`}>
      <ul className="vdb-warnings">{detail.warnings.map(w => <li key={w}>{w}</li>)}</ul>
    </Disclosure>}
  </div>;
}
