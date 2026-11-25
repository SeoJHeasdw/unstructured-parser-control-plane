"""작업 도구 진입점. 콘솔 서버(run.cmd·run.sh)가 켜져 있어야 한다.

  python docops.py init-workspace <폴더> --roots "<문서 폴더>"   OpenCode 작업 폴더 만들기
  python docops.py mcp                       OpenCode 등 MCP 클라이언트용 stdio 서버
  python docops.py status                    준비 상태
  python docops.py parse "C:\\docs\\a.pdf"   첫 인자는 필수 인자, 나머지는 --이름 값
  python docops.py read D12 --page 3
  python docops.py report --scope last

표준 라이브러리만 쓰므로 가상환경 없이 Python 3.12 이상이면 실행된다.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings, load_dotenv  # noqa: E402
from app.agent.ops import REQUIRED, TOOL_ARGS, Ops  # noqa: E402


def make_ops() -> Ops:
    load_dotenv()
    settings = Settings.from_env()
    return Ops(settings.runtime_dir, settings.runtime_id)


def cli(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("도구: " + ", ".join(TOOL_ARGS))
        return 0
    name, rest = argv[0], argv[1:]
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
        if first:
            args.setdefault(first, " ".join(positional))
    text, is_error = make_ops().call(name, args)
    print(text)
    return 1 if is_error else 0


def init_workspace(argv: list[str]) -> int:
    """OpenCode 작업 폴더(opencode.json + AGENTS.md)를 만든다. 경로는 이 PC 기준으로 자동으로 채운다."""
    import json

    if not argv or argv[0].startswith("--"):
        print('사용법: python docops.py init-workspace <작업 폴더> --roots "<문서 폴더>[;<문서 폴더2>]"')
        return 2
    target = Path(argv[0]).expanduser().resolve()
    roots = ""
    if "--roots" in argv:
        index = argv.index("--roots")
        roots = argv[index + 1] if index + 1 < len(argv) else ""
    repo = Path(__file__).resolve().parent.parent
    if target == repo or repo in target.parents:
        print("[error] 작업 폴더는 저장소 밖에 만들어 주세요(에이전트가 코드를 보지 않게).")
        return 2
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / "opencode.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {"$schema": "https://opencode.ai/config.json"}
    # MCP 요청 시간 제한(기본 5초)을 늘리고, 도구 쪽 대기 시간도 그 안에서 맞춘다.
    config.setdefault("mcp", {})["docops"] = {
        "type": "local",
        "command": [sys.executable, str(Path(__file__).resolve()), "mcp"],
        "environment": {"DOCOPS_AGENT_ROOTS": roots, "DOCOPS_AGENT_WAIT_SECONDS": "40"},
        "enabled": True,
        "timeout": 120000,
    }
    # 실험·보고만 한다: 파일 수정·셸·웹을 끈다. 고를 도구가 적을수록 중형 모델이 덜 헤맨다.
    config["permission"] = {"edit": "deny", "bash": "deny", "webfetch": "deny", "websearch": "deny",
                            "task": "deny", "external_directory": "deny", "skill": "deny"}
    config["tools"] = {"write": False, "edit": False, "patch": False, "bash": False, "webfetch": False,
                       "websearch": False, "task": False, "read": False, "glob": False, "grep": False, "list": False}
    config["share"] = "disabled"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    guide = repo / "opencode-workspace" / "AGENTS.md"
    (target / "AGENTS.md").write_text(guide.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[ok] {config_path}")
    print(f"[ok] {target / 'AGENTS.md'}")
    if not roots:
        print("[주의] --roots 를 주지 않았습니다. opencode.json의 DOCOPS_AGENT_ROOTS에 문서 폴더를 넣어 주세요.")
    print("모델 연결(base_url·model·api_key)은 기존 OpenCode 전역 설정을 그대로 씁니다. OpenCode Desktop에서 이 폴더를 여세요.")
    return 0


def main() -> int:
    if sys.platform == "win32":
        # 콘솔 코드 페이지와 무관하게 한글이 깨지지 않게 한다(MCP는 바이트로 직접 쓴다).
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from app.agent.mcp import serve
        serve(make_ops())
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "init-workspace":
        return init_workspace(sys.argv[2:])
    return cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
