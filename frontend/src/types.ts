export type DocumentItem = {
  id: string; name: string; source: string; format: string; size: string;
  updated: string; status: string; stage: string; parser: string; ocr: boolean;
  note: string; pages: number; refs: number; text: string; compare: string;
  simulated?: boolean;
};
export type Relation = {
  id: string; sourceId: string; source: string; location: string; target: string;
  targetId: string | null; evidence: string; method: string; status: string;
};
export type Activity = {time: string; title: string; description: string; type: string; documentId: string};
export type AppData = {asOf: string; documents: DocumentItem[]; relations: Relation[]; activity: Activity[]};
export type { Page } from './navigation';
export type DocumentFilter = {status?: string; format?: string; query?: string; source?: string};
