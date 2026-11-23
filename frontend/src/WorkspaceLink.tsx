import type { AnchorHTMLAttributes } from 'react';
import { workspaceHref, type WorkspaceRoute } from './navigation';

type Props = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'onClick' | 'href'> & {
  to: WorkspaceRoute;
  onNavigate: (route: WorkspaceRoute) => void;
};

export function WorkspaceLink({ to, onNavigate, children, ...attrs }: Props) {
  return <a {...attrs} href={workspaceHref(to)} onClick={event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(to);
  }}>{children}</a>;
}
