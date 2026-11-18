import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VectorDbWorkspace from '../VectorDbWorkspace';
import { memoryStorage } from './flowTestEnv';

/* 합성 데이터: 문서 2개, 청크 3개, 4차원 벡터 */
const FIELDS = [
  { name: 'id', type: 'VARCHAR', element_type: null, dim: null, max_length: 64, max_capacity: null, primary_key: true, auto_id: false, nullable: false, partition_key: false, description: '', is_vector: false, index_type: null },
  { name: 'text', type: 'VARCHAR', element_type: null, dim: null, max_length: 4000, max_capacity: null, primary_key: false, auto_id: false, nullable: false, partition_key: false, description: '청크 본문', is_vector: false, index_type: null },
  { name: 'doc_id', type: 'VARCHAR', element_type: null, dim: null, max_length: 128, max_capacity: null, primary_key: false, auto_id: false, nullable: false, partition_key: false, description: '', is_vector: false, index_type: null },
  { name: 'chunk_index', type: 'INT64', element_type: null, dim: null, max_length: null, max_capacity: null, primary_key: false, auto_id: false, nullable: false, partition_key: false, description: '', is_vector: false, index_type: null },
  { name: 'embedding', type: 'FLOAT_VECTOR', element_type: null, dim: 4, max_length: null, max_capacity: null, primary_key: false, auto_id: false, nullable: false, partition_key: false, description: '', is_vector: true, index_type: 'HNSW' },
];
const DETECTED = { pk: 'id', text: 'text', doc: 'doc_id', order: 'chunk_index', source: null, page: null, vector: 'embedding' };
const VECTOR = { kind: 'dense', type: 'FloatVector', dim: 4, norm: 1, min: -0.5, max: 0.5, mean: 0, head: [0.5, -0.5, 0.5, -0.5] };
const ROWS = [
  { pk: 'c1', text: '알파 문단 시작. 겹침구간', fields: { id: 'c1', doc_id: 'DOC-A', chunk_index: 0 }, vector: VECTOR, partition: '_default' },
  { pk: 'c2', text: '겹침구간 이어지는 베타 문단.', fields: { id: 'c2', doc_id: 'DOC-A', chunk_index: 1 }, vector: VECTOR, partition: '_default' },
  { pk: 'c3', text: '감마 문서의 단독 청크.', fields: { id: 'c3', doc_id: 'DOC-B', chunk_index: 0 }, vector: VECTOR, partition: '_default' },
];
const PARTITIONS = [{ name: '_default', row_count: 3, error: null }];

const RESPONSES: Record<string, (body: Record<string, unknown>) => unknown> = {
  'GET /api/vectordb/sources': () => ({
    default: 'example', max_window: 16384,
    sources: [{ key: 'example', label: '예시 데이터', available: true }, { key: 'milvus', label: 'Milvus 연결', available: false }],
    milvus: { configured: false, uri: '', db: 'default', token_set: false, ca_bundle_set: false, timeout: 10 },
  }),
  'GET /api/vectordb/example/tree': () => ({
    source: 'example', warnings: [], totals: { databases: 1, collections: 1, partitions: 1, rows: 3 },
    databases: [{ name: 'default', error: null, collections: [{ name: 'demo_chunks', row_count: 3, dim: 4, vector_field: 'embedding', vector_fields: 1, metric: 'COSINE', load_state: 'LoadStateLoaded', partitions: PARTITIONS, error: null }] }],
  }),
  'GET /api/vectordb/example/collection': () => ({
    db: 'default', name: 'demo_chunks', description: '합성 예시 컬렉션', row_count: 3, load_state: 'LoadStateLoaded', load_progress: 100, consistency_level: 'Bounded',
    shards: 1, partitions_num: 1, auto_id: false, enable_dynamic_field: false, aliases: [], properties: [{ key: 'embedding.model', value: 'demo-embed-small' }],
    fields: FIELDS, partitions: PARTITIONS, detected: DETECTED, warnings: [],
    vector_fields: [{ name: 'embedding', type: 'FloatVector', dim: 4, description: '', index_name: 'embedding_idx', index_type: 'HNSW', metric: 'COSINE', index_params: { M: 16, efConstruction: 200 }, index_state: 'Finished', indexed_rows: 3, total_rows: 3, pending_rows: 0, fail_reason: null }],
    embedding: { model: 'demo-embed-small', recorded_in: '컬렉션 속성', dim: 4, recorded_dim: 4, dim_mismatch: false },
  }),
  'POST /api/vectordb/example/browse': () => ({
    rows: ROWS, total: 3, total_basis: 'count', effective_filter: 'id != ""', user_filter: '', text_field: 'text', output_fields: ['id', 'doc_id', 'chunk_index'],
    limit: 20, offset: 0, partition: null, max_window: 16384,
  }),
  'POST /api/vectordb/example/chunk': body => ({ ...ROWS.find(r => r.pk === body.pk), text_field: 'text', detected: DETECTED }),
  'POST /api/vectordb/example/similar': body => ({
    pk: body.pk, metric: 'COSINE', higher_is_closer: true, vector_field: 'embedding', doc_field: 'doc_id', doc: 'DOC-A', text_field: 'text',
    hits: ROWS.filter(r => r.pk !== body.pk).map((r, i) => ({ rank: i + 1, pk: r.pk, score: 0.9 - i * 0.1, text: r.text, doc: r.fields.doc_id, order: r.fields.chunk_index, page: null, same_document: r.fields.doc_id === 'DOC-A' })),
  }),
  'POST /api/vectordb/example/documents': () => ({ doc_field: 'doc_id', values: [{ value: 'DOC-A', count: 2 }, { value: 'DOC-B', count: 1 }], scanned: 3, truncated: false }),
  'POST /api/vectordb/example/document': () => ({
    doc_field: 'doc_id', value: 'DOC-A', order_field: 'chunk_index', ordered_by: 'chunk_index', text_field: 'text', total: 2, truncated: false, overlaps: 1, overlap_avg: 4,
    chunks: [
      { index: 0, pk: 'c1', order: 0, page: null, text: ROWS[0].text, head_skip: 0, overlap: 0, tail: [10, 14] },
      { index: 1, pk: 'c2', order: 1, page: null, text: ROWS[1].text, head_skip: 4, overlap: 4, tail: null },
    ],
  }),
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  memoryStorage();
  fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const path = String(input).split('?')[0];
    const handler = RESPONSES[`${method} ${path}`];
    if (!handler) return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) };
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
    return { ok: true, status: 200, json: async () => handler(body) };
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const calls = (path: string) => fetchMock.mock.calls.filter(([url]) => String(url).startsWith(path)).length;
const lastBrowse = () => JSON.parse(String(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/browse')).pop()![1].body)) as Record<string, unknown>;
/** 컬렉션 탭으로 가서 청크 표가 뜰 때까지 기다린다. */
const openCollections = async (user: ReturnType<typeof userEvent.setup>) => {
  render(<VectorDbWorkspace active />);
  await user.click(await screen.findByRole('tab', { name: '컬렉션' }));
  await screen.findByRole('button', { name: '청크 c2 열기' });
};

describe('벡터 DB 화면', () => {
  it('보이기 전에는 불러오지 않고, 처음에는 개요 탭을 예시 데이터로 연다', async () => {
    const { rerender } = render(<VectorDbWorkspace active={false} />);
    expect(fetchMock).not.toHaveBeenCalled();
    rerender(<VectorDbWorkspace active />);
    expect(await screen.findByRole('heading', { name: 'demo_chunks' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: '개요' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText('예시 데이터')).toBeTruthy();
    expect(screen.getByText('Milvus 미연결')).toBeTruthy();
    expect(screen.queryByRole('group', { name: '데이터 출처' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(calls('/api/vectordb/example/tree')).toBe(1);
    expect(calls('/api/vectordb/milvus')).toBe(0);
  });

  it('컬렉션 탭은 트리와 청크 표를 보여 주고 선택을 기억한다', async () => {
    const user = userEvent.setup();
    await openCollections(user);
    expect(localStorage.getItem('vdb.page')).toBe('"collections"');
    expect(screen.getByRole('heading', { name: 'demo_chunks' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: '청크' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('button', { name: /조건·필드/ }).getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getAllByRole('row')).toHaveLength(4);
    cleanup();
    render(<VectorDbWorkspace active />);
    expect((await screen.findByRole('tab', { name: '컬렉션' })).getAttribute('aria-selected')).toBe('true');
  });

  it('청크 줄에 올리면 같은 문서 줄만 강조하고 나머지는 흐리게 한다', async () => {
    const user = userEvent.setup();
    await openCollections(user);
    const row = (pk: string) => screen.getByRole('button', { name: `청크 ${pk} 열기` }).closest('tr')!;
    await user.hover(row('c1'));
    expect(row('c1').closest('table')?.className).toContain('is-dimmed');
    expect(row('c2').className).toContain('is-lit');
    expect(row('c3').className).not.toContain('is-lit');
    await user.unhover(row('c1'));
    expect(row('c1').closest('table')?.className).not.toContain('is-dimmed');
  });

  it('컬렉션 탭에서 청크를 열면 팝업에 전체 텍스트와 비슷한 청크가 보이고, Escape로 닫으면 연 자리로 돌아간다', async () => {
    const user = userEvent.setup();
    await openCollections(user);
    const opener = screen.getByRole('button', { name: '청크 c2 열기' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: '청크 c2' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(await within(dialog).findByText('겹침구간 이어지는 베타 문단.', { selector: '.vdb-fulltext' })).toBeTruthy();
    expect(await within(dialog).findByText(/같은 문서 1개/)).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('문서로 다시 읽기는 팝업 안에서 청크를 순서대로 이어 보여 주고, 이전 보기로 돌아간다', async () => {
    const user = userEvent.setup();
    await openCollections(user);
    await user.click(screen.getByRole('button', { name: '청크 c1 열기' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', { name: /이 문서 다시 읽기/ }));
    const article = await within(dialog).findByRole('article', { name: 'DOC-A 본문' });
    const text = article.textContent ?? '';
    expect(text.indexOf('알파')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('알파')).toBeLessThan(text.indexOf('베타'));
    expect(text.split('겹침구간').length - 1).toBe(1);
    expect(within(article).getAllByRole('button').map(b => b.getAttribute('aria-label'))).toEqual(['청크 1 열기', '청크 2 열기']);
    await user.click(within(dialog).getByRole('button', { name: '이전 보기' }));
    expect(await within(screen.getByRole('dialog')).findByText('알파 문단 시작. 겹침구간', { selector: '.vdb-fulltext' })).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('스키마·인덱스 탭은 벡터 필드와 인덱스를 보여 주고 탭 선택을 기억한다', async () => {
    const user = userEvent.setup();
    await openCollections(user);
    await user.click(screen.getByRole('tab', { name: '스키마·인덱스' }));
    const tabpanel = screen.getByRole('tabpanel', { name: '스키마·인덱스' });
    expect(within(tabpanel).getAllByText('embedding').length).toBeGreaterThan(0);
    expect(within(tabpanel).getAllByText('HNSW').length).toBeGreaterThan(0);
    expect(within(tabpanel).getByText('4d')).toBeTruthy();
    expect(within(tabpanel).getByText('efConstruction', { exact: false })).toBeTruthy();
    expect(within(tabpanel).getByText('demo-embed-small')).toBeTruthy();
    expect(within(tabpanel).getByRole('button', { name: /설명·속성/ }).getAttribute('aria-expanded')).toBe('false');
    expect(localStorage.getItem('vdb.tab')).toBe('"schema"');
  });
});

/* 개요: 파티션 4개(큰 것 2, 작은 것 1, 빈 것 1) + 다른 컬렉션 1개 + 컬렉션 없는 데이터베이스 */
const MAP_PARTS = [
  { name: '_default', row_count: 6, error: null },
  { name: 'qc', row_count: 14, error: null },
  { name: 'equipment', row_count: 10, error: null },
  { name: 'staging', row_count: 0, error: null },
];
const MAP_TREE = {
  source: 'example', warnings: [], totals: { databases: 2, collections: 2, partitions: 5, rows: 38 },
  databases: [
    { name: 'default', error: null, collections: [
      { name: 'demo_chunks', row_count: 30, dim: 4, vector_field: 'embedding', vector_fields: 1, metric: 'COSINE', load_state: 'LoadStateLoaded', partitions: MAP_PARTS, error: null },
      { name: 'legacy_chunks', row_count: 8, dim: 768, vector_field: 'embedding', vector_fields: 1, metric: 'L2', load_state: 'LoadStateNotLoad', partitions: [{ name: 'archive', row_count: 8, error: null }], error: null },
    ] },
    { name: 'sandbox', error: null, collections: [] },
  ],
};

describe('벡터 DB 개요와 파티션 팝업', () => {
  const saved = { tree: RESPONSES['GET /api/vectordb/example/tree'], coll: RESPONSES['GET /api/vectordb/example/collection'] };
  beforeEach(() => {
    RESPONSES['GET /api/vectordb/example/tree'] = () => MAP_TREE;
    RESPONSES['GET /api/vectordb/example/collection'] = () => ({ ...(saved.coll({}) as Record<string, unknown>), row_count: 30, partitions: MAP_PARTS, partitions_num: 4 });
  });
  afterEach(() => { RESPONSES['GET /api/vectordb/example/tree'] = saved.tree; RESPONSES['GET /api/vectordb/example/collection'] = saved.coll; });

  const openOverview = async () => {
    render(<VectorDbWorkspace active />);
    return screen.findByRole('list', { name: 'demo_chunks 파티션' });
  };
  const tile = (name: RegExp) => screen.getByRole('button', { name });

  it('컬렉션마다 머리줄과 같은 크기의 파티션 타일을 청크가 많은 순서로 놓고, 빈 파티션은 끝에 흐리게 둔다', async () => {
    const tiles = await openOverview();
    const items = within(tiles).getAllByRole('listitem');
    expect(items.map(item => item.textContent?.replace(/\d+/g, ''))).toEqual(['qc', 'equipment', '_default', 'staging']);
    expect(within(items[0]).getByText('14')).toBeTruthy();
    expect(within(items[3]).queryByRole('button')).toBeNull();
    expect(items[3].firstElementChild?.className).toContain('is-muted');
    const head = screen.getByRole('heading', { name: 'legacy_chunks' }).closest('header')!;
    expect(head.textContent).toContain('768차원 · L2');
    expect(within(head).getByText('로드 안 됨').className).toContain('ui-pill');
    expect(screen.getByText('sandbox · 컬렉션 없음')).toBeTruthy();
  });

  it('타일에 올리면 타일에 없는 비율만 띄운다', async () => {
    const user = userEvent.setup();
    await openOverview();
    await user.hover(tile(/^qc,/));
    const tip = screen.getByRole('tooltip').textContent ?? '';
    expect(tip).toContain('컬렉션 청크의 47%');
    expect(tip).not.toContain('qc');
    expect(tip).not.toContain('14');
  });

  it('타일을 누르면 파티션 팝업이 청크 목록과 첫 청크 상세를 보여 주고, 다른 청크를 고르면 상세가 바뀐다', async () => {
    const user = userEvent.setup();
    await openOverview();
    await user.click(tile(/^qc,/));
    const dialog = await screen.findByRole('dialog', { name: 'qc' });
    expect(within(dialog).getByText('demo_chunks · 청크 14개')).toBeTruthy();
    expect(within(dialog).getByRole('tab', { name: '청크' }).getAttribute('aria-selected')).toBe('true');
    const list = await within(dialog).findByRole('listbox', { name: '청크 목록' });
    expect(lastBrowse().partition).toBe('qc');
    expect(within(list).getAllByRole('option')).toHaveLength(3);
    expect(within(list).getAllByRole('option')[0].getAttribute('aria-selected')).toBe('true');
    expect(await within(dialog).findByText('알파 문단 시작. 겹침구간', { selector: '.vdb-fulltext' })).toBeTruthy();
    await user.click(within(list).getByText('감마 문서의 단독 청크.'));
    expect(await within(dialog).findByText('감마 문서의 단독 청크.', { selector: '.vdb-fulltext' })).toBeTruthy();
  });

  it('문서별 탭은 이 파티션의 문서 목록과 고른 문서를 순서대로 다시 읽은 본문을 보여 준다', async () => {
    const user = userEvent.setup();
    await openOverview();
    await user.click(tile(/^qc,/));
    const dialog = await screen.findByRole('dialog', { name: 'qc' });
    await user.click(within(dialog).getByRole('tab', { name: '문서별' }));
    const docs = await within(dialog).findByRole('listbox', { name: '문서 목록' });
    expect(within(docs).getAllByRole('option').map(o => o.textContent)).toEqual(['DOC-A2', 'DOC-B1']);
    expect(lastBrowse().output_fields).toEqual(['doc_id']);
    const article = await within(dialog).findByRole('article', { name: 'DOC-A 본문' });
    expect((article.textContent ?? '').split('겹침구간').length - 1).toBe(1);
    await user.click(within(article).getByRole('button', { name: '청크 2 열기' }));
    expect(within(dialog).getByRole('tab', { name: '청크' }).getAttribute('aria-selected')).toBe('true');
    expect(await within(dialog).findByText('겹침구간 이어지는 베타 문단.', { selector: '.vdb-fulltext' })).toBeTruthy();
  });

  it('Escape로 팝업을 닫으면 누른 타일로 초점이 돌아온다', async () => {
    const user = userEvent.setup();
    await openOverview();
    await user.click(tile(/^qc,/));
    await screen.findByRole('dialog', { name: 'qc' });
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(tile(/^qc,/));
  });

  it('파티션이 8개를 넘으면 7개와 "n개 더" 타일을 두고, 목록 팝업에서 고르면 그 파티션을 연다', async () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ name: `p${i}`, row_count: 10 - i, error: null }));
    RESPONSES['GET /api/vectordb/example/tree'] = () => ({ ...MAP_TREE, databases: [{ name: 'default', error: null, collections: [{ ...MAP_TREE.databases[0].collections[0], row_count: 55, partitions: many }] }] });
    const user = userEvent.setup();
    const tiles = await openOverview();
    expect(within(tiles).getAllByRole('listitem')).toHaveLength(8);
    await user.click(within(tiles).getByRole('button', { name: '파티션 3개 더 보기' }));
    const more = await screen.findByRole('dialog', { name: 'demo_chunks 파티션' });
    await user.click(within(more).getByRole('button', { name: /^p8/ }));
    expect(await screen.findByRole('dialog', { name: 'p8' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'demo_chunks 파티션' })).toBeNull();
  });
});

describe('Milvus가 연결되지 않았을 때', () => {
  const configured = {
    default: 'milvus', max_window: 16384,
    sources: [{ key: 'example', label: '예시 데이터', available: true }, { key: 'milvus', label: 'Milvus 연결', available: true }],
    milvus: { configured: true, uri: 'http://milvus.local:19530', db: 'default', token_set: false, ca_bundle_set: false, timeout: 10, unreachable: null },
  };
  const useMilvusDown = (sources: unknown) => {
    const base = fetchMock.getMockImplementation() as (input: string, init?: RequestInit) => Promise<unknown>;
    fetchMock.mockImplementation(async (input: string, init?: RequestInit) => {
      const path = String(input).split('?')[0];
      if (path === '/api/vectordb/sources') return { ok: true, status: 200, json: async () => sources };
      if (path === '/api/vectordb/milvus/tree') return { ok: false, status: 502, json: async () => ({ detail: 'Milvus HTTP 404: 404 page not found' }) };
      return base(input, init);
    });
  };

  it('자동으로 연 Milvus가 실패하면 한 번만 시도하고 예시 데이터로 연다', async () => {
    useMilvusDown(configured);
    render(<VectorDbWorkspace active />);
    expect(await screen.findByRole('heading', { name: 'demo_chunks' })).toBeTruthy();
    expect(screen.getByText('예시 데이터 · Milvus 연결 실패')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(calls('/api/vectordb/milvus/tree')).toBe(1);
    expect(calls('/api/vectordb/example/tree')).toBe(1);
  });

  it('최근 연결 실패로 서버가 쉬는 중이면 Milvus를 부르지 않고 예시 데이터로 연다', async () => {
    useMilvusDown({ ...configured, default: 'example', milvus: { ...configured.milvus, unreachable: { retry_in: 20, error: 'Milvus HTTP 404: 404 page not found' } } });
    render(<VectorDbWorkspace active />);
    expect(await screen.findByRole('heading', { name: 'demo_chunks' })).toBeTruthy();
    expect(screen.getByText('예시 데이터 · Milvus 연결 실패')).toBeTruthy();
    expect(calls('/api/vectordb/milvus')).toBe(0);
  });

  it('사용자가 Milvus를 직접 고른 경우에는 예시로 바꾸지 않고 오류와 다시 시도를 보여 준다', async () => {
    useMilvusDown({ ...configured, default: 'example' });
    const user = userEvent.setup();
    render(<VectorDbWorkspace active />);
    await screen.findByRole('heading', { name: 'demo_chunks' });
    await user.click(screen.getByRole('button', { name: 'Milvus 연결' }));
    expect((await screen.findByRole('alert')).textContent).toContain('404');
    expect(calls('/api/vectordb/milvus/tree')).toBe(1);
  });
});
