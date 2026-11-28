import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDown, Binary, Check as CheckIcon, CircleCheck, CircleX, Clock, KeyRound, ListTree, LoaderCircle, Pencil, PlugZap, Plus, RefreshCw, RotateCcw, ScanText, Search, Server, Terminal, TriangleAlert, X } from 'lucide-react';
import { forgetConnection, draftBody, runCheck, saveConnection } from './api/models';
import type { ChatConnection, Check, Draft, EmbeddingConnection, Listing, OcrConnection, OcrMode, OcrPrompts, Slot } from './api/models';
import { Modal, Tabs } from './ui';
import './modelWorkspace.css';

type Operation = 'test' | 'list';
type Outcome = Check & { checkedAt: Date };
type Results = Partial<Record<string, Partial<Record<Operation, Outcome>>>>;
type OcrEditing = OcrPrompts & { mode: OcrMode; defaults: OcrPrompts };
type Editing = { slot: Slot; label: string; base_url: string; model_id: string; models: string[]; api_key_set: boolean; saved: boolean; ocr?: OcrEditing };
type Tab = 'chat' | 'embed' | 'ocr';

const timeFormat = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const SLOT_NAME: Record<Slot, string> = { primary: '기본 연결', secondary: '보조 연결', embedding: '임베딩 게이트웨이', ocr: 'OCR 모델' };
/** 서버(app/ocr_model.py DEFAULTS)와 같은 기본 지시문. */
const OCR_DEFAULTS: OcrPrompts = { text_prompt: 'OCR:', table_prompt: 'Table Recognition:', page_prompt: 'document parsing.' };
const OCR_MODES: Record<OcrMode, { name: string; detail: string }> = {
  region: { name: '영역 방식', detail: '레이아웃으로 나눠 영역마다 호출 · PaddleOCR-VL 등' },
  page: { name: '쪽 방식', detail: '쪽 전체를 한 번 호출 · Schift·Unlimited-OCR 등' },
};
const OCR_PROMPTS: Record<OcrMode, { key: keyof OcrPrompts; label: string }[]> = {
  region: [{ key: 'text_prompt', label: '글자 지시문' }, { key: 'table_prompt', label: '표 지시문' }],
  page: [{ key: 'page_prompt', label: '쪽 지시문' }],
};
const ocrDefaults = (conn: OcrConnection): OcrPrompts => ({ ...OCR_DEFAULTS, ...conn.defaults });
const normalizeListing = (body: Partial<Listing>): Listing => ({ connections: body.connections ?? [], embedding: body.embedding ?? null, ocr: body.ocr ?? null });

function GatewayStatus({ configured, pending, result, okLabel = '응답 확인' }: { configured: boolean; pending?: Operation; result?: Outcome; okLabel?: string }) {
  if (!configured) return <span className="ui-pill mw-chip">미설정</span>;
  if (pending === 'test') return <span className="ui-pill is-accent mw-chip"><LoaderCircle size={13} className="mw-spin" aria-hidden="true" /> 확인 중</span>;
  if (!result) return <span className="ui-pill mw-chip"><Clock size={13} aria-hidden="true" /> 확인 전</span>;
  return <span className={`ui-pill mw-chip ${result.ok ? 'is-ok' : 'is-bad'}`}>
    {result.ok ? <CircleCheck size={13} aria-hidden="true" /> : <CircleX size={13} aria-hidden="true" />}
    {result.ok ? okLabel : '확인 실패'}
  </span>;
}

function ErrorHint({ code, kind }: { code: number | null; kind: Operation }) {
  switch (code) {
    case 401:
    case 403: return <span>API 키와 게이트웨이 권한을 확인하세요.</span>;
    case 404: return <span>{kind === 'test' ? 'Base URL과 모델 ID를 확인하세요.' : '게이트웨이의 모델 목록 지원 여부를 확인하세요.'}</span>;
    case 200: return <span>응답은 왔지만 확인 기준을 통과하지 못했습니다. 모델과 설정을 확인하세요.</span>;
    case 400: case 409: return <span>연결 설정을 확인하세요.</span>;
    case 429: return <span>게이트웨이 요청 한도를 확인한 뒤 다시 시도하세요.</span>;
    default: return <span>서버와 게이트웨이 연결을 확인한 뒤 다시 시도하세요.</span>;
  }
}

function RequestError({ result, kind }: { result: Outcome; kind: Operation }) {
  return <div className="mw-message is-bad" role="status">
    <CircleX size={17} aria-hidden="true" />
    <div>
      <strong>{kind === 'test' ? '모델 응답을 확인하지 못했습니다' : '모델 목록을 가져오지 못했습니다'}</strong>
      <ErrorHint code={result.status} kind={kind} />
      {result.error && <p className="mw-error-detail">{result.error}</p>}
      {result.reply && <p className="mw-error-detail">모델 응답: {result.reply}</p>}
    </div>
    <time dateTime={result.checkedAt.toISOString()}>{timeFormat.format(result.checkedAt)}</time>
  </div>;
}

function ModelList({ result, label, current }: { result: Outcome; label: string; current: string[] }) {
  const [query, setQuery] = useState('');
  const models = result.models ?? [];
  const matches = models.filter(id => id.toLowerCase().includes(query.trim().toLowerCase()));
  if (!result.ok) return <RequestError result={result} kind="list" />;
  return <section className="mw-list" aria-label={`${label}에서 반환된 모델 목록`}>
    <header>
      <h3><ListTree size={16} aria-hidden="true" /> 게이트웨이 모델 목록 <span className="ui-pill">{models.length}</span></h3>
      <time dateTime={result.checkedAt.toISOString()}>{timeFormat.format(result.checkedAt)}</time>
    </header>
    {models.length > 0 ? <>
      <label className="mw-search"><Search size={16} aria-hidden="true" /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="모델 ID 검색" aria-label={`${label} 모델 ID 검색`} /></label>
      {matches.length > 0 ? <ul className="mw-model-list" tabIndex={0} aria-label="검색된 모델">
        {matches.map(id => <li key={id}><code>{id}</code>{current.includes(id) && <span className="ui-pill is-accent">현재 설정</span>}</li>)}
      </ul> : <p className="mw-list-empty" role="status">일치하는 모델 ID가 없습니다.</p>}
    </> : <p className="mw-list-empty">게이트웨이가 모델 ID를 반환하지 않았습니다.</p>}
  </section>;
}

function SourceBadge({ saved, configured }: { saved?: boolean; configured: boolean }) {
  if (saved) return <span className="mw-source is-saved" data-tip="이 화면에서 저장한 값을 씁니다. .env보다 우선합니다.">화면에서 저장</span>;
  return configured ? <span className="mw-source" data-tip="서버의 .env 또는 환경변수 값을 씁니다.">.env</span> : null;
}

function Properties({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return <dl className="mw-properties">{rows.map(([dt, dd], i) => <div key={i}><dt>{dt}</dt><dd>{dd}</dd></div>)}</dl>;
}

function SetupGuide() {
  return <details className="mw-setup">
    <summary><span className="mw-setup-icon"><Terminal size={18} aria-hidden="true" /></span><strong>서버 파일로 설정하기 (.env)</strong><ArrowDown size={16} className="mw-setup-arrow" aria-hidden="true" /></summary>
    <div className="mw-setup-body">
      <p>여러 PC에 같은 값을 배포할 때는 프로젝트의 <code>.env</code> 또는 서버 환경변수를 쓰고 서버를 다시 시작하세요. 이 화면에서 저장한 값이 있으면 그 값이 우선합니다.</p>
      <dl className="mw-env">
        <div><dt>기본 연결</dt><dd><code>MODEL_BASE_URL</code><code>MODEL_ID</code><code>MODEL_API_KEY</code></dd></div>
        <div><dt>보조 연결</dt><dd><code>MODEL2_BASE_URL</code><code>MODEL2_ID</code><code>MODEL2_API_KEY</code></dd></div>
        <div><dt>임베딩</dt><dd><code>EMBED_BASE_URL</code><code>EMBED_MODELS</code><code>EMBED_API_KEY</code></dd></div>
        <div><dt>OCR</dt><dd><code>OCR_BASE_URL</code><code>OCR_MODEL</code><code>OCR_API_KEY</code><code>OCR_MODE</code></dd></div>
      </dl>
    </div>
  </details>;
}

export default function ModelWorkspace() {
  const [listing, setListing] = useState<Listing | null>(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Partial<Record<string, Operation>>>({});
  const [results, setResults] = useState<Results>({});
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState<Tab>('chat');
  const [editing, setEditing] = useState<Editing | null>(null);
  const [embedModel, setEmbedModel] = useState('');
  const [notice, setNotice] = useState('');
  const editTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setLoadError('');
    fetch('/api/models', { signal }).then(async response => {
      if (!response.ok) throw new Error();
      const body = await response.json() as Partial<Listing>;
      if (!Array.isArray(body.connections)) throw new Error();
      if (!signal.aborted) { setListing(normalizeListing(body)); setResults({}); }
    }).catch(() => {
      if (!signal.aborted) setLoadError('로컬 서버에서 모델 설정을 읽지 못했습니다. 서버 실행 상태를 확인하세요.');
    }).finally(() => { if (!signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 5000); return () => window.clearTimeout(timer); }, [notice]);

  const run = async (key: string, kind: Operation, url: string, body?: unknown) => {
    setPending(prev => ({ ...prev, [key]: kind }));
    const result = await runCheck(url, body);
    setResults(prev => ({ ...prev, [key]: { ...prev[key], [kind]: { ...result, checkedAt: new Date() } } }));
    setPending(prev => ({ ...prev, [key]: undefined }));
  };
  const openEditor = (value: Editing) => { editTrigger.current = document.activeElement as HTMLElement; setEditing(value); };
  const closeEditor = () => { setEditing(null); requestAnimationFrame(() => editTrigger.current?.focus()); };
  const applyListing = (next: Listing, message: string, slot: Slot) => {
    setListing(normalizeListing(next)); setNotice(message);
    setResults(prev => ({ ...prev, [slot]: undefined }));
  };

  const chats = listing?.connections ?? [];
  const embedding = listing?.embedding ?? null;
  const ocr = listing?.ocr ?? null;
  const configured = chats.filter(conn => conn.configured).length;
  const reloadBusy = loading || Object.values(pending).some(Boolean);
  const blocked = loading || !!loadError;
  const editChat = (conn: ChatConnection) => openEditor({ slot: conn.key, label: conn.label, base_url: conn.base_url, model_id: conn.model_id, models: [], api_key_set: conn.api_key_set, saved: !!conn.saved });

  const chatCard = (conn: ChatConnection) => {
    const result = results[conn.key];
    const running = pending[conn.key];
    const canRun = conn.configured && !running && !blocked;
    return <section className="mw-gateway" key={conn.key} aria-label={conn.label}>
      <header className="mw-gateway-head">
        <span className="mw-gateway-icon"><PlugZap size={19} strokeWidth={1.8} aria-hidden="true" /></span>
        <div><h2>{conn.label}</h2><p>{conn.label !== SLOT_NAME[conn.key] && SLOT_NAME[conn.key]} <SourceBadge saved={conn.saved} configured={conn.configured} /></p></div>
        <GatewayStatus configured={conn.configured} pending={running} result={result?.test} />
      </header>
      <Properties rows={[
        ['Base URL', conn.base_url ? <code>{conn.base_url}</code> : '미설정'],
        ['모델 ID', conn.model_id ? <code>{conn.model_id}</code> : '미설정'],
        [<><KeyRound size={14} aria-hidden="true" /> API 키</>, conn.api_key_set ? '저장됨 (표시하지 않음)' : '없음'],
      ]} />
      <div className="mw-gateway-actions">
        {conn.configured ? <>
          <button className="button-primary" disabled={!canRun} onClick={() => void run(conn.key, 'test', `/api/models/${conn.key}/test`)}>
            {running === 'test' ? <LoaderCircle size={16} className="mw-spin" aria-hidden="true" /> : <PlugZap size={16} aria-hidden="true" />}{running === 'test' ? '응답 확인 중' : '연결 확인'}
          </button>
          <button className="button-secondary" disabled={!canRun} onClick={() => void run(conn.key, 'list', `/api/models/${conn.key}/models`)}>
            {running === 'list' ? <LoaderCircle size={16} className="mw-spin" aria-hidden="true" /> : <ListTree size={16} aria-hidden="true" />}{running === 'list' ? '목록 조회 중' : '모델 목록 조회'}
          </button>
          <button className="button-quiet mw-edit" disabled={blocked} onClick={() => editChat(conn)}><Pencil size={15} aria-hidden="true" />설정 편집</button>
        </> : <>
          <button className="button-primary" disabled={blocked} onClick={() => editChat(conn)}><Pencil size={16} aria-hidden="true" />연결 설정</button>
          <button className="button-secondary" disabled>연결 확인</button>
          <button className="button-secondary" disabled>모델 목록 조회</button>
        </>}
      </div>
      {result?.test && (result.test.ok ? <div className="mw-message is-ok" role="status">
        <CircleCheck size={17} aria-hidden="true" />
        <div><strong>모델 응답 확인 <b className="ui-num">{result.test.latency_ms.toLocaleString('ko-KR')} ms</b></strong>
          <span><code>{result.test.model ?? conn.model_id}</code>{result.test.reply && <> · {result.test.reply}</>}</span></div>
        <time dateTime={result.test.checkedAt.toISOString()}>{timeFormat.format(result.test.checkedAt)}</time>
      </div> : <RequestError result={result.test} kind="test" />)}
      {result?.list && <ModelList key={result.list.checkedAt.getTime()} result={result.list} label={conn.label} current={[conn.model_id]} />}
    </section>;
  };

  const embedCard = (conn: EmbeddingConnection) => {
    const result = results.embedding;
    const running = pending.embedding;
    const model = conn.models.includes(embedModel) ? embedModel : conn.models[0] ?? '';
    const canRun = conn.configured && !!model && !running && !blocked;
    const edit = () => openEditor({ slot: 'embedding', label: conn.label, base_url: conn.base_url, model_id: '', models: conn.models, api_key_set: conn.api_key_set, saved: !!conn.saved });
    return <section className="mw-gateway" aria-label={conn.label}>
      <header className="mw-gateway-head">
        <span className="mw-gateway-icon"><Binary size={19} strokeWidth={1.8} aria-hidden="true" /></span>
        <div><h2>{conn.label}</h2><p>{conn.label !== SLOT_NAME.embedding && SLOT_NAME.embedding} <SourceBadge saved={conn.saved} configured={conn.configured} /></p></div>
        <GatewayStatus configured={conn.configured && conn.models.length > 0} pending={running} result={result?.test} okLabel="임베딩 확인" />
      </header>
      <Properties rows={[
        ['Base URL', conn.base_url ? <code>{conn.base_url}</code> : '미설정'],
        ['모델', conn.models.length ? <span className="mw-chips">{conn.models.map(id => <code key={id}>{id}</code>)}</span> : '미설정'],
        [<><KeyRound size={14} aria-hidden="true" /> API 키</>, conn.api_key_set ? '저장됨 (표시하지 않음)' : '없음'],
      ]} />
      <div className="mw-gateway-actions">
        {conn.configured && conn.models.length > 0 ? <>
          {conn.models.length > 1 && <select className="mw-model-pick" aria-label="확인할 임베딩 모델" value={model} onChange={event => setEmbedModel(event.target.value)}>
            {conn.models.map(id => <option key={id} value={id}>{id}</option>)}</select>}
          <button className="button-primary" disabled={!canRun} onClick={() => void run('embedding', 'test', '/api/models/embedding/test', { model })}>
            {running === 'test' ? <LoaderCircle size={16} className="mw-spin" aria-hidden="true" /> : <PlugZap size={16} aria-hidden="true" />}{running === 'test' ? '임베딩 확인 중' : '임베딩 확인'}
          </button>
          <button className="button-secondary" disabled={!conn.configured || !!running || blocked} onClick={() => void run('embedding', 'list', '/api/models/embedding/models')}>
            <ListTree size={16} aria-hidden="true" />모델 목록 조회
          </button>
          <button className="button-quiet mw-edit" disabled={blocked} onClick={edit}><Pencil size={15} aria-hidden="true" />설정 편집</button>
        </> : <button className="button-primary" disabled={blocked} onClick={edit}><Pencil size={16} aria-hidden="true" />연결 설정</button>}
      </div>
      <p className="mw-usage">의미 기반 청킹과 임베딩 평가가 이 연결을 씁니다. 생성 모델 게이트웨이가 <code>/embeddings</code>를 지원하면 그 연결도 평가에서 고를 수 있습니다.</p>
      {result?.test && (result.test.ok ? <div className="mw-message is-ok" role="status">
        <CircleCheck size={17} aria-hidden="true" />
        <div><strong>임베딩 확인 <b className="ui-num">{result.test.latency_ms.toLocaleString('ko-KR')} ms</b></strong>
          <span><code>{result.test.model}</code>{result.test.dims ? <> · {result.test.dims.toLocaleString('ko-KR')}차원</> : null}</span></div>
        <time dateTime={result.test.checkedAt.toISOString()}>{timeFormat.format(result.test.checkedAt)}</time>
      </div> : <RequestError result={result.test} kind="test" />)}
      {result?.list && <ModelList key={result.list.checkedAt.getTime()} result={result.list} label={conn.label} current={conn.models} />}
    </section>;
  };

  const ocrCard = (conn: OcrConnection) => {
    const result = results.ocr;
    const running = pending.ocr;
    const canRun = conn.configured && !running && !blocked;
    const defaults = ocrDefaults(conn);
    const mode = OCR_MODES[conn.mode] ?? OCR_MODES.region;
    const edit = () => openEditor({ slot: 'ocr', label: conn.label, base_url: conn.base_url, model_id: conn.model_id, models: [], api_key_set: conn.api_key_set, saved: !!conn.saved,
      ocr: { mode: conn.mode === 'page' ? 'page' : 'region', text_prompt: conn.text_prompt, table_prompt: conn.table_prompt, page_prompt: conn.page_prompt, defaults } });
    return <section className="mw-gateway" aria-label={conn.label}>
      <header className="mw-gateway-head">
        <span className="mw-gateway-icon"><ScanText size={19} strokeWidth={1.8} aria-hidden="true" /></span>
        <div><h2>{conn.label}</h2><p>{conn.label !== SLOT_NAME.ocr && SLOT_NAME.ocr} <SourceBadge saved={conn.saved} configured={conn.configured} /></p></div>
        <GatewayStatus configured={conn.configured} pending={running} result={result?.test} okLabel="OCR 확인" />
      </header>
      <Properties rows={[
        ['Base URL', conn.base_url ? <code>{conn.base_url}</code> : '미설정'],
        ['모델 ID', conn.model_id ? <code>{conn.model_id}</code> : '미설정'],
        ['방식', <>{mode.name} <span className="mw-sub">{mode.detail}</span></>],
        ['지시문', <span className="mw-chips">{OCR_PROMPTS[conn.mode === 'page' ? 'page' : 'region'].map(({ key, label }) =>
          <span key={key} className="mw-prompt">{label} <code>{conn[key] || defaults[key]}</code>{(conn[key] || defaults[key]) === defaults[key] && <small>기본</small>}</span>)}</span>],
        [<><KeyRound size={14} aria-hidden="true" /> API 키</>, conn.api_key_set ? '설정됨 (표시하지 않음)' : '없음'],
      ]} />
      <div className="mw-gateway-actions">
        {conn.configured ? <>
          <button className="button-primary" disabled={!canRun} onClick={() => void run('ocr', 'test', '/api/models/ocr/test')}>
            {running === 'test' ? <LoaderCircle size={16} className="mw-spin" aria-hidden="true" /> : <PlugZap size={16} aria-hidden="true" />}{running === 'test' ? 'OCR 확인 중' : 'OCR 확인'}
          </button>
          <button className="button-quiet mw-edit" disabled={blocked} onClick={edit}><Pencil size={15} aria-hidden="true" />설정 편집</button>
        </> : <button className="button-primary" disabled={blocked} onClick={edit}><Pencil size={16} aria-hidden="true" />연결 설정</button>}
      </div>
      <p className="mw-usage">라이브러리 OCR(EasyOCR 등)은 쓰지 않습니다. 스캔 PDF 쪽과 이미지의 글자는 여기 연결한 모델로만 읽고, 연결하지 않으면 읽지 않습니다. OCR 확인은 시험 그림 한 장을 읽힙니다.</p>
      {result?.test && (result.test.ok ? <div className="mw-message is-ok" role="status">
        <CircleCheck size={17} aria-hidden="true" />
        <div><strong>OCR 확인 <b className="ui-num">{result.test.latency_ms.toLocaleString('ko-KR')} ms</b></strong>
          <span><code>{result.test.model ?? conn.model_id}</code>{result.test.reply && <> · {result.test.reply}</>}</span></div>
        <time dateTime={result.test.checkedAt.toISOString()}>{timeFormat.format(result.test.checkedAt)}</time>
      </div> : <RequestError result={result.test} kind="test" />)}
    </section>;
  };

  return <div className="mw-workspace">
    <section className="mw-overview" aria-label="모델 연결 개요">
      <span className="mw-overview-icon"><Server size={23} strokeWidth={1.7} aria-hidden="true" /></span>
      <div className="mw-overview-copy"><h2>OpenAI 호환 게이트웨이</h2>
        <p>여기서 저장하면 서버를 다시 시작하지 않아도 바로 씁니다. 저장한 값은 이 PC의 실행 폴더에 두고, API 키는 다시 보여 주지 않습니다.</p>
      </div>
      <div className="mw-overview-actions">
        {listing && !loadError && <span className="ui-pill is-accent"><b className="ui-num">{configured}/{chats.length}</b> 생성 모델 설정됨</span>}
        <button className="button-secondary" onClick={() => setReload(value => value + 1)} disabled={reloadBusy}>
          <RefreshCw size={16} className={loading ? 'mw-spin' : undefined} aria-hidden="true" /> 다시 읽기
        </button>
      </div>
    </section>
    {notice && <div className="mw-notice" role="status"><CheckIcon size={16} aria-hidden="true" /><span>{notice}</span>
      <button className="plain-icon" aria-label="안내 닫기" data-tip="닫기" onClick={() => setNotice('')}><X size={15} /></button></div>}
    {loading && !listing && <div className="mw-state" role="status"><LoaderCircle size={20} className="mw-spin" aria-hidden="true" /> 설정 불러오는 중</div>}
    {loadError && <div className="mw-message is-bad mw-load-error" role="alert">
      <TriangleAlert size={18} aria-hidden="true" /><div><strong>모델 설정을 확인할 수 없습니다</strong><span>{loadError}</span></div>
      <button className="button-secondary" onClick={() => setReload(value => value + 1)} disabled={reloadBusy}>다시 시도</button>
    </div>}
    {listing && <Tabs<Tab> label="연결 종류" value={tab} onChange={setTab} className="mw-tabs"
      items={[{ id: 'chat', label: '생성 모델', badge: chats.length }, { id: 'embed', label: '임베딩 모델', badge: embedding?.models.length ?? 0 },
        { id: 'ocr', label: 'OCR 모델', badge: ocr?.configured ? 1 : 0 }]}>
      {current => current === 'chat'
        ? <div className="mw-gateway-grid" aria-busy={loading}>
          {chats.map(chatCard)}
          {!chats.some(c => c.key === 'secondary') && <button type="button" className="mw-add" disabled={blocked}
            onClick={() => openEditor({ slot: 'secondary', label: '', base_url: '', model_id: '', models: [], api_key_set: false, saved: false })}>
            <Plus size={18} aria-hidden="true" /><span><b>보조 연결 추가</b><small>다른 게이트웨이나 모델을 함께 비교할 때</small></span></button>}
        </div>
        : current === 'embed' ? <div className="mw-gateway-grid">{embedding ? embedCard(embedding) : <div className="mw-state">임베딩 연결 정보를 읽지 못했습니다.</div>}</div>
        : <div className="mw-gateway-grid">{ocr ? ocrCard(ocr) : <div className="mw-state">OCR 모델 연결 정보를 읽지 못했습니다. 서버를 최신 버전으로 다시 시작해 주세요.</div>}</div>}
    </Tabs>}
    {listing && <SetupGuide />}
    {editing && <ConnectionEditor value={editing} onClose={closeEditor}
      onSaved={(next, message) => { applyListing(next, message, editing.slot); closeEditor(); }} />}
  </div>;
}

function ConnectionEditor({ value, onClose, onSaved }: { value: Editing; onClose: () => void; onSaved: (listing: Listing, message: string) => void }) {
  const embed = value.slot === 'embedding';
  const ocr = value.ocr;
  const custom = (key: keyof OcrPrompts) => ocr && ocr[key] !== ocr.defaults[key] ? ocr[key] : '';
  const [draft, setDraft] = useState<Draft>({ label: value.label, base_url: value.base_url, model_id: value.model_id, models: value.models, api_key: '', clear_api_key: false,
    ...(ocr ? { mode: ocr.mode, text_prompt: custom('text_prompt'), table_prompt: custom('table_prompt'), page_prompt: custom('page_prompt') } : {}) });
  const [modelInput, setModelInput] = useState('');
  const [promptsOpen] = useState(() => !!ocr && (Object.keys(OCR_DEFAULTS) as (keyof OcrPrompts)[]).some(key => !!custom(key)));
  const [check, setCheck] = useState<Outcome | null>(null);
  const [listed, setListed] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState<'' | 'test' | 'list' | 'save' | 'forget'>('');
  const [error, setError] = useState('');
  const urlRef = useRef<HTMLInputElement>(null);
  const uid = useId();
  const set = (patch: Partial<Draft>) => { setDraft(prev => ({ ...prev, ...patch })); setCheck(null); setError(''); };
  const addModel = (id: string) => { const clean = id.trim(); if (clean && !draft.models.includes(clean)) set({ models: [...draft.models, clean] }); setModelInput(''); };
  const toggleModel = (id: string) => embed ? set({ models: draft.models.includes(id) ? draft.models.filter(m => m !== id) : [...draft.models, id] }) : set({ model_id: id });
  const canCheck = !!draft.base_url.trim() && (embed ? draft.models.length > 0 : !!draft.model_id.trim());

  const test = async () => { setBusy('test'); setCheck({ ...(await runCheck('/api/models/draft/test', draftBody(value.slot, draft))), checkedAt: new Date() }); setBusy(''); };
  const list = async () => { setBusy('list'); setListed({ ...(await runCheck('/api/models/draft/models', draftBody(value.slot, draft))), checkedAt: new Date() }); setBusy(''); };
  const save = async () => {
    setBusy('save'); setError('');
    try { onSaved(await saveConnection(value.slot, draft), `${draft.label || SLOT_NAME[value.slot]} 설정을 저장했습니다. 다음 요청부터 바로 씁니다.`); }
    catch (exc) { setError(exc instanceof Error ? exc.message : '저장하지 못했습니다.'); setBusy(''); }
  };
  const forget = async () => {
    setBusy('forget'); setError('');
    try { onSaved(await forgetConnection(value.slot), '화면에서 저장한 값을 지우고 .env 값으로 되돌렸습니다.'); }
    catch (exc) { setError(exc instanceof Error ? exc.message : '되돌리지 못했습니다.'); setBusy(''); }
  };

  const mode: OcrMode = draft.mode === 'page' ? 'page' : 'region';
  return <Modal open onClose={onClose} size="md" initialFocus={urlRef} title={embed ? '임베딩 연결 설정' : ocr ? 'OCR 모델 연결 설정' : `${SLOT_NAME[value.slot]} 설정`}
    subtitle="저장하면 바로 적용됩니다. API 키를 비워 두면 저장된 키를 그대로 둡니다."
    footer={<>
      {value.saved && <button type="button" className="button-quiet mw-forget" disabled={!!busy} onClick={() => void forget()}
        data-tip="화면에서 저장한 값을 지우고 서버의 .env 값을 씁니다."><RotateCcw size={14} aria-hidden="true" />.env 값으로 되돌리기</button>}
      <button type="button" className="button-secondary" disabled={!canCheck || !!busy} onClick={() => void test()}>
        {busy === 'test' ? <LoaderCircle size={15} className="mw-spin" aria-hidden="true" /> : <PlugZap size={15} aria-hidden="true" />}저장 전 확인</button>
      <button type="button" className="button-quiet" onClick={onClose}>취소</button>
      <button type="button" className="button-primary" disabled={!!busy} onClick={() => void save()}>{busy === 'save' ? '저장 중' : '저장'}</button>
    </>}>
    <form className="mw-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <label><span>이름</span><input value={draft.label} maxLength={40} placeholder={SLOT_NAME[value.slot]} onChange={event => set({ label: event.target.value })} /></label>
      <div className="mw-field"><label htmlFor={`${uid}-url`}>Base URL</label><input id={`${uid}-url`} ref={urlRef} value={draft.base_url} inputMode="url" spellCheck={false}
        placeholder="http://게이트웨이-주소:8000/v1" aria-describedby={`${uid}-url-hint`} onChange={event => set({ base_url: event.target.value })} />
        <small id={`${uid}-url-hint`}>OpenAI 호환 주소입니다. 보통 <code>/v1</code>까지 넣습니다.</small></div>
      {embed ? <div className="mw-field">
        <span id={`${uid}-models`}>모델 ID</span>
        <div className="mw-tags" role="group" aria-labelledby={`${uid}-models`}>
          {draft.models.map(id => <span className="mw-tag" key={id}><code>{id}</code>
            <button type="button" aria-label={`${id} 빼기`} data-tip="빼기" onClick={() => set({ models: draft.models.filter(m => m !== id) })}><X size={12} /></button></span>)}
          <input value={modelInput} aria-label="추가할 모델 ID" placeholder={draft.models.length ? '모델 추가' : '예: BAAI/bge-m3'} spellCheck={false}
            onChange={event => setModelInput(event.target.value.replace(',', ''))}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ',') { event.preventDefault(); addModel(modelInput); } else if (event.key === 'Backspace' && !modelInput && draft.models.length) set({ models: draft.models.slice(0, -1) }); }}
            onBlur={() => addModel(modelInput)} />
        </div>
        <small>Enter로 추가합니다. 첫 번째 모델이 의미 기반 청킹의 기본 모델이 됩니다.</small>
      </div> : <label><span>모델 ID</span><input value={draft.model_id} spellCheck={false} placeholder={ocr ? '예: PaddleOCR-VL-1.5' : '예: granite-3-8b-instruct'} onChange={event => set({ model_id: event.target.value })} /></label>}
      {ocr && <fieldset className="mw-modes">
        <legend>OCR 방식</legend>
        {(['region', 'page'] as const).map(id => <label key={id} className="mw-mode">
          <input type="radio" name={`${uid}-mode`} value={id} checked={mode === id} onChange={() => set({ mode: id })} />
          <span><b>{OCR_MODES[id].name}</b><small>({OCR_MODES[id].detail})</small></span></label>)}
      </fieldset>}
      {ocr && <details className="mw-prompts" open={promptsOpen}>
        <summary>지시문 (선택 · 비워 두면 기본값)</summary>
        {OCR_PROMPTS[mode].map(({ key, label }) => <label key={key}><span>{label}</span>
          <input value={draft[key] ?? ''} spellCheck={false} maxLength={500} placeholder={ocr.defaults[key]} onChange={event => set({ [key]: event.target.value } as Partial<Draft>)} /></label>)}
        <small>{mode === 'region' ? '영역 방식은 글자 영역과 표 영역에 다른 지시문을 씁니다.' : '쪽 방식은 쪽 전체에 지시문 하나를 씁니다.'} 모델 설명서의 지시문을 그대로 넣으세요.</small>
      </details>}
      <div className="mw-pick">
        <button type="button" className="button-quiet" disabled={!draft.base_url.trim() || !!busy} onClick={() => void list()}>
          {busy === 'list' ? <LoaderCircle size={15} className="mw-spin" aria-hidden="true" /> : <ListTree size={15} aria-hidden="true" />}게이트웨이 모델 목록 불러오기</button>
        {listed && (listed.ok ? (listed.models?.length ? <ul className="mw-pick-list" aria-label="불러온 모델">
          {listed.models.map(id => { const on = embed ? draft.models.includes(id) : draft.model_id === id; return <li key={id}>
            <button type="button" aria-pressed={on} onClick={() => toggleModel(id)}>{on ? <CheckIcon size={14} aria-hidden="true" /> : <Plus size={14} aria-hidden="true" />}<code>{id}</code></button></li>; })}
        </ul> : <p className="mw-list-empty">게이트웨이가 모델 ID를 반환하지 않았습니다. 직접 입력하세요.</p>) : <RequestError result={listed} kind="list" />)}
      </div>
      <label><span>API 키</span><input type="password" autoComplete="new-password" value={draft.api_key} disabled={draft.clear_api_key} spellCheck={false}
        placeholder={value.api_key_set ? '저장된 키 유지 · 바꿀 때만 입력' : '필요한 게이트웨이만 입력'} onChange={event => set({ api_key: event.target.value })} /></label>
      {value.api_key_set && <label className="mw-check"><input type="checkbox" checked={draft.clear_api_key} onChange={event => set({ clear_api_key: event.target.checked, api_key: '' })} />저장된 키 지우기</label>}
      <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
    </form>
    {check && (check.ok ? <div className="mw-message is-ok mw-inline" role="status"><CircleCheck size={17} aria-hidden="true" /><div>
      <strong>{embed ? '임베딩 확인' : ocr ? 'OCR 확인' : '모델 응답 확인'} <b className="ui-num">{check.latency_ms.toLocaleString('ko-KR')} ms</b></strong>
      <span><code>{check.model}</code>{check.dims ? <> · {check.dims.toLocaleString('ko-KR')}차원</> : check.reply ? <> · {check.reply}</> : null}</span></div></div>
      : <div className="mw-inline"><RequestError result={check} kind="test" /></div>)}
    {error && <p className="mw-form-error" role="alert"><TriangleAlert size={15} aria-hidden="true" />{error}</p>}
  </Modal>;
}
