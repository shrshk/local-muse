"""Save a `temporal workflow show -o json` history from stdin as a replay fixture.

Usage: make history WF=<workflow id> NAME=<fixture name>
Record test runs only: payloads hold prompts and tool output, so read them before committing.
"""

import gzip
import json
import pathlib
import sys

HISTORIES = pathlib.Path(__file__).parent / "histories"


def main() -> None:
    workflow_id, name = sys.argv[1], sys.argv[2]
    history = json.load(sys.stdin)
    if not history.get("events"):
        sys.exit(f"no events for {workflow_id}")
    path = HISTORIES / f"{name}.json.gz"
    with gzip.open(path, "wt") as f:
        json.dump({"workflow_id": workflow_id, "history": history}, f, separators=(",", ":"))
    print(f"wrote {path} ({len(history['events'])} events)")


if __name__ == "__main__":
    main()
