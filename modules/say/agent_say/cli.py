from __future__ import annotations
import argparse, json, sys, time
from agent_say.validate import SpecError, validate_request, resolve_wait
from agent_say.result import make_result, exit_code
from agent_say.ui_runner import run_ui
from agent_say.speak import speak_best_effort
from agent_say.read import main_read


def main_ask(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-say")
    p.add_argument("--file", help="request JSON path (default: stdin)")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--default", default=None)
    p.add_argument("--speak", action="store_true")
    args = p.parse_args(argv)
    try:
        raw = open(args.file).read() if args.file else sys.stdin.read()
        req = validate_request(json.loads(raw))
        if args.speak:
            req["speak"] = True
        wait = resolve_wait(
            {"wait": args.wait, "timeout": args.timeout, "default": args.default},
            options=req["options"],
        )
    except (SpecError, json.JSONDecodeError, OSError) as e:
        err = make_result("error", None, None, 0)
        print(json.dumps(err))
        print(f"agent-say: {e}", file=sys.stderr)
        return 1

    if req.get("speak"):
        speak_best_effort(req["title"], req.get("body") or "")

    t0 = time.monotonic()
    try:
        ui = run_ui(req, timeout_sec=wait["timeout_sec"])
        status = ui.get("status", "ok")
        choice = ui.get("choice")
        text = ui.get("text")
        if status not in ("ok", "cancelled", "error"):
            status = "ok"
    except KeyboardInterrupt:
        elapsed = int((time.monotonic() - t0) * 1000)
        result = make_result("cancelled", None, None, elapsed)
        print(json.dumps(result))
        return 130
    except TimeoutError:
        if wait.get("default"):
            status, choice, text = "ok", wait["default"], None
        else:
            status, choice, text = "timeout", None, None
    except Exception as e:
        print(f"agent-say: {e}", file=sys.stderr)
        status, choice, text = "error", None, None

    elapsed = int((time.monotonic() - t0) * 1000)
    result = make_result(status, choice, text, elapsed)
    print(json.dumps(result))
    return exit_code(status)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "read":
        return main_read(argv[1:])
    return main_ask(argv)


if __name__ == "__main__":
    raise SystemExit(main())
