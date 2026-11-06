"""Minimal system registry for the benchmark runner.

A system has triage(report_path, ws, repo) returning a dict with at least:
verdict, confidence, tool_calls, tokens, latency_s.
"""
REGISTRY = {}


class Skipped(Exception):
    """Raised when a system cannot run here (for example, no API key)."""


class System:
    name = ""
    description = ""

    def triage(self, report_path, ws, repo):
        raise NotImplementedError


def register(name, needs_llm=False):
    def deco(cls):
        cls.name, cls.needs_llm = name, needs_llm
        REGISTRY[name] = cls
        return cls
    return deco


def build(name):
    if name not in REGISTRY:
        raise KeyError("unknown system %r; known: %s" % (name, ", ".join(sorted(REGISTRY))))
    return REGISTRY[name]()
