import { useEffect, useState } from 'react';
import { CircleCheck, CircleX, ListTree, LoaderCircle, PlugZap, RefreshCw, Server } from 'lucide-react';

/** 서버 환경변수(.env)에 설정된 OpenAI 호환 모델 연결. API 키 값은 화면으로 오지 않는다. */
type Connection = { key: string; label: string; base_url: string; model_id: string; api_key_set: boolean; configured: boolean };
type Check = { ok: boolean; status: number | null; latency_ms: number; reply?: string; model?: string; models?: string[]; error?: string };

async function post(url: string): Promise<Check> {
  const response = await fetch(url, { method: 'POST' });
  const body = await response.json().catch(() => ({})) as Partial<Check> & { detail?: string };
  if (!response.ok && body.ok === undefined) return { ok: false, status: response.status, latency_ms: 0, error: body.detail ?? `HTTP ${response.status}` };
  return body as Check;
}

export default function ModelWorkspace() {
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { test?: Check; list?: Check }>>({});
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    fetch('/api/models').then(response => { if (!response.ok) throw new Error(); return response.json(); })
      .then((body: { connections: Connection[] }) => { if (alive) { setConnections(body.connections); setLoadError(''); } })
      .catch(() => { if (alive) { setConnections(null); setLoadError('로컬 서버에서 모델 설정을 읽지 못했습니다.'); } });
    return () => { alive = false; };
  }, [reload]);
  const run = async (key: string, kind: 'test' | 'list') => {
    setBusy(`${key}:${kind}`);
    const result = await post(`/api/models/${encodeURIComponent(key)}/${kind === 'test' ? 'test' : 'models'}`).catch(() => ({ ok: false, status: null, latency_ms: 0, error: '로컬 서버에 연결하지 못했습니다.' }) as Check);
    setResults(prev => ({ ...prev, [key]: { ...prev[key], [kind]: result } }));
    setBusy(null);
  };
  return <div className="model-workspace">
    <div className="mw-head"><div><p>OpenAI 호환 주소(base_url)·API 키·모델 ID로 연결합니다. 연결 확인은 버튼을 누를 때만 짧은 요청 한 번을 보냅니다.</p></div><button className="button-secondary" onClick={() => setReload(value => value + 1)}><RefreshCw size={14} /> 설정 다시 읽기</button></div>
    {loadError && <div className="shell-info" role="alert"><CircleX size={16} /><span>{loadError}</span></div>}
    <div className="model-grid">{(connections ?? []).map(conn => { const result = results[conn.key]; return <section className="panel model-card" key={conn.key} aria-label={conn.label}>
      <div className="model-card-top"><span className="model-icon"><Server size={19} /></span><span className={`mw-status ${conn.configured ? 'is-on' : ''}`}>{conn.configured ? '설정됨' : '미설정'}</span></div>
      <h3>{conn.label}</h3>
      <div className="model-lines">
        <div><span>Base URL</span><b title={conn.base_url}>{conn.base_url || '설정되지 않음'}</b></div>
        <div><span>API Key</span><b>{conn.api_key_set ? '설정됨 (값은 표시하지 않음)' : '없음'}</b></div>
        <div><span>Model ID</span><b>{conn.model_id || '설정되지 않음'}</b></div>
      </div>
      <div className="mw-actions">
        <button className="button-primary" disabled={!conn.configured || !!busy} onClick={() => run(conn.key, 'test')}>{busy === `${conn.key}:test` ? <LoaderCircle size={14} className="mw-spin" /> : <PlugZap size={14} />} 연결 확인</button>
        <button className="button-secondary" disabled={!conn.configured || !!busy} onClick={() => run(conn.key, 'list')}>{busy === `${conn.key}:list` ? <LoaderCircle size={14} className="mw-spin" /> : <ListTree size={14} />} 모델 목록</button>
      </div>
      {result?.test && <div className={`mw-result ${result.test.ok ? 'is-ok' : 'is-error'}`} role="status">{result.test.ok ? <CircleCheck size={15} /> : <CircleX size={15} />}<div><b>{result.test.ok ? `응답 확인 · ${result.test.latency_ms}ms` : `실패${result.test.status ? ` · HTTP ${result.test.status}` : ''}`}</b><span>{result.test.ok ? `${result.test.model}: ${result.test.reply || '(빈 응답)'}` : result.test.error}</span></div></div>}
      {result?.list && <div className={`mw-result ${result.list.ok ? 'is-ok' : 'is-error'}`}>{result.list.ok ? <ListTree size={15} /> : <CircleX size={15} />}<div><b>{result.list.ok ? `모델 ${result.list.models?.length ?? 0}개` : '목록을 가져오지 못함'}</b>{result.list.ok ? <ul className="mw-models">{result.list.models?.map(id => <li key={id} className={id === conn.model_id ? 'is-current' : ''}>{id}</li>)}</ul> : <span>{result.list.error}</span>}</div></div>}
      {!conn.configured && <p className="mw-hint">프로젝트 루트 <code>.env</code>에 <code>{conn.key === 'primary' ? 'MODEL' : 'MODEL2'}_BASE_URL</code>, <code>_API_KEY</code>, <code>_ID</code>를 넣고 서버를 다시 시작하세요.</p>}
    </section>; })}</div>
  </div>;
}
