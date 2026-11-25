/**
 * PPTX 원본을 브라우저에서 슬라이드로 다시 그리기 위한 모델. 원본 대조용 재현이며 PowerPoint와 똑같지는 않다.
 *
 * 읽는 것: 슬라이드 크기·순서·숨김, 도형 위치(그룹 좌표 변환 포함), 자리표시자의 위치·글자 크기 상속(레이아웃 → 마스터),
 * 글자(크기·굵게·기울임·밑줄·색·위첨자·글머리표·단계·정렬), 채우기·선 색(테마 색 포함), 그림, 표(병합), 차트·SmartArt 자리,
 * 배경, 레이아웃·마스터의 장식 도형, 발표자 메모.
 * 하지 않는 것: 매크로·하이퍼링크 실행, 애니메이션, 도형 효과(그림자·3D), 차트 그리기, 자유형 도형의 정확한 윤곽.
 * 모든 글자는 React가 텍스트로 넣는다(HTML 주입 없음). 그림은 Blob URL로만 쓴다.
 */
import JSZip from 'jszip';

export type Box = { x: number; y: number; w: number; h: number; rot: number; flipH: boolean; flipV: boolean };
export type Run = { text: string; size: number; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean; color?: string; baseline?: number; font?: string };
export type Para = { runs: Run[]; align: 'left' | 'center' | 'right' | 'justify'; level: number; bullet: string | null; marginLeft: number; indent: number; size: number };
export type TextBody = { paras: Para[]; anchor: 'top' | 'middle' | 'bottom'; inset: [number, number, number, number]; vertical: boolean };
export type Cell = { text: TextBody; span: number; rowSpan: number; hidden: boolean; fill?: string };
export type Shape =
  | { kind: 'shape'; box: Box; name: string; geometry: string; fill?: string; image?: string; line?: string; lineWidth: number; text?: TextBody; connector: boolean }
  | { kind: 'picture'; box: Box; name: string; src?: string; unsupported?: string; crop?: [number, number, number, number] }
  | { kind: 'table'; box: Box; name: string; columns: number[]; rows: { height: number; cells: Cell[] }[] }
  | { kind: 'placeholder'; box: Box; name: string; label: string; texts: string[] };
export type Slide = { number: number; hidden: boolean; background?: string; backgroundImage?: string; shapes: Shape[]; notes: string; layout: string };
export type Deck = { width: number; height: number; slides: Slide[]; urls: string[] };

export const EMU_PER_PT = 12700;
const MAX_SLIDES = 500;
const MAX_SHAPES = 3000;
const IMAGE_TYPES: Record<string, string> = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp', webp: 'image/webp', svg: 'image/svg+xml', avif: 'image/avif' };
const DEFAULT_INSET: [number, number, number, number] = [91440, 45720, 91440, 45720];

// ---------------------------------------------------------------- XML 도우미

const kids = (el: Element | null | undefined, name: string) => el ? Array.from(el.children).filter(child => child.localName === name) : [];
const kid = (el: Element | null | undefined, name: string) => el ? Array.from(el.children).find(child => child.localName === name) ?? null : null;
const path = (el: Element | null | undefined, ...names: string[]) => names.reduce<Element | null>((node, name) => kid(node, name), el ?? null);
const num = (value: string | null | undefined, fallback = 0) => {
  if (value === null || value === undefined || value.trim() === '') return fallback; // Number(null)은 0이라 기본값이 사라진다
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};
const bool = (value: string | null | undefined) => value === '1' || value === 'true';
const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const relId = (el: Element | null, name: string) => el?.getAttributeNS(REL_NS, name) ?? el?.getAttribute(`r:${name}`) ?? null;

function resolve(base: string, target: string) {
  if (target.startsWith('/')) return target.slice(1);
  const parts = base.split('/').slice(0, -1);
  for (const part of target.split('/')) {
    if (part === '..') parts.pop();
    else if (part && part !== '.') parts.push(part);
  }
  return parts.join('/');
}

type Rels = Map<string, { target: string; type: string; external: boolean }>;

class Package {
  private xml = new Map<string, Document | null>();
  private rels = new Map<string, Rels>();
  urls: string[] = [];
  private images = new Map<string, string>();

  constructor(private zip: JSZip, private toUrl: (data: Uint8Array, mime: string) => string) {}

  async doc(name: string): Promise<Document | null> {
    if (!this.xml.has(name)) {
      const file = this.zip.file(name);
      const text = file ? await file.async('string') : null;
      const parsed = text ? new DOMParser().parseFromString(text, 'application/xml') : null;
      this.xml.set(name, parsed && !parsed.getElementsByTagName('parsererror').length ? parsed : null);
    }
    return this.xml.get(name) ?? null;
  }

  async relsOf(part: string): Promise<Rels> {
    if (!this.rels.has(part)) {
      const folder = part.split('/').slice(0, -1).join('/');
      const relsDoc = await this.doc(`${folder ? folder + '/' : ''}_rels/${part.split('/').pop()}.rels`);
      const map: Rels = new Map();
      for (const rel of Array.from(relsDoc?.documentElement.children ?? [])) {
        const external = rel.getAttribute('TargetMode') === 'External';
        const target = rel.getAttribute('Target') ?? '';
        map.set(rel.getAttribute('Id') ?? '', { target: external ? target : resolve(part, target), type: (rel.getAttribute('Type') ?? '').split('/').pop() ?? '', external });
      }
      this.rels.set(part, map);
    }
    return this.rels.get(part)!;
  }

  async related(part: string, type: string) {
    for (const rel of (await this.relsOf(part)).values()) if (rel.type === type && !rel.external) return rel.target;
    return null;
  }

  /** 그림 → Blob URL. 브라우저가 못 그리는 형식(EMF·WMF·TIFF)은 이유를 돌려준다. */
  async image(part: string, id: string | null): Promise<{ src?: string; unsupported?: string }> {
    const rel = id ? (await this.relsOf(part)).get(id) : undefined;
    if (!rel) return { unsupported: '그림 연결 없음' };
    if (rel.external) return { unsupported: '외부 연결 그림(불러오지 않음)' };
    const ext = rel.target.split('.').pop()?.toLowerCase() ?? '';
    const mime = IMAGE_TYPES[ext];
    if (!mime) return { unsupported: `${ext.toUpperCase() || '알 수 없는'} 그림(브라우저 표시 불가)` };
    if (!this.images.has(rel.target)) {
      const file = this.zip.file(rel.target);
      if (!file) return { unsupported: '그림 파일 없음' };
      const url = this.toUrl(await file.async('uint8array'), mime);
      this.urls.push(url);
      this.images.set(rel.target, url);
    }
    return { src: this.images.get(rel.target) };
  }
}

// ---------------------------------------------------------------- 색

type Theme = { colors: Record<string, string>; major: string; minor: string; majorEa: string; minorEa: string };

function hexToRgb(hex: string) { const n = parseInt(hex, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
function rgbToHex(rgb: number[]) { return '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join(''); }
function rgbToHsl([r, g, b]: number[]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}
function hslToRgb([h, s, l]: number[]) {
  if (!s) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t: number) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
}

const SCHEME_ALIAS: Record<string, string> = { bg1: 'lt1', tx1: 'dk1', bg2: 'lt2', tx2: 'dk2' };

function color(el: Element | null, theme: Theme, placeholder?: string): string | undefined {
  if (!el) return undefined;
  let base: string | undefined;
  if (el.localName === 'srgbClr') base = el.getAttribute('val') ?? undefined;
  else if (el.localName === 'sysClr') base = el.getAttribute('lastClr') ?? (el.getAttribute('val') === 'window' ? 'FFFFFF' : '000000');
  else if (el.localName === 'schemeClr') {
    const val = el.getAttribute('val') ?? '';
    base = val === 'phClr' ? placeholder?.replace('#', '') : theme.colors[val] ?? theme.colors[SCHEME_ALIAS[val]];
  } else if (el.localName === 'prstClr') base = ({ black: '000000', white: 'FFFFFF', red: 'FF0000', blue: '0000FF', green: '008000', yellow: 'FFFF00', gray: '808080' } as Record<string, string>)[el.getAttribute('val') ?? ''];
  if (!base || !/^[0-9a-f]{6}$/i.test(base)) return undefined;
  let rgb = hexToRgb(base);
  let alpha = 1;
  for (const mod of Array.from(el.children)) {
    const v = num(mod.getAttribute('val'), 100000) / 100000;
    if (mod.localName === 'lumMod' || mod.localName === 'lumOff') {
      const hsl = rgbToHsl(rgb);
      hsl[2] = mod.localName === 'lumMod' ? hsl[2] * v : hsl[2] + v;
      rgb = hslToRgb([hsl[0], hsl[1], Math.max(0, Math.min(1, hsl[2]))]);
    } else if (mod.localName === 'tint') rgb = rgb.map(c => c + (255 - c) * (1 - v));
    else if (mod.localName === 'shade') rgb = rgb.map(c => c * v);
    else if (mod.localName === 'alpha') alpha = v;
  }
  const hex = rgbToHex(rgb);
  return alpha < 1 ? `rgba(${hexToRgb(hex.slice(1)).join(',')},${alpha.toFixed(2)})` : hex;
}

const colorIn = (el: Element | null, theme: Theme, placeholder?: string) =>
  color(el ? Array.from(el.children).find(c => ['srgbClr', 'schemeClr', 'sysClr', 'prstClr'].includes(c.localName)) ?? null : null, theme, placeholder);

/** a:solidFill · a:gradFill(첫 색) · a:noFill. 없으면 undefined, 채우지 않음이면 'none'. */
function fill(props: Element | null, theme: Theme): string | undefined {
  if (!props) return undefined;
  if (kid(props, 'noFill')) return 'none';
  const solid = kid(props, 'solidFill');
  if (solid) return colorIn(solid, theme);
  const grad = kid(props, 'gradFill');
  if (grad) return colorIn(path(grad, 'gsLst', 'gs'), theme);
  return undefined;
}

// ---------------------------------------------------------------- 글자 스타일 상속

type Ctx = { pkg: Package; theme: Theme; part: string };
type Levels = (Element | null)[]; // 가까운 것부터: 도형 lstStyle → 레이아웃 → 마스터 자리표시자 → 마스터 txStyles → 기본

const levelProps = (levels: Levels, level: number) => levels.map(list => kid(list, `lvl${level + 1}pPr`)).filter((el): el is Element => !!el);

function pick<T>(chain: Element[], read: (el: Element) => T | undefined): T | undefined {
  for (const el of chain) { const v = read(el); if (v !== undefined) return v; }
  return undefined;
}

function fontFamily(face: string | undefined, theme: Theme) {
  if (!face) return undefined;
  if (face === '+mj-lt') return theme.major;
  if (face === '+mn-lt') return theme.minor;
  if (face === '+mj-ea') return theme.majorEa || theme.major;
  if (face === '+mn-ea') return theme.minorEa || theme.minor;
  return face.startsWith('+') ? undefined : face;
}

function textBody(body: Element | null, levels: Levels, bodyPrs: (Element | null)[], ctx: Ctx, placeholderColor?: string): TextBody | undefined {
  if (!body) return undefined;
  const bodyPr = [kid(body, 'bodyPr'), ...bodyPrs].filter((el): el is Element => !!el);
  const anchorValue = pick(bodyPr, el => el.getAttribute('anchor') ?? undefined) ?? 't';
  const inset = (['lIns', 'tIns', 'rIns', 'bIns'] as const).map((name, i) => num(pick(bodyPr, el => el.getAttribute(name) ?? undefined), DEFAULT_INSET[i])) as [number, number, number, number];
  const autofit = path(body, 'bodyPr', 'normAutofit');
  const scale = autofit ? num(autofit.getAttribute('fontScale'), 100000) / 100000 : 1;
  const vert = pick(bodyPr, el => el.getAttribute('vert') ?? undefined);
  const counters: number[] = [];
  const paras: Para[] = [];
  for (const p of kids(body, 'p')) {
    const pPr = kid(p, 'pPr');
    const level = Math.min(8, num(pPr?.getAttribute('lvl'), 0));
    const chain = [...(pPr ? [pPr] : []), ...levelProps([kid(body, 'lstStyle'), ...levels], level)];
    const defaults = chain.map(el => kid(el, 'defRPr')).filter((el): el is Element => !!el);
    const baseSize = num(pick(defaults, el => el.getAttribute('sz') ?? undefined), 1800) / 100;
    const runs: Run[] = [];
    for (const child of Array.from(p.children)) {
      if (child.localName === 'br') { runs.push({ text: '\n', size: baseSize * scale }); continue; }
      if (child.localName !== 'r' && child.localName !== 'fld') continue;
      const rPr = kid(child, 'rPr');
      const props = [...(rPr ? [rPr] : []), ...defaults];
      const attr = (name: string) => pick(props, el => el.getAttribute(name) ?? undefined);
      const fillEl = pick(props, el => kid(el, 'solidFill') ?? undefined);
      runs.push({
        text: kid(child, 't')?.textContent ?? '',
        size: num(attr('sz'), baseSize * 100) / 100 * scale,
        bold: bool(attr('b')) || undefined, italic: bool(attr('i')) || undefined,
        underline: (attr('u') && attr('u') !== 'none') || undefined, strike: (attr('strike') && attr('strike') !== 'noStrike') || undefined,
        color: (fillEl ? colorIn(fillEl, ctx.theme, placeholderColor) : undefined) ?? placeholderColor ?? (ctx.theme.colors.tx1 ? `#${ctx.theme.colors.tx1}` : undefined),
        baseline: num(attr('baseline'), 0) || undefined,
        font: fontFamily(pick(props, el => kid(el, 'ea')?.getAttribute('typeface') ?? kid(el, 'latin')?.getAttribute('typeface') ?? undefined), ctx.theme),
      });
    }
    // 글머리표: 가장 가까운 설정을 쓴다(buNone이면 없음).
    const bulletEl = pick(chain, el => kid(el, 'buNone') ?? kid(el, 'buChar') ?? kid(el, 'buAutoNum') ?? undefined);
    let bullet: string | null = null;
    const hasText = runs.some(run => run.text.trim());
    counters.length = level + 1;
    if (bulletEl?.localName === 'buChar' && hasText) bullet = bulletEl.getAttribute('char') || '•';
    else if (bulletEl?.localName === 'buAutoNum' && hasText) {
      counters[level] = (counters[level] ?? num(bulletEl.getAttribute('startAt'), 1) - 1) + 1;
      const type = bulletEl.getAttribute('type') ?? 'arabicPeriod';
      const n = counters[level];
      const mark = type.startsWith('alphaLc') ? String.fromCharCode(96 + ((n - 1) % 26) + 1) : type.startsWith('alphaUc') ? String.fromCharCode(64 + ((n - 1) % 26) + 1)
        : type.startsWith('circleNum') ? String.fromCharCode(0x2460 + Math.min(n, 20) - 1) : String(n);
      bullet = mark + (type.endsWith('ParenR') ? ')' : type.endsWith('ParenBoth') ? ')' : '.');
      if (type.endsWith('ParenBoth')) bullet = '(' + bullet;
    }
    const algn = pick(chain, el => el.getAttribute('algn') ?? undefined);
    paras.push({
      runs, level, bullet, size: baseSize * scale,
      align: algn === 'ctr' ? 'center' : algn === 'r' ? 'right' : algn === 'just' || algn === 'dist' ? 'justify' : 'left',
      marginLeft: num(pick(chain, el => el.getAttribute('marL') ?? undefined), 0),
      indent: num(pick(chain, el => el.getAttribute('indent') ?? undefined), 0),
    });
  }
  return { paras, anchor: anchorValue === 'ctr' ? 'middle' : anchorValue === 'b' ? 'bottom' : 'top', inset, vertical: !!vert && vert !== 'horz' };
}

// ---------------------------------------------------------------- 도형

type Transform = (box: Box) => Box;
const identity: Transform = box => box;

function readXfrm(xfrm: Element | null): Box | null {
  const off = kid(xfrm, 'off'), ext = kid(xfrm, 'ext');
  if (!xfrm || !off || !ext) return null;
  return { x: num(off.getAttribute('x')), y: num(off.getAttribute('y')), w: num(ext.getAttribute('cx')), h: num(ext.getAttribute('cy')),
    rot: num(xfrm.getAttribute('rot')) / 60000, flipH: bool(xfrm.getAttribute('flipH')), flipV: bool(xfrm.getAttribute('flipV')) };
}

type Placeholder = { type: string; idx: string | null };
type Template = { sp: Element; part: string };
type Templates = { byIdx: Map<string, Template>; byType: Map<string, Template> };

function placeholderOf(shape: Element): Placeholder | null {
  const nv = Array.from(shape.children).find(child => child.localName.startsWith('nv'));
  const ph = path(nv, 'nvPr', 'ph');
  return ph ? { type: ph.getAttribute('type') ?? 'body', idx: ph.getAttribute('idx') } : null;
}

const MASTER_TYPE: Record<string, string> = { ctrTitle: 'title', subTitle: 'body', obj: 'body', tbl: 'body', chart: 'body', pic: 'body', dgm: 'body', media: 'body', clipArt: 'body' };

function templates(doc: Document | null, part: string): Templates {
  const result: Templates = { byIdx: new Map(), byType: new Map() };
  for (const sp of Array.from(doc?.getElementsByTagNameNS('*', 'sp') ?? [])) {
    const ph = placeholderOf(sp);
    if (!ph) continue;
    if (ph.idx !== null && !result.byIdx.has(ph.idx)) result.byIdx.set(ph.idx, { sp, part });
    if (!result.byType.has(ph.type)) result.byType.set(ph.type, { sp, part });
  }
  return result;
}

function findTemplate(ph: Placeholder, layout: Templates, master: Templates) {
  const fromLayout = (ph.idx !== null ? layout.byIdx.get(ph.idx) : undefined) ?? layout.byType.get(ph.type);
  const masterType = MASTER_TYPE[ph.type] ?? ph.type;
  const fromMaster = master.byType.get(masterType) ?? (masterType !== 'body' && !['title', 'dt', 'ftr', 'sldNum'].includes(masterType) ? master.byType.get('body') : undefined);
  return [fromLayout, fromMaster].filter((t): t is Template => !!t);
}

type Scope = { ctx: Ctx; layout: Templates; master: Templates; txStyles: Element | null; defaultStyle: Element | null; out: Shape[]; fromTemplate: boolean };

function styleFor(ph: Placeholder | null, scope: Scope) {
  if (!ph) return path(scope.txStyles, 'otherStyle') ?? scope.defaultStyle;
  const type = MASTER_TYPE[ph.type] ?? ph.type;
  return type === 'title' ? path(scope.txStyles, 'titleStyle') : ['dt', 'ftr', 'sldNum'].includes(type) ? path(scope.txStyles, 'otherStyle') : path(scope.txStyles, 'bodyStyle');
}

async function walk(tree: Element, scope: Scope, transform: Transform) {
  for (const raw of Array.from(tree.children)) {
    if (scope.out.length >= MAX_SHAPES) return;
    let el = raw;
    if (el.localName === 'AlternateContent') {
      // 새 기능(mc:Choice) 대신 호환용 대체본(mc:Fallback)을 쓴다. 대체본이 없으면 Choice.
      const branch = kid(el, 'Fallback') ?? kid(el, 'Choice');
      if (branch) await walk(branch, scope, transform);
      continue;
    }
    const name = path(Array.from(el.children).find(child => child.localName.startsWith('nv')), 'cNvPr')?.getAttribute('name') ?? '';
    if (el.localName === 'grpSp') {
      const xfrm = path(el, 'grpSpPr', 'xfrm');
      const box = readXfrm(xfrm);
      const chOff = kid(xfrm, 'chOff'), chExt = kid(xfrm, 'chExt');
      if (!box || !chOff || !chExt) { await walk(el, scope, transform); continue; }
      const cx = num(chOff.getAttribute('x')), cy = num(chOff.getAttribute('y'));
      const sx = num(chExt.getAttribute('cx')) ? box.w / num(chExt.getAttribute('cx')) : 1;
      const sy = num(chExt.getAttribute('cy')) ? box.h / num(chExt.getAttribute('cy')) : 1;
      const inner: Transform = child => transform({ ...child, x: box.x + (child.x - cx) * sx, y: box.y + (child.y - cy) * sy, w: child.w * sx, h: child.h * sy });
      await walk(el, scope, inner);
      continue;
    }
    if (el.localName === 'sp' || el.localName === 'cxnSp') {
      const ph = placeholderOf(el);
      if (ph && scope.fromTemplate) continue; // 레이아웃·마스터의 자리표시자는 '제목을 입력하십시오' 같은 틀이라 그리지 않는다
      const found = ph ? findTemplate(ph, scope.layout, scope.master) : [];
      const spPr = kid(el, 'spPr');
      const box = readXfrm(kid(spPr, 'xfrm')) ?? found.map(t => readXfrm(path(t.sp, 'spPr', 'xfrm'))).find(Boolean) ?? null;
      if (!box) continue;
      const style = kid(el, 'style');
      const refColor = (name: string) => { const ref = kid(style, name); return ref && num(ref.getAttribute('idx')) > 0 ? colorIn(ref, scope.ctx.theme) : undefined; };
      const ln = kid(spPr, 'ln');
      const lineFill = ln ? fill(ln, scope.ctx.theme) : undefined;
      const geometry = path(spPr, 'prstGeom')?.getAttribute('prst') ?? (kid(spPr, 'custGeom') ? 'custom' : 'rect');
      const blip = path(spPr, 'blipFill', 'blip');
      const levels: Levels = [...found.map(t => path(t.sp, 'txBody', 'lstStyle')), styleFor(ph, scope), scope.defaultStyle];
      const fontColor = colorIn(kid(style, 'fontRef'), scope.ctx.theme);
      scope.out.push({
        kind: 'shape', box: transform(box), name, geometry, connector: el.localName === 'cxnSp' || geometry.startsWith('line') || geometry.includes('Connector'),
        fill: fill(spPr, scope.ctx.theme) ?? refColor('fillRef'),
        image: blip ? (await scope.ctx.pkg.image(scope.ctx.part, relId(blip, 'embed'))).src : undefined,
        line: lineFill ?? refColor('lnRef'), lineWidth: num(ln?.getAttribute('w'), 12700),
        text: textBody(kid(el, 'txBody'), levels, found.map(t => path(t.sp, 'txBody', 'bodyPr')), scope.ctx, fontColor),
      });
      continue;
    }
    if (el.localName === 'pic') {
      const ph = placeholderOf(el);
      if (ph && scope.fromTemplate) continue;
      const found = ph ? findTemplate(ph, scope.layout, scope.master) : [];
      const box = readXfrm(path(el, 'spPr', 'xfrm')) ?? found.map(t => readXfrm(path(t.sp, 'spPr', 'xfrm'))).find(Boolean) ?? null;
      if (!box) continue;
      const blipFill = kid(el, 'blipFill');
      const src = path(blipFill, 'srcRect');
      const crop = src ? (['l', 't', 'r', 'b'].map(side => num(src.getAttribute(side)) / 100000) as [number, number, number, number]) : undefined;
      scope.out.push({ kind: 'picture', box: transform(box), name, ...(await scope.ctx.pkg.image(scope.ctx.part, relId(kid(blipFill, 'blip'), 'embed'))), crop });
      continue;
    }
    if (el.localName === 'graphicFrame') {
      const box = readXfrm(kid(el, 'xfrm'));
      if (!box) continue;
      const data = path(el, 'graphic', 'graphicData');
      const uri = data?.getAttribute('uri') ?? '';
      const table = kid(data, 'tbl');
      if (table) {
        const columns = kids(kid(table, 'tblGrid'), 'gridCol').map(col => num(col.getAttribute('w')));
        const rows = kids(table, 'tr').map(tr => ({
          height: num(tr.getAttribute('h')),
          cells: kids(tr, 'tc').map(tc => ({
            text: textBody(kid(tc, 'txBody'), [scope.defaultStyle], [], scope.ctx) ?? { paras: [], anchor: 'top' as const, inset: DEFAULT_INSET, vertical: false },
            span: num(tc.getAttribute('gridSpan'), 1), rowSpan: num(tc.getAttribute('rowSpan'), 1),
            hidden: bool(tc.getAttribute('hMerge')) || bool(tc.getAttribute('vMerge')),
            fill: fill(kid(tc, 'tcPr'), scope.ctx.theme),
          })),
        }));
        scope.out.push({ kind: 'table', box: transform(box), name, columns, rows });
      } else {
        const label = uri.endsWith('/chart') ? '차트' : uri.endsWith('/diagram') ? 'SmartArt' : uri.endsWith('/ole') ? '내장 개체' : '개체';
        scope.out.push({ kind: 'placeholder', box: transform(box), name, label, texts: await graphicTexts(data, scope.ctx) });
      }
    }
  }
}

/** 차트 제목·SmartArt 글자. 그리지는 못해도 무엇이 있는지는 보여 준다. */
async function graphicTexts(data: Element | null, ctx: Ctx): Promise<string[]> {
  const target = Array.from(data?.children ?? []).map(child => relId(child, 'id') ?? relId(child, 'dm')).find(Boolean);
  if (!target) return [];
  const rel = (await ctx.pkg.relsOf(ctx.part)).get(target);
  if (!rel || rel.external) return [];
  const doc = await ctx.pkg.doc(rel.target);
  if (!doc) return [];
  const scope = rel.type === 'chart' ? Array.from(doc.getElementsByTagNameNS('*', 'title')).slice(0, 1) : [doc.documentElement];
  return scope.flatMap(node => Array.from(node.getElementsByTagNameNS('*', 'p')).map(p => Array.from(p.getElementsByTagNameNS('*', 't')).map(t => t.textContent ?? '').join('')))
    .filter(text => text.trim()).slice(0, 40);
}

async function background(doc: Document | null, ctx: Ctx): Promise<{ color?: string; image?: string } | undefined> {
  const bg = path(doc?.documentElement, 'cSld', 'bg');
  if (!bg) return undefined;
  const bgPr = kid(bg, 'bgPr');
  if (bgPr) {
    const blip = path(bgPr, 'blipFill', 'blip');
    if (blip) return { image: (await ctx.pkg.image(ctx.part, relId(blip, 'embed'))).src };
    const value = fill(bgPr, ctx.theme);
    return value && value !== 'none' ? { color: value } : undefined;
  }
  const ref = kid(bg, 'bgRef');
  return ref ? { color: colorIn(ref, ctx.theme) } : undefined;
}

async function readTheme(pkg: Package, masterPart: string): Promise<Theme> {
  const themePart = await pkg.related(masterPart, 'theme');
  const doc = themePart ? await pkg.doc(themePart) : null;
  const colors: Record<string, string> = {};
  const scheme = doc?.getElementsByTagNameNS('*', 'clrScheme')[0];
  for (const entry of Array.from(scheme?.children ?? [])) {
    const value = entry.firstElementChild;
    const hex = value?.localName === 'srgbClr' ? value.getAttribute('val') : value?.getAttribute('lastClr');
    if (hex) colors[entry.localName] = hex;
  }
  const fonts = doc?.getElementsByTagNameNS('*', 'fontScheme')[0];
  const face = (group: string, script: string) => path(kid(fonts, group), script)?.getAttribute('typeface') ?? '';
  return { colors, major: face('majorFont', 'latin'), minor: face('minorFont', 'latin'), majorEa: face('majorFont', 'ea'), minorEa: face('minorFont', 'ea') };
}

async function notesText(pkg: Package, slidePart: string) {
  const notesPart = await pkg.related(slidePart, 'notesSlide');
  const doc = notesPart ? await pkg.doc(notesPart) : null;
  if (!doc) return '';
  for (const sp of Array.from(doc.getElementsByTagNameNS('*', 'sp'))) {
    if (placeholderOf(sp)?.type !== 'body') continue;
    return kids(kid(sp, 'txBody'), 'p').map(p => Array.from(p.getElementsByTagNameNS('*', 't')).map(t => t.textContent ?? '').join('')).join('\n').trim();
  }
  return '';
}

export async function readPptx(data: ArrayBuffer | Uint8Array, toUrl: (data: Uint8Array, mime: string) => string): Promise<Deck> {
  const zip = await JSZip.loadAsync(data);
  const pkg = new Package(zip, toUrl);
  const presentation = await pkg.doc('ppt/presentation.xml');
  if (!presentation) throw new Error('PowerPoint 본문(ppt/presentation.xml)을 찾을 수 없습니다.');
  const root = presentation.documentElement;
  const size = kid(root, 'sldSz');
  const width = num(size?.getAttribute('cx'), 12192000), height = num(size?.getAttribute('cy'), 6858000);
  const defaultStyle = kid(root, 'defaultTextStyle');
  const rels = await pkg.relsOf('ppt/presentation.xml');
  const slideParts = kids(kid(root, 'sldIdLst'), 'sldId').map(el => rels.get(relId(el, 'id') ?? '')?.target).filter((t): t is string => !!t).slice(0, MAX_SLIDES);
  const slides: Slide[] = [];
  for (const [index, part] of slideParts.entries()) {
    const doc = await pkg.doc(part);
    if (!doc) continue;
    const layoutPart = await pkg.related(part, 'slideLayout');
    const layoutDoc = layoutPart ? await pkg.doc(layoutPart) : null;
    const masterPart = layoutPart ? await pkg.related(layoutPart, 'slideMaster') : null;
    const masterDoc = masterPart ? await pkg.doc(masterPart) : null;
    const theme = masterPart ? await readTheme(pkg, masterPart) : { colors: {}, major: '', minor: '', majorEa: '', minorEa: '' };
    // 마스터의 색 대응(clrMap)으로 bg1·tx1 등을 바꿔 단다.
    const clrMap = masterDoc?.getElementsByTagNameNS('*', 'clrMap')[0];
    if (clrMap) for (const alias of ['bg1', 'tx1', 'bg2', 'tx2']) { const target = clrMap.getAttribute(alias); if (target && theme.colors[target]) theme.colors[alias] = theme.colors[target]; }
    const layout = templates(layoutDoc, layoutPart ?? ''), master = templates(masterDoc, masterPart ?? '');
    const txStyles = masterDoc?.getElementsByTagNameNS('*', 'txStyles')[0] ?? null;
    const out: Shape[] = [];
    const base = { layout, master, txStyles, defaultStyle, out };
    const showMaster = (d: Document | null) => d?.documentElement.getAttribute('showMasterSp') !== '0';
    // 장식 도형(로고·띠): 마스터 → 레이아웃 → 슬라이드 순으로 쌓는다.
    if (showMaster(doc) && showMaster(layoutDoc) && masterDoc && masterPart) {
      const tree = path(masterDoc.documentElement, 'cSld', 'spTree');
      if (tree) await walk(tree, { ...base, ctx: { pkg, theme, part: masterPart }, fromTemplate: true }, identity);
    }
    if (showMaster(doc) && layoutDoc && layoutPart) {
      const tree = path(layoutDoc.documentElement, 'cSld', 'spTree');
      if (tree) await walk(tree, { ...base, ctx: { pkg, theme, part: layoutPart }, fromTemplate: true }, identity);
    }
    const ctx = { pkg, theme, part };
    const tree = path(doc.documentElement, 'cSld', 'spTree');
    if (tree) await walk(tree, { ...base, ctx, fromTemplate: false }, identity);
    const bg = await background(doc, ctx) ?? (layoutPart ? await background(layoutDoc, { pkg, theme, part: layoutPart }) : undefined)
      ?? (masterPart ? await background(masterDoc, { pkg, theme, part: masterPart }) : undefined);
    slides.push({ number: index + 1, hidden: doc.documentElement.getAttribute('show') === '0', background: bg?.color, backgroundImage: bg?.image,
      shapes: out, notes: await notesText(pkg, part), layout: path(layoutDoc?.documentElement, 'cSld')?.getAttribute('name') ?? '' });
  }
  return { width, height, slides, urls: pkg.urls };
}
