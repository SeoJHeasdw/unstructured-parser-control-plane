import { useEffect, useState } from 'react';
import { ArrowDown, CircleCheck, CircleHelp, CircleX, Clock, KeyRound, ListTree, LoaderCircle, PlugZap, RefreshCw, Search, Server, Settings2, Terminal, TriangleAlert } from 'lucide-react';
import './modelWorkspace.css';

/** API 키는 존재 여부만 응답에 포함한다. */
type Connection = { key: string; label: string; base_url: string; model_id: string; api_key_set: boolean; configured: boolean };
type Check = { ok: boolean; status: number | null; latency_ms: number; reply?: string; model?: string; models?: string[]; error?: string };
type Operation = 'test' | 'list';
type Outcome = Check & { checkedAt: Date };
type Results = Partial<Record<string, Partial<Record<Operation, Outcome>>>>;

async function post(url: string): Promise<Check> {
  const response = await fetch(url, { method: 'POST' });
  const body = await response.json().catch(() => null) as (Partial<Check> & { detail?: string }) | null;
  if (typeof body?.ok !== 'boolean') {
    return {
      ok: false, status: response.status, latency_ms: 0,
      error: body?.detail ?? (response.ok ? '응답 형식을 확인할 수 없습니다.' : `HTTP ${response.status}`),
    };
  }
  return body as Check;
}

const timeFormat = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

function GatewayStatus({ conn, pending, result }: { conn: Connection; pending?: Operation; result?: Outcome }) {
  if (!conn.configured) return <span className="ui-pill mw-chip">미설정</span>;
  if (pending === 'test') return <span className="ui-pill is-accent mw-chip"><LoaderCircle size={13} className="mw-spin" aria-hidden="true" /> 응답 확인 중</span>;
  if (!result) return <span className="ui-pill mw-chip"><Clock size={13} aria-hidden="true" /> 확인 전</span>;
  return <span className={`ui-pill mw-chip ${result.ok ? 'is-ok' : 'is-bad'}`}>
    {result.ok ? <CircleCheck size={13} aria-hidden="true" /> : <CircleX size={13} aria-hidden="true" />}
    {result.ok ? '응답 확인' : '확인 실패'}
  </span>;
}

function ErrorHint({ code, kind }: { code: number | null; kind: Operation }) {
  switch (code) {
    case 401:
    case 403:
      return <span>서버의 API 키와 게이트웨이 권한을 확인하세요.</span>;
    case 404:
      return <span>{kind === 'test' ? 'Base URL과 Model ID를 확인하세요.' : '게이트웨이의 모델 목록 지원 여부를 확인하세요.'}</span>;
    case 409:
      return <span>서버의 연결 설정을 확인하고 다시 읽으세요.</span>;
    case 429:
      return <span>게이트웨이 요청 한도를 확인한 뒤 다시 시도하세요.</span>;
    default:
      return <span>서버와 게이트웨이 연결을 확인한 뒤 다시 시도하세요.</span>;
  }
}

function RequestError({ result, kind }: { result: Outcome; kind: Operation }) {
  return <div className="mw-message is-bad" role="status">
    <CircleX size={17} aria-hidden="true" />
    <div>
      <strong>{kind === 'test' ? '모델 응답을 확인하지 못했습니다' : '모델 목록을 가져오지 못했습니다'}</strong>
      <ErrorHint code={result.status} kind={kind} />
      {result.error && <p className="mw-error-detail">{result.error}</p>}
    </div>
    <time dateTime={result.checkedAt.toISOString()}>{timeFormat.format(result.checkedAt)}</time>
  </div>;
}

function ModelList({ result, conn }: { result: Outcome; conn: Connection }) {
  const [query, setQuery] = useState('');
  const models = result.models ?? [];
  const matches = models.filter(id => id.toLowerCase().includes(query.trim().toLowerCase()));
  if (!result.ok) return <RequestError result={result} kind="list" />;
  return <section className="mw-list" aria-label={`${conn.label}에서 반환된 모델 목록`}>
    <header>
      <h3><ListTree size={16} aria-hidden="true" /> 게이트웨이 모델 목록 <span className="ui-pill">{models.length}</span></h3>
      <time dateTime={result.checkedAt.toISOString()}>{timeFormat.format(result.checkedAt)}</time>
    </header>
    {models.length > 0 ? <>
      <label className="mw-search"><Search size={16} aria-hidden="true" /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="모델 ID 검색" aria-label={`${conn.label} 모델 ID 검색`} /></label>
      {matches.length > 0 ? <ul className="mw-model-list" tabIndex={0} aria-label="검색된 모델">
        {matches.map(id => <li key={id}><code>{id}</code>{id === conn.model_id && <span className="ui-pill is-accent">현재 설정</span>}</li>)}
      </ul> : <p className="mw-list-empty" role="status">일치하는 모델 ID가 없습니다.</p>}
    </> : <p className="mw-list-empty">게이트웨이가 모델 ID를 반환하지 않았습니다.</p>}
  </section>;
}

function SetupGuide({ defaultOpen }: { defaultOpen: boolean }) {
  return <details className="mw-setup" open={defaultOpen || undefined}>
    <summary><span className="mw-setup-icon"><Terminal size={18} aria-hidden="true" /></span><strong>서버에서 연결 설정하기</strong><ArrowDown size={16} className="mw-setup-arrow" aria-hidden="true" /></summary>
    <div className="mw-setup-body">
      <p>프로젝트의 <code>.env</code> 또는 서버 환경변수에 값을 입력하고 서버를 다시 시작하세요. 인증이 필요한 게이트웨이는 API 키도 설정해야 합니다.</p>
      <dl className="mw-env">
        <div><dt>기본 연결</dt><dd><code>MODEL_BASE_URL</code><code>MODEL_ID</code><code>MODEL_API_KEY</code></dd></div>
        <div><dt>보조 연결</dt><dd><code>MODEL2_BASE_URL</code><code>MODEL2_ID</code><code>MODEL2_API_KEY</code></dd></div>
      </dl>
    </div>
  </details>;
}

export default function ModelWorkspace() {
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Partial<Record<string, Operation>>>({});
  const [results, setResults] = useState<Results>({});
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setLoadError('');
    fetch('/api/models', { signal }).then(async response => {
      if (!response.ok) throw new Error();
      const body: { connections?: Connection[] } = await response.json();
      if (!Array.isArray(body.connections)) throw new Error();
      if (!signal.aborted) {
        setConnections(body.connections);
        setResults({});
      }
    }).catch(() => {
      if (!signal.aborted) setLoadError('로컬 서버에서 모델 설정을 읽지 못했습니다. 서버 실행 상태를 확인하세요.');
    }).finally(() => {
      if (!signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [reload]);

  const run = async (key: string, kind: Operation) => {
    setPending(prev => ({ ...prev, [key]: kind }));
    const result: Check = await post(`/api/models/${encodeURIComponent(key)}/${kind === 'test' ? 'test' : 'models'}`)
      .catch(() => ({ ok: false, status: null, latency_ms: 0, error: '로컬 서버에 연결하지 못했습니다.' }));
    setResults(prev => ({ ...prev, [key]: { ...prev[key], [kind]: { ...result, checkedAt: new Date() } } }));
    setPending(prev => ({ ...prev, [key]: undefined }));
  };
  const configured = connections?.filter(conn => conn.configured).length ?? 0;
  const reloadBusy = loading || Object.values(pending).some(Boolean);
  const refresh = () => setReload(value => value + 1);
  return <div className="mw-workspace">
    <section className="mw-overview" aria-label="게이트웨이 설정 개요">
      <span className="mw-overview-icon"><Server size={23} strokeWidth={1.7} aria-hidden="true" /></span>
      <div className="mw-overview-copy"><h2>OpenAI 호환 게이트웨이</h2>
        <p>연결 확인은 설정된 모델에 짧은 확인 요청을 보냅니다. API 키는 서버에서 관리합니다.</p>
      </div>
      <div className="mw-overview-actions">
        {connections && !loadError && <span className="ui-pill is-accent"><b className="ui-num">{configured}/{connections.length}</b> 설정됨</span>}
        <button className="button-secondary" onClick={refresh} disabled={reloadBusy}>
          <RefreshCw size={16} className={loading ? 'mw-spin' : undefined} aria-hidden="true" /> 설정 다시 읽기
        </button>
      </div>
    </section>
    {loading && !connections && <div className="mw-state" role="status"><LoaderCircle size={20} className="mw-spin" aria-hidden="true" /> 설정 불러오는 중</div>}
    {loadError && <div className="mw-message is-bad mw-load-error" role="alert">
      <TriangleAlert size={18} aria-hidden="true" /><div><strong>모델 설정을 확인할 수 없습니다</strong><span>{loadError}</span></div>
      <button className="button-secondary" onClick={refresh} disabled={reloadBusy}>다시 시도</button>
    </div>}
    {connections && connections.length === 0 && <div className="mw-state" role="status"><CircleHelp size={20} aria-hidden="true" /> 등록된 게이트웨이 연결이 없습니다.</div>}
    {connections && connections.length > 0 && <div className="mw-gateway-grid" aria-busy={loading}>
      {connections.map(conn => {
        const result = results[conn.key];
        const running = pending[conn.key];
        const canRun = conn.configured && !running && !loading && !loadError;
        return <section className="mw-gateway" key={conn.key} aria-label={conn.label}>
          <header className="mw-gateway-head">
            <span className="mw-gateway-icon"><PlugZap size={19} strokeWidth={1.8} aria-hidden="true" /></span>
            <div><h2>{conn.label}</h2><p>{conn.key === 'primary' ? '기본 연결' : '보조 연결'}</p></div>
            <GatewayStatus conn={conn} pending={running} result={result?.test} />
          </header>
          <p className="gateway-last">{conn.configured ? '설정됨' : '미설정'} · {result?.test ? '마지막 확인 ' + timeFormat.format(result.test.checkedAt) : '연결 확인 전'}</p>
          <details className="gateway-details"><summary>연결 정보</summary><dl className="mw-properties">
            <div><dt>Base URL</dt><dd>{conn.base_url ? <code>{conn.base_url}</code> : '미설정'}</dd></div>
            <div><dt>Model ID</dt><dd>{conn.model_id ? <code>{conn.model_id}</code> : '미설정'}</dd></div>
            <div><dt><KeyRound size={14} aria-hidden="true" /> API 키</dt><dd>{conn.api_key_set ? '서버에 설정됨' : '미설정'}</dd></div>
          </dl></details>
          <div className="mw-gateway-actions">
            <button className="button-primary" disabled={!canRun} onClick={() => void run(conn.key, 'test')}>
              {running === 'test' ? <LoaderCircle size={16} className="mw-spin" aria-hidden="true" /> : <PlugZap size={16} aria-hidden="true" />}
              {running === 'test' ? '응답 확인 중' : '연결 확인'}
            </button>
            <button className="button-secondary" disabled={!canRun} onClick={() => void run(conn.key, 'list')}>
              {running === 'list' ? <LoaderCircle size={16} className="mw-spin" aria-hidden="true" /> : <ListTree size={16} aria-hidden="true" />}
              {running === 'list' ? '목록 조회 중' : '모델 목록 조회'}
            </button>
          </div>
          {!conn.configured && <p className="mw-config-missing"><Settings2 size={15} aria-hidden="true" /> Base URL과 Model ID를 설정하면 연결을 확인할 수 있습니다.</p>}
          {result?.test && (result.test.ok ? <div className="mw-message is-ok" role="status">
            <CircleCheck size={17} aria-hidden="true" />
            <div><strong>모델 응답 확인 <b className="ui-num">{result.test.latency_ms.toLocaleString('ko-KR')} ms</b></strong>
              <span><code>{result.test.model ?? conn.model_id}</code>{result.test.reply && <> · {result.test.reply}</>}</span></div>
            <time dateTime={result.test.checkedAt.toISOString()}>{timeFormat.format(result.test.checkedAt)}</time>
          </div> : <RequestError result={result.test} kind="test" />)}
          {result?.list && <ModelList key={result.list.checkedAt.getTime()} result={result.list} conn={conn} />}
        </section>;
      })}
    </div>}
    {connections && <SetupGuide key={configured ? 'configured' : 'missing'} defaultOpen={!configured} />}
  </div>;
}
