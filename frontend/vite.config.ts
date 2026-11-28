/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// Node 25는 내장 localStorage를 전역에 두어 jsdom의 localStorage를 가린다.
const webstorage = process.allowedNodeEnvironmentFlags.has('--no-experimental-webstorage') ? ['--no-experimental-webstorage'] : [];
export default defineConfig({ plugins:[react()], server:{proxy:{'/api':'http://127.0.0.1:8000'}}, test:{execArgv:webstorage} });
