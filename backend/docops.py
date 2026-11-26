"""작업 도구 진입점. 콘솔 서버(run.cmd·run.sh)가 켜져 있어야 한다.

  python docops.py init-workspace <폴더> --roots "<문서 폴더>"   OpenCode 작업 폴더 만들기
  python docops.py doctor <작업 폴더> [--model provider/model]  현장 연결 점검
  python docops.py mcp                       OpenCode 등 MCP 클라이언트용 stdio 서버
  python docops.py --workspace <작업 폴더> files     MCP와 같은 폴더·서버로 CLI 실행
  python docops.py status                    준비 상태
  python docops.py parse "C:\\docs\\a.pdf"   첫 인자는 필수 인자, 나머지는 --이름 값
  python docops.py verify D12                원본과 자동 대조(의심 지점 S번호)
  python docops.py source D12 --page 3       원본 글자(파서와 별개) / read D12 --page 3: 파싱 결과
  python docops.py flag D12 --spot S3        사람이 원문 대조로 볼 곳(검수 요청 V번호)
  python docops.py verdicts --state wrong    사람이 '틀림'으로 판정한 것

표준 라이브러리만 쓰므로 가상환경 없이 Python 3.12 이상이면 실행된다.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings, load_dotenv  # noqa: E402
from app.agent.ops import REQUIRED, TOOL_ARGS, Ops  # noqa: E402


def make_ops() -> Ops:
    load_dotenv()
    settings = Settings.from_env()
    return Ops(settings.runtime_dir, settings.runtime_id)


def cli(argv: list[str]) -> int:
    if argv[:1] == ["--workspace"]:
        from app.agent.diagnostics import workspace_server
        if len(argv) < 3:
            print("사용법: docops.py --workspace <작업 폴더> <도구> [인자]")
            return 2
        try:
            env = workspace_server(Path(argv[1]).expanduser()).get("environment", {})
            for key in ("DOCOPS_AGENT_ROOTS", "DOCOPS_RUNTIME_DIR", "DOCOPS_API_URL", "DOCOPS_AGENT_WAIT_SECONDS",
                        "DOCOPS_AGENT_CONFIRM_OVER"):
                if key in env:
                    os.environ[key] = env[key]
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            print(f"[error] docops 작업 폴더 설정을 읽지 못했습니다 ({type(exc).__name__}).")
            return 2
        argv = argv[2:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("도구: " + ", ".join(TOOL_ARGS))
        return 0
    name, rest = argv[0], argv[1:]
    if rest in (["--help"], ["-h"]) and name in TOOL_ARGS:
        from app.agent.mcp import TOOLS
        spec = next(tool for tool in TOOLS if tool["name"] == name)
        print(f"{name} — {spec['description']}")
        for key, details in spec["inputSchema"]["properties"].items():
            print(f"  --{key}  {details.get('description', '')}")
        return 0
    args, positional = {}, []
    index = 0
    while index < len(rest):
        item = rest[index]
        if item.startswith("--"):
            key, equals, value = item[2:].partition("=")
            if not equals:
                if index + 1 < len(rest) and not rest[index + 1].startswith("--"):
                    value = rest[index + 1]
                    index += 1
                else:
                    value = "true"
            args[key.replace("-", "_")] = value
        else:
            positional.append(item)
        index += 1
    if positional:
        first = REQUIRED.get(name) or (TOOL_ARGS.get(name) or [None])[0]
        if first is None or first in args:
            print("[error] 위치 인자가 중복되거나 이 도구에서 지원되지 않습니다.")
            return 2
        args[first] = " ".join(positional)
    ops = make_ops()
    try:
        text, is_error = ops.call(name, args)
    finally:
        ops.close()
    print(text)
    return 1 if is_error else 0


def _write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(text)
        except BaseException:
            handle.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def init_workspace(argv: list[str]) -> int:
    """OpenCode 작업 폴더(opencode.json + AGENTS.md)를 만든다. 경로는 이 PC 기준으로 자동으로 채운다."""
    parser = argparse.ArgumentParser(description="OpenCode 파서 전용 작업 폴더 설정")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--roots", help="허용할 문서 폴더. 여러 폴더는 운영체제 경로 구분자로 연결")
    args = parser.parse_args(argv)
    target = args.workspace.expanduser().resolve()
    repo = Path(__file__).resolve().parent.parent
    managed = target == repo / "OpenCode"
    if not managed and (target == repo or repo in target.parents or target in repo.parents):
        print("[error] 저장소와 별도의 작업 폴더를 골라 주세요.")
        return 2
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / "opencode.json"
    if (target / "opencode.jsonc").is_file():
        print("[error] 이 폴더에는 opencode.jsonc가 있습니다. 파서 전용 새 폴더를 지정하고 기존 모델 설정을 연결하세요.")
        return 2
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {"$schema": "https://opencode.ai/config.json"}
    mcp = config.setdefault("mcp", {})
    native = "servers" in mcp or "providers" in config or "permissions" in config
    servers = mcp.setdefault("servers", {}) if native else mcp
    previous_env = servers.get("docops", {}).get("environment", {})
    environment = {**previous_env, "DOCOPS_AGENT_WAIT_SECONDS": "40"}
    if args.roots is not None:
        from app.folder_import import root_candidates, resolve_roots

        candidates, default = root_candidates({"DOCOPS_AGENT_ROOTS": args.roots})
        _, notes = resolve_roots(candidates)
        if default or not candidates:
            print("[error] --roots에 문서 폴더를 넣으세요.")
            return 2
        for note in notes:
            print(f"[주의] {note}")
        environment["DOCOPS_AGENT_ROOTS"] = os.pathsep.join(str(root.resolve()) for root in candidates)
    elif not environment.get("DOCOPS_AGENT_ROOTS"):
        environment.pop("DOCOPS_AGENT_ROOTS", None)
    # 작업 폴더에서 띄운 MCP도 콘솔과 같은 저장소를 찾는다.
    if managed:
        environment["DOCOPS_RUNTIME_DIR"] = str(Settings.from_env().runtime_dir)
    else:
        environment.setdefault("DOCOPS_RUNTIME_DIR", str(Settings.from_env().runtime_dir))
    # MCP 요청 시간 제한(기본 5초)을 늘리고, 도구 쪽 대기 시간도 그 안에서 맞춘다.
    servers["docops"] = {
        "type": "local", "command": [sys.executable, str(Path(__file__).resolve()), "mcp"],
        "environment": environment,
        **({"codemode": False, "timeout": {"execution": 120000}} if native else {"enabled": True, "timeout": 120000}),
    }
    if native:
        rules = [{"action": action, "resource": "*", "effect": effect} for action, effect in (("*", "deny"), ("docops_*", "allow"))]
        config["permissions"] = [rule for rule in config.get("permissions", []) if rule not in rules] + rules
    else:
        config.setdefault("permission", {})
        # OpenCode는 마지막으로 일치하는 권한을 사용한다. 재실행 때도 전용 규칙을 마지막에 둔다.
        for rule, effect in (("*", "deny"), ("docops_*", "allow")):
            config["permission"].pop(rule, None)
            config["permission"][rule] = effect
        # 구버전에서 tools가 permission보다 우선하는 경우를 위해 기존 항목을 보존한다.
        disabled = ("write", "edit", "patch", "bash", "webfetch", "websearch", "task", "read", "glob", "grep", "list")
        config["tools"] = {**config.get("tools", {}), **dict.fromkeys(disabled, False)}
    config["share"] = "disabled"
    guide = (repo / "opencode-workspace" / "AGENTS.md").read_text(encoding="utf-8")
    guide_path = target / "AGENTS.md"
    if guide_path.exists():
        prior = guide_path.read_text(encoding="utf-8")
        legacy = hashlib.sha256(prior.encode()).hexdigest() == "9ba41f70a3ae4a79aa665d2a509de757b1067574b3bad58bb88ae13ad414fb16"
        if prior != guide and not legacy and not prior.startswith("<!-- docops-managed -->"):
            guide_path = target / "DOCOPS_GUIDE.md"
            if guide_path.exists() and not guide_path.read_text(encoding="utf-8").startswith("<!-- docops-managed -->"):
                print("[error] 기존 DOCOPS_GUIDE.md를 보존했습니다. 새 작업 폴더를 지정하세요.")
                return 2
            config["instructions"] = list(dict.fromkeys([*config.get("instructions", []), guide_path.name]))
    _write_text(guide_path, guide)
    _write_text(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"[ok] {config_path}")
    print(f"[ok] {guide_path}")
    if not environment.get("DOCOPS_AGENT_ROOTS"):
        print("[안내] 문서 폴더는 콘솔 .env 설정을 따릅니다. 미설정 시 samples를 씁니다.")
    print("모델 연결(base_url·model·api_key)은 기존 OpenCode 전역 설정을 그대로 씁니다. OpenCode Desktop에서 이 폴더를 여세요.")
    return 0


def main() -> int:
    if sys.platform == "win32":
        # 콘솔 코드 페이지와 무관하게 한글이 깨지지 않게 한다(MCP는 바이트로 직접 쓴다).
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from app.agent.mcp import serve
        ops = make_ops()
        try:
            serve(ops)
        finally:
            ops.close()
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "init-workspace":
        try:
            return init_workspace(sys.argv[2:])
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            print(f"[error] 작업 폴더 설정을 확인하세요 ({type(exc).__name__}).")
            return 2
    if sys.argv[1:2] == ["doctor"]:
        from app.agent.diagnostics import doctor
        return doctor(sys.argv[2:], Path(__file__))
    return cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
