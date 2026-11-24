"""작업 에이전트(OpenCode 등)용 도구: 실행 중인 콘솔 API를 부르는 MCP 서버와 CLI.

표준 라이브러리만 쓴다. 콘솔 서버가 runtime 저장소를 잠그므로(server.lock) SQLite를 직접 열지 않고 HTTP로만 다룬다.
"""
