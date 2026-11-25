"""현장 연결 진단. 기본 검사는 stdio + 콘솔까지만, --model을 지정할 때만 OpenCode를 실행한다."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from app.agent.mcp import PROTOCOL_VERSIONS, TOOLS

_RECEIPT = re.compile(r"DOCOPS-CHECK-[0-9a-f]{12}")
MODEL_PROMPT = ("연결 시험입니다. docops_status 도구를 check 값 connection으로 딱 한 번 호출하세요. "
                "다른 도구를 쓰지 말고 도구가 돌려준 DOCOPS-CHECK 코드 한 줄만 최종 답변에 쓰세요.")


def _model_error(event: dict) -> str:
    # 원문 오류에는 주소·헤더·요청 본문이 포함될 수 있어 판정에만 쓴다.
    error = event.get("error") or {}
    detail = error.get("data", {}) if isinstance(error, dict) else {}
    status = str(detail.get("statusCode") or detail.get("status") or "") if isinstance(detail, dict) else ""
    messages = {"401": "모델 게이트웨이 인증 실패(401). OpenCode의 자격 증명을 확인하세요.",
                "403": "모델 게이트웨이 접근 거부(403). 모델 사용 권한을 확인하세요.",
                "404": "게이트웨이가 경로 또는 모델을 찾지 못했습니다(404). base URL과 배포 ID를 확인하세요.",
                "429": "모델 게이트웨이의 호출 한도에 도달했습니다(429).",
                "502": "모델 게이트웨이의 상위 서버 오류(502).",
                "503": "모델 게이트웨이에서 서비스를 제공할 수 없습니다(503).",
                "504": "모델 게이트웨이가 제한 시간 안에 응답하지 않았습니다(504)."}
    if status in messages:
        return messages[status]
    raw = json.dumps(error, ensure_ascii=False).lower()
    if any(key in raw for key in ("tool_choice", "function calling", "tool calling", "does not support tools")):
        return "게이트웨이가 도구 호출 관련 오류를 반환했습니다. 해당 배포의 tools 지원 설정을 확인하세요."
    return "OpenCode가 오류를 보고했습니다. 선택한 모델과 게이트웨이 상태를 확인하세요."


def model_evidence(output: str) -> tuple[bool, str]:
    receipt, final = None, ""
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part") or {}
        if event.get("type") == "error":
            return False, _model_error(event)
        if part.get("type") == "tool":
            state = part.get("state", {})
            if part.get("tool") != "docops_status" or state.get("input") != {"check": "connection"}:
                return False, "연결 시험과 다른 도구 또는 인자를 사용했습니다."
            if state.get("status") == "error":
                return False, "모델이 도구를 선택했지만 실행이 실패했습니다."
            if state.get("status") == "completed":
                token = str(state.get("output", "")).strip()
                if receipt or not _RECEIPT.fullmatch(token):
                    return False, "도구 호출이 반복됐거나 확인 코드가 없습니다."
                receipt, final = token, ""
        if receipt and part.get("type") == "text":
            final = str(part.get("text", "")).strip()
    if not receipt:
        return False, "완료된 docops_status 도구 호출을 이벤트에서 찾지 못했습니다."
    if final != receipt:
        return False, "도구는 성공했지만 모델의 최종 답변과 반환 코드가 다릅니다."
    return True, "도구 선택·인자·실행·최종 답변의 확인 코드가 일치합니다."


def workspace_server(workspace: Path) -> dict:
    config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8-sig"))
    mcp = config["mcp"]
    return mcp.get("servers", mcp)["docops"]


def _local_check(spec: dict, workspace: Path, entrypoint: Path) -> bool:
    command = spec.get("command")
    if (spec.get("type") != "local" or spec.get("enabled") is False or spec.get("disabled") is True or
            not isinstance(command, list) or len(command) != 3 or command[-1] != "mcp" or
            Path(command[1]).resolve() != entrypoint.resolve()):
        print("[FAIL workspace] docops 연결 대상이 현재 설치와 다릅니다. init-workspace로 갱신하세요.")
        return False
    env = {**os.environ, **spec.get("environment", {})}
    env.pop("DOCOPS_AGENT_PROBE_ONLY", None)
    requests = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSIONS[0], "capabilities": {},
                                                      "clientInfo": {"name": "docops-doctor", "version": "1"}}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/list"},
        {"id": 3, "method": "tools/call", "params": {"name": "status", "arguments": {"check": "connection"}}},
    ]
    wire = "".join(json.dumps({"jsonrpc": "2.0", **msg}) + "\n" for msg in requests)
    proc = subprocess.run(command, cwd=workspace, env=env, input=wire.encode(), capture_output=True, timeout=45)
    if proc.returncode:
        print(f"[FAIL mcp] MCP 프로세스 종료 코드 {proc.returncode}. 설정의 Python 경로를 확인하세요.")
        return False
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    if [r.get("id") for r in replies] != [1, 2, 3]:
        print("[FAIL mcp] stdio 응답 개수 또는 ID가 요청과 다릅니다.")
        return False
    hello, catalog, status = [r.get("result", {}) for r in replies]
    if hello.get("serverInfo", {}).get("name") != "docops" or hello.get("protocolVersion") not in PROTOCOL_VERSIONS:
        print("[FAIL mcp] docops MCP 초기화 응답을 확인하세요.")
        return False
    names = {tool["name"] for tool in catalog.get("tools", [])}
    if names != {tool["name"] for tool in TOOLS}:
        print("[FAIL catalog] 현재 설치와 실행 중인 MCP 도구 목록이 다릅니다.")
        return False
    print(f"[PASS mcp] stdio 초기화 · 도구 {len(names)}개")
    content = status.get("content") or [{}]
    if status.get("isError") or not _RECEIPT.fullmatch(content[0].get("text", "")):
        print("[FAIL console] 콘솔 API 상태 확인 실패. run.cmd 창과 DOCOPS_API_URL을 확인하세요.")
        return False
    print("[PASS console] MCP에서 콘솔 상태 확인")
    return True


def doctor(argv: list[str], entrypoint: Path) -> int:
    parser = argparse.ArgumentParser(description="OpenCode 작업 폴더의 MCP와 콘솔 연결을 점검합니다.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--model", help="OpenCode에 등록된 사내 provider/model ID. 지정하면 모델 호출 1회를 시험.")
    args = parser.parse_args(argv)
    if args.model and not re.fullmatch(r"[\w.:-]+/[\w./:+~-]+", args.model):
        parser.error("--model에는 현장의 provider/model 식별자를 넣으세요.")
    workspace = args.workspace.expanduser().resolve()
    stage = "workspace"
    try:
        spec = workspace_server(workspace)
        stage = "mcp"
        if not _local_check(spec, workspace, entrypoint):
            return 1
        if not args.model:
            print("[SKIP model] 모델 미호출. Desktop에서 아래 문장을 입력하거나 --model로 시험하세요.")
            print(MODEL_PROMPT)
            return 0
        stage = "model"
        executable = shutil.which("opencode")
        if not executable:
            print("[FAIL model] OpenCode CLI를 PATH에서 찾지 못했습니다. Desktop에서 아래 문장으로 확인하세요.")
            print(MODEL_PROMPT)
            return 1
        usage = subprocess.run([executable, "--help"], capture_output=True, timeout=15)
        mode = ["--standalone"] if b"--standalone" in usage.stdout else []
        proc = subprocess.run([executable, *mode, "run", "--model", args.model, "--format", "json", MODEL_PROMPT],
                              cwd=workspace, env={**os.environ, "DOCOPS_AGENT_PROBE_ONLY": "1"},
                              capture_output=True, timeout=240)
        ok, detail = model_evidence(proc.stdout.decode("utf-8", errors="replace"))
        if proc.returncode:
            reason = detail if not ok else "Desktop에서 같은 모델의 연결 상태를 확인하세요."
            print(f"[FAIL model] OpenCode 종료 코드 {proc.returncode}. {reason}")
            return 1
        print(f"[{'PASS' if ok else 'FAIL'} model] {detail}")
        return 0 if ok else 1
    except subprocess.TimeoutExpired:
        print(f"[FAIL {stage}] 제한 시간 안에 응답이 끝나지 않았습니다.")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"[FAIL {stage}] 설정·실행 경로 또는 응답 형식을 확인하세요 ({type(exc).__name__}).")
    return 1
