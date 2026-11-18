import { useEffect, useId, useRef } from 'react';
import type { KeyboardEvent, ReactNode, RefObject } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import './ui.css';

type Props = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** sm 440 · md 680 · lg 980 · xl 1240(높이 고정, 마스터-디테일용) */
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /** 제목 오른쪽(닫기 버튼 앞)에 둘 작은 표시나 버튼 */
  extra?: ReactNode;
  /** 제목 아래 탭 줄 */
  tabs?: ReactNode;
  footer?: ReactNode;
  /** 본문 여백 없이 채움(목록 + 상세 배치용) */
  flush?: boolean;
  initialFocus?: RefObject<HTMLElement | null>;
  children: ReactNode;
};

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
let openCount = 0;
let bodyOverflow = '';

/** 가운데 팝업. Escape·바깥 클릭·X로 닫고, 닫으면 연 자리로 초점을 돌려준다. */
export function Modal({ open, onClose, title, subtitle, size = 'md', extra, tabs, footer, flush, initialFocus, children }: Props) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    if (openCount === 0) bodyOverflow = document.body.style.overflow;
    openCount += 1;
    document.body.style.overflow = 'hidden';
    const body = dialogRef.current?.querySelector('.ui-dialog-body');
    const target = initialFocus?.current ?? body?.querySelector<HTMLElement>(FOCUSABLE) ?? dialogRef.current;
    target?.focus({ preventScroll: true });
    return () => {
      openCount -= 1;
      if (openCount === 0) document.body.style.overflow = bodyOverflow;
      if (opener && opener.isConnected && !opener.closest('[hidden], [inert]')) opener.focus({ preventScroll: true });
    };
    // 열릴 때 한 번만 초점을 옮긴다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeRef.current();
      return;
    }
    if (event.key !== 'Tab' || !dialogRef.current) return;
    const items = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(el => el.tabIndex >= 0 && !el.closest('[hidden], [inert]'));
    if (!items.length) { event.preventDefault(); return; }
    const first = items[0]; const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };

  return createPortal(
    <div className="ui-overlay" onMouseDown={event => { if (event.target === event.currentTarget) closeRef.current(); }}>
      <div ref={dialogRef} className={`ui-dialog is-${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onKeyDown={onKeyDown}>
        <div className="ui-dialog-head">
          <div className="ui-dialog-titles">
            <h2 className="ui-dialog-title" id={titleId}>{title}</h2>
            {subtitle && <p className="ui-dialog-sub">{subtitle}</p>}
          </div>
          {extra && <div className="ui-dialog-extra">{extra}</div>}
          <button type="button" className="ui-dialog-close" onClick={() => closeRef.current()} aria-label="닫기"><X size={18} /></button>
        </div>
        {tabs && <div className="ui-dialog-tabs">{tabs}</div>}
        <div className={'ui-dialog-body' + (flush ? ' is-flush' : '')}>{children}</div>
        {footer && <div className="ui-dialog-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
