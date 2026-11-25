import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { EyeOff, ImageOff, StickyNote } from 'lucide-react';
import { EMU_PER_PT, readPptx } from './pptx';
import type { Box, Deck, Para, Shape, TextBody } from './pptx';
import './officeSource.css';

/**
 * 원문 대조의 Office 원본 보기. 파일을 브라우저 안에서만 다시 그린다(서버·외부로 보내지 않음).
 * Word·PowerPoint와 글꼴·줄바꿈·쪽 나눔이 다를 수 있어 화면에 '브라우저 재현'이라고 밝힌다.
 */
export default function OfficeSource({ kind, data, expanded }: { kind: 'docx' | 'pptx'; data: ArrayBuffer; expanded: boolean }) {
  return <div className={`office-source${expanded ? ' is-expanded' : ''}`}>
    <p className="office-note">브라우저에서 다시 그린 원본입니다. {kind === 'docx' ? 'Word' : 'PowerPoint'}와 글꼴·줄바꿈·{kind === 'docx' ? '쪽 나눔' : '도형 효과'}이 다를 수 있으니, 정확한 배치는 원본 다운로드로 확인하세요.</p>
    {kind === 'docx' ? <DocxSource data={data} /> : <PptxSource data={data} />}
  </div>;
}

// ---------------------------------------------------------------- DOCX (docx-preview)

/** 문서에서 온 링크는 http(s)·mailto·문서 안 책갈피만 남긴다(javascript: 등 제거). */
export function sanitizeLinks(root: HTMLElement) {
  for (const anchor of Array.from(root.querySelectorAll('a[href]'))) {
    const href = anchor.getAttribute('href') ?? '';
    if (href.startsWith('#')) continue;
    if (/^(https?:|mailto:)/i.test(href)) { anchor.setAttribute('target', '_blank'); anchor.setAttribute('rel', 'noopener noreferrer'); }
    else anchor.removeAttribute('href');
  }
}

function DocxSource({ data }: { data: ArrayBuffer }) {
  const host = useRef<HTMLDivElement>(null);
  const styles = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ ready: boolean; error?: string }>({ ready: false });
  useEffect(() => {
    let alive = true;
    const body = host.current, style = styles.current;
    if (!body || !style) return;
    setState({ ready: false });
    import('docx-preview').then(({ renderAsync }) => renderAsync(data, body, style, {
      className: 'docx', inWrapper: true, breakPages: true, ignoreLastRenderedPageBreak: true, useBase64URL: true,
      // 문서 안 HTML 조각(altChunk)은 같은 출처의 iframe에 들어가 스크립트가 돌 수 있어 그리지 않는다.
      renderAltChunks: false, renderComments: false, renderChanges: false, experimental: false,
    })).then(() => {
      if (!alive) return;
      sanitizeLinks(body);
      setState({ ready: true });
    }).catch(() => { if (alive) setState({ ready: false, error: 'Word 원본을 그리지 못했어요. 원본 다운로드로 확인하세요.' }); });
    return () => { alive = false; };
  }, [data]);
  // 쪽 폭(A4 약 794px)이 칸보다 넓으면 줄여서 맞춘다.
  useEffect(() => {
    const body = host.current;
    if (!state.ready || !body || typeof ResizeObserver === 'undefined') return;
    const fit = () => {
      const page = body.querySelector<HTMLElement>('section.docx');
      if (!page) return;
      body.style.zoom = '1';
      const scale = Math.min(1, (body.clientWidth - 16) / (page.offsetWidth + 32));
      body.style.zoom = scale > 0 ? String(scale) : '1';
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(body.parentElement ?? body);
    return () => observer.disconnect();
  }, [state.ready]);
  return <div className="docx-source">
    {!state.ready && !state.error && <p className="office-status" role="status">Word 원본을 그리는 중…</p>}
    {state.error && <p className="office-status is-error" role="alert">{state.error}</p>}
    <div ref={styles} hidden />
    <div ref={host} className="docx-host" aria-label="Word 원본" />
  </div>;
}

// ---------------------------------------------------------------- PPTX (자체 렌더러)

function toUrl(bytes: Uint8Array, mime: string) {
  return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(new Blob([bytes as BlobPart], { type: mime })) : '';
}

function PptxSource({ data }: { data: ArrayBuffer }) {
  const [deck, setDeck] = useState<Deck>();
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    let loaded: Deck | undefined;
    setDeck(undefined); setError('');
    readPptx(data, toUrl).then(result => { loaded = result; if (alive) setDeck(result); else result.urls.forEach(url => URL.revokeObjectURL?.(url)); })
      .catch(() => { if (alive) setError('PowerPoint 원본을 그리지 못했어요. 원본 다운로드로 확인하세요.'); });
    return () => { alive = false; loaded?.urls.forEach(url => URL.revokeObjectURL?.(url)); };
  }, [data]);
  if (error) return <p className="office-status is-error" role="alert">{error}</p>;
  if (!deck) return <p className="office-status" role="status">슬라이드를 그리는 중…</p>;
  const hidden = deck.slides.filter(slide => slide.hidden).length;
  return <div className="pptx-source">
    <p className="pptx-count">슬라이드 {deck.slides.length}장{hidden ? ` · 숨긴 슬라이드 ${hidden}장` : ''}</p>
    {deck.slides.map(slide => <figure key={slide.number} className={`pptx-slide${slide.hidden ? ' is-hidden' : ''}`} aria-label={`슬라이드 ${slide.number}`}>
      <figcaption><strong>슬라이드 {slide.number}</strong>{slide.hidden && <span className="pptx-flag"><EyeOff size={12} aria-hidden="true" />숨긴 슬라이드</span>}{slide.layout && <small>{slide.layout}</small>}</figcaption>
      <Stage deck={deck} slide={slide} />
      {slide.notes && <details className="pptx-notes"><summary><StickyNote size={13} aria-hidden="true" />발표자 메모</summary><p>{slide.notes}</p></details>}
    </figure>)}
  </div>;
}

function Stage({ deck, slide }: { deck: Deck; slide: Deck['slides'][number] }) {
  const widthPt = deck.width / EMU_PER_PT;
  const style: CSSProperties = {
    aspectRatio: `${deck.width} / ${deck.height}`, background: slide.background ?? '#ffffff',
    ...(slide.backgroundImage ? { backgroundImage: `url("${slide.backgroundImage}")`, backgroundSize: 'cover', backgroundPosition: 'center' } : {}),
  };
  const shapes = useMemo(() => slide.shapes.map((shape, index) => <ShapeView key={index} shape={shape} deck={deck} widthPt={widthPt} />), [slide, deck, widthPt]);
  return <div className="pptx-stage" style={style}>{shapes}</div>;
}

const pct = (value: number, total: number) => `${(value / total * 100).toFixed(4)}%`;
const cqw = (pt: number, widthPt: number) => `${(pt / widthPt * 100).toFixed(4)}cqw`;

function place(box: Box, deck: Deck, flip = false): CSSProperties {
  const transforms = [box.rot ? `rotate(${box.rot}deg)` : '', flip && box.flipH ? 'scaleX(-1)' : '', flip && box.flipV ? 'scaleY(-1)' : ''].filter(Boolean);
  return { left: pct(box.x, deck.width), top: pct(box.y, deck.height), width: pct(box.w, deck.width), height: pct(box.h, deck.height),
    transform: transforms.length ? transforms.join(' ') : undefined };
}

function Paragraphs({ body, widthPt }: { body: TextBody; widthPt: number }) {
  return <>{body.paras.map((para: Para, index) => {
    const empty = !para.runs.some(run => run.text.length);
    return <p key={index} style={{
      textAlign: para.align, paddingLeft: cqw(para.marginLeft / EMU_PER_PT, widthPt), textIndent: cqw(para.indent / EMU_PER_PT, widthPt),
      fontSize: cqw(para.size, widthPt),
    }}>
      {para.bullet && <span className="pptx-bullet">{para.bullet}{' '}</span>}
      {empty ? ' ' : para.runs.map((run, r) => <span key={r} style={{
        fontSize: cqw(run.baseline ? run.size * 0.7 : run.size, widthPt), fontWeight: run.bold ? 700 : undefined, fontStyle: run.italic ? 'italic' : undefined,
        textDecoration: [run.underline ? 'underline' : '', run.strike ? 'line-through' : ''].filter(Boolean).join(' ') || undefined,
        color: run.color, fontFamily: run.font ? `"${run.font}", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif` : undefined,
        verticalAlign: run.baseline ? (run.baseline > 0 ? 'super' : 'sub') : undefined,
      }}>{run.text}</span>)}
    </p>;
  })}</>;
}

function TextFrame({ body, deck, widthPt }: { body: TextBody; deck: Deck; widthPt: number }) {
  const [l, t, r, b] = body.inset;
  return <div className={`pptx-text is-${body.anchor}${body.vertical ? ' is-vertical' : ''}`}
    style={{ padding: `${pct(t, deck.width)} ${pct(r, deck.width)} ${pct(b, deck.width)} ${pct(l, deck.width)}` }}>
    <div><Paragraphs body={body} widthPt={widthPt} /></div>
  </div>;
}

function ShapeView({ shape, deck, widthPt }: { shape: Shape; deck: Deck; widthPt: number }): ReactNode {
  if (shape.kind === 'picture') {
    const [l, t, r, b] = shape.crop ?? [0, 0, 0, 0];
    const w = Math.max(0.01, 1 - l - r), h = Math.max(0.01, 1 - t - b);
    return <div className="pptx-shape pptx-picture" style={place(shape.box, deck, true)} data-name={shape.name}>
      {shape.src ? <img src={shape.src} alt={shape.name || '그림'} style={{ width: `${100 / w}%`, height: `${100 / h}%`, left: `${-l / w * 100}%`, top: `${-t / h * 100}%` }} />
        : <span className="pptx-missing"><ImageOff size={14} aria-hidden="true" />{shape.unsupported}</span>}
    </div>;
  }
  if (shape.kind === 'table') {
    const total = shape.columns.reduce((sum, w) => sum + w, 0) || 1;
    return <div className="pptx-shape pptx-table" style={place(shape.box, deck)}>
      <table><colgroup>{shape.columns.map((w, i) => <col key={i} style={{ width: `${w / total * 100}%` }} />)}</colgroup>
        <tbody>{shape.rows.map((row, r) => <tr key={r} style={{ height: cqw(row.height / EMU_PER_PT, widthPt) }}>
          {row.cells.map((cell, c) => cell.hidden ? null : <td key={c} colSpan={cell.span > 1 ? cell.span : undefined} rowSpan={cell.rowSpan > 1 ? cell.rowSpan : undefined}
            style={{ background: cell.fill && cell.fill !== 'none' ? cell.fill : undefined }}><Paragraphs body={cell.text} widthPt={widthPt} /></td>)}
        </tr>)}</tbody></table>
    </div>;
  }
  if (shape.kind === 'placeholder') {
    return <div className="pptx-shape pptx-object" style={place(shape.box, deck)}>
      <span className="pptx-object-label">{shape.label} · 그리지 않음</span>
      {shape.texts.length > 0 && <ul>{shape.texts.map((text, i) => <li key={i}>{text}</li>)}</ul>}
    </div>;
  }
  if (shape.connector) {
    const { flipH, flipV } = shape.box;
    return <svg className="pptx-shape pptx-line" style={place({ ...shape.box, flipH: false, flipV: false }, deck)} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <line x1={flipH ? 100 : 0} y1={flipV ? 100 : 0} x2={flipH ? 0 : 100} y2={flipV ? 0 : 100} stroke={shape.line && shape.line !== 'none' ? shape.line : '#555'}
        strokeWidth={Math.max(1, shape.lineWidth / EMU_PER_PT)} vectorEffect="non-scaling-stroke" />
    </svg>;
  }
  const border = shape.line && shape.line !== 'none' ? `max(1px, ${cqw(shape.lineWidth / EMU_PER_PT, widthPt)}) solid ${shape.line}` : undefined;
  const radius = shape.geometry === 'ellipse' ? '50%' : shape.geometry.startsWith('round') ? '12%' : undefined;
  return <div className="pptx-shape" data-name={shape.name} style={{
    ...place(shape.box, deck), background: shape.fill && shape.fill !== 'none' ? shape.fill : undefined, border, borderRadius: radius,
    ...(shape.image ? { backgroundImage: `url("${shape.image}")`, backgroundSize: 'cover', backgroundPosition: 'center' } : {}),
  }}>{shape.text && shape.text.paras.some(p => p.runs.some(run => run.text.trim())) && <TextFrame body={shape.text} deck={deck} widthPt={widthPt} />}</div>;
}
