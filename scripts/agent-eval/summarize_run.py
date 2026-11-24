"""OpenCode --format json 이벤트 로그 요약: 도구 호출·인자·결과 첫 줄·최종 답."""
import json
import sys


def main(path: str) -> None:
    tools, texts, errors = [], [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        part = event.get("part") or {}
        kind = part.get("type") or event.get("type")
        if kind == "tool":
            state = part.get("state") or {}
            output = str(state.get("output") or state.get("error") or "")
            tools.append((part.get("tool"), json.dumps(state.get("input"), ensure_ascii=False), state.get("status"), output.split("\n", 1)[0][:110]))
        elif kind == "text" and part.get("text"):
            texts.append(part["text"])
        elif event.get("type") == "error" or "error" in event:
            errors.append(json.dumps(event, ensure_ascii=False)[:300])
    print(f"# {path.rsplit('/', 1)[-1]}  tool calls: {len(tools)}")
    for index, (name, args, status, first) in enumerate(tools, 1):
        print(f"{index:2}. {name} {args} [{status}] -> {first}")
    for error in errors:
        print("ERROR", error)
    print("--- final text ---")
    print(texts[-1][:2500] if texts else "(none)")


if __name__ == "__main__":
    for item in sys.argv[1:]:
        main(item)
        print()
