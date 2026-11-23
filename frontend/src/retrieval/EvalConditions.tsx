import { useState } from 'react';
import { Modal, Segmented } from '../ui';
import { saveQuestions, type Candidate, type Preset, type Question, type RetrievalConfig, type RetrievalDoc, type Sample } from '../api/retrieval';
import { DocChoices, ModelChoices } from './eval-setup';
import { QuestionChoices } from './eval-questions';
import { defaultCandidates } from './eval-common';
import { errorText } from './shared';

export type EvalSetup = { candidates: Candidate[] | null; docIds: string[] | null; presetId: string | null };
type Props = {
  setup: EvalSetup; docIds: string[]; candidates: Candidate[]; questions: Question[] | null; docs: RetrievalDoc[]; samples: Sample[];
  config: RetrievalConfig | null; presets: Preset[]; preset: Preset | null; onClose: () => void;
  onApply: (setup: EvalSetup, questions: Question[] | null) => void;
};

export function EvalConditions({ setup, docIds, candidates, questions, docs, samples, config, presets, preset, onClose, onApply }: Props) {
  const [tab, setTab] = useState<'docs'|'questions'|'models'>('docs');
  const [draft, setDraft] = useState(setup);
  const [draftQuestions, setDraftQuestions] = useState(questions);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const cancel = () => { if (!saving) onClose(); };
  async function apply() {
    if (saving) return;
    setSaving(true); setError('');
    try {
      let updated = questions;
      if (draftQuestions && JSON.stringify(draftQuestions) !== JSON.stringify(questions)) {
        updated = (await saveQuestions(draftQuestions.filter(q => q.question.trim()))).questions;
      }
      onApply(draft, updated);
    } catch (cause) { setError(errorText(cause)); setSaving(false); }
  }
  return <Modal open onClose={cancel} title="평가 조건" size="lg"
    tabs={<Segmented label="평가 조건 항목" value={tab} onChange={setTab} options={[{id:'docs',label:'문서·청킹'},{id:'questions',label:'질문'},{id:'models',label:'모델'}]}/>}
    footer={<>{error && <span role="alert" className="ee-warn-text">{error}</span>}<button className="ee-btn" disabled={saving} onClick={cancel}>취소</button>
      <button className="ee-btn is-primary" disabled={saving} onClick={() => void apply()}>{saving ? '적용 중' : '적용'}</button></>}>
    <fieldset className="condition-fields" disabled={saving}>
      {tab === 'docs' && <><label className="condition-preset">청킹 전략<select value={draft.presetId ?? preset?.id ?? ''} onChange={e => setDraft({...draft, presetId:e.target.value})}>{presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <DocChoices samples={samples} docs={docs} questions={draftQuestions ?? []} docIds={draft.docIds ?? docIds} max={config?.caps.max_documents ?? 200} onChange={ids => setDraft({...draft,docIds:ids})}/></>}
      {tab === 'questions' && (draftQuestions ? <QuestionChoices questions={draftQuestions} onChange={setDraftQuestions} docs={docs} samples={samples} maxRows={config?.caps.max_question_rows ?? 2000}/> : <p>질문을 불러오지 못했습니다.</p>)}
      {tab === 'models' && <ModelChoices config={config} candidates={draft.candidates ?? (setup.candidates ? defaultCandidates(config) : candidates)} isDefault={draft.candidates === null}
        onChange={list => setDraft({...draft,candidates:list})} onReset={() => setDraft({...draft,candidates:null})}/>}
    </fieldset>
  </Modal>;
}
