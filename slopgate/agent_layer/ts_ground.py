"""Tree-sitter grounding for C and C headers: the same record ground.find_symbol returns,
computed from a real syntax tree instead of line regexes.

What the regex scan gets wrong and this gets right (each has a test in tests/test_ts_ground.py):

  * curl style definitions, return type on its own line:      CURLcode\\nCurl_http_done(...)\\n{
    regex: MENTIONED (so the adjudicator says HALLUCINATED about real code);  here: DEFINED
  * function-like macros:  #define Curl_safefree(p) ...     regex: MENTIONED;  here: DEFINED (kind "macro")
  * prototypes:  static int f(void);   regex counts them as definitions and as callers;  here: neither
  * a definition is reported at the line of its name, not wherever a multi-line regex match began

A "mention" is any line containing the name; it is "in code" unless every occurrence on that line
lies inside a comment, string literal or char literal node. Callers are call_expression nodes whose
function is exactly the identifier.

Optional dependency. If tree_sitter / tree_sitter_c are not installed, available() is False and
ground.py keeps using the regex scan. Selected by SLOPGATE_PARSER = regex (default) | treesitter | auto.
"""
import hashlib

try:                                              # pragma: no cover - import guard
    import tree_sitter
    import tree_sitter_c
    _LANG = tree_sitter.Language(tree_sitter_c.language())
    try:
        _PARSER = tree_sitter.Parser(_LANG)
    except TypeError:                             # older bindings: Parser() then set_language
        _PARSER = tree_sitter.Parser()
        _PARSER.set_language(_LANG)
    IMPORT_ERROR = None
except Exception as e:  # noqa: BLE001
    _LANG = _PARSER = None
    IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

TS_EXT = (".c", ".h")
CHECKED_BY = "tree-sitter C syntax tree (definitions, calls, comments and strings from the parse)"
NON_CODE = {"comment", "string_literal", "char_literal", "system_lib_string", "concatenated_string"}
_DECL_WRAPPERS = {"pointer_declarator", "parenthesized_declarator", "attributed_declarator",
                  "function_declarator", "array_declarator"}
_CACHE_MAX = 512
_cache = {}


def available():
    return _PARSER is not None


def parse(src):
    """(tree, source bytes). Cached on content, so repeated lookups over one checkout parse once."""
    b = src.encode("utf-8", errors="replace")
    key = hashlib.sha1(b).hexdigest()
    hit = _cache.get(key)
    if hit is None:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        hit = _cache[key] = (_PARSER.parse(b), b)
    return hit


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _text(node, b):
    return b[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def function_name(defn):
    """The identifier node a function_definition defines, through pointer / paren declarators."""
    d = defn.child_by_field_name("declarator")
    while d is not None and d.type in _DECL_WRAPPERS:
        nxt = d.child_by_field_name("declarator")
        if nxt is None:
            nxt = next((c for c in d.named_children if c.type in _DECL_WRAPPERS | {"identifier"}), None)
        d = nxt
    return d if d is not None and d.type == "identifier" else None


def scan(src, rel, sym):
    """-> (mentions, definitions, callers) for one file, in ground.find_symbol's shapes."""
    tree, b = parse(src)
    sb = sym.encode()
    non_code, defs, callers = [], [], []
    for n in _walk(tree.root_node):
        t = n.type
        if t in NON_CODE:
            non_code.append((n.start_byte, n.end_byte))
        elif t == "function_definition":
            name = function_name(n)
            if name is not None and _text(name, b) == sym:
                defs.append({"file": rel, "line": name.start_point[0] + 1, "kind": "function"})
        elif t == "preproc_function_def":
            name = n.child_by_field_name("name")
            if name is not None and _text(name, b) == sym:
                defs.append({"file": rel, "line": name.start_point[0] + 1, "kind": "macro"})
        elif t == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None and fn.type == "identifier" and _text(fn, b) == sym:
                callers.append({"file": rel, "line": fn.start_point[0] + 1})

    def in_code(pos):
        return not any(s <= pos and pos + len(sb) <= e for s, e in non_code)

    mentions, off = [], 0
    for i, line in enumerate(b.split(b"\n"), 1):
        j = line.find(sb)
        if j >= 0:
            code = False
            while j >= 0 and not code:
                code = in_code(off + j)
                j = line.find(sb, j + 1)
            mentions.append({"file": rel, "line": i, "in_code": code})
        off += len(line) + 1
    return mentions, defs, callers


def enclosing_function(src, line):
    """Name of the innermost function definition that contains 1-based `line`, else None."""
    tree, b = parse(src)
    row, best = line - 1, None
    for n in _walk(tree.root_node):
        if n.type == "function_definition" and n.start_point[0] <= row <= n.end_point[0]:
            if best is None or n.start_byte >= best.start_byte:
                best = n
    name = function_name(best) if best is not None else None
    return _text(name, parse(src)[1]) if name is not None else None
