"""Evidence ledger: the agent's whole record of progress for one report.

Only the tool layer appends rows. A row is never edited, so a rationale that
cites E3 is citing something that actually ran.
"""
import json
import time


class Ledger:
    def __init__(self):
        self.rows = []

    def add(self, tool, args, result, by="planner"):
        row = {"id": "E%d" % (len(self.rows) + 1), "tool": tool, "args": dict(args),
               "result": result, "status": result.get("status", "INCONCLUSIVE"),
               "by": by, "t": round(time.time(), 3)}
        self.rows.append(row)
        return row

    def get(self, row_id):
        return next((r for r in self.rows if r["id"] == row_id), None)

    def find(self, tool, **match):
        return [r for r in self.rows if r["tool"] == tool
                and all(r["args"].get(k) == v for k, v in match.items())]


    def dump(self):
        return json.loads(json.dumps(self.rows, default=str))
