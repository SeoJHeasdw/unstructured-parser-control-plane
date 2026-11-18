import { ArrowRight, ChevronRight, FileCheck2, FolderUp, Play } from 'lucide-react';

const steps = [
  { label: '파일 선택', icon: FolderUp },
  { label: '파싱 실행', icon: Play },
  { label: '결과 확인', icon: FileCheck2 },
];

export function WorkspaceIntro({ onLive, onExamples }: { onLive: () => void; onExamples: () => void }) {
  return <section className="workspace-intro" aria-labelledby="workspace-intro-title">
    <div className="workspace-intro-copy">
      <h2 id="workspace-intro-title">내 문서 처리 시작하기</h2>
      <p>이 컴퓨터에 파일을 저장하고, 문서에서 추출한 내용을 확인하세요.</p>
      <div className="workspace-intro-actions">
        <button className="workspace-intro-primary" onClick={onLive}>파일 처리 시작 <ArrowRight size={17} aria-hidden="true" /></button>
        <button className="workspace-intro-secondary" onClick={onExamples}>예시 문서 둘러보기 <ChevronRight size={15} aria-hidden="true" /></button>
      </div>
    </div>
    <ol className="workspace-intro-steps" aria-label="실제 파일 처리 순서">
      {steps.map(({ label, icon: Icon }) => <li key={label}>
        <span className="workspace-step-icon"><Icon size={22} strokeWidth={1.65} aria-hidden="true" /></span>
        <span>{label}</span>
      </li>)}
    </ol>
  </section>;
}
