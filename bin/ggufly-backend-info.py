#!/usr/bin/env python3
"""Parse llama-server help declarations without treating prose as options."""
import json
import re
import sys
from collections import defaultdict

FLAG = r'--?[A-Za-z0-9][A-Za-z0-9_-]*'
ALIASES = rf'{FLAG}(?:\s*,\s*{FLAG})*(?:\s*,)?'
DECLARATION = re.compile(
    rf'^(?P<indent> *)(?P<aliases>{ALIASES})(?P<tail>.*)$')

# Strip CSI and OSC ANSI sequences while leaving ordinary help text intact.
ANSI_RE = re.compile(
    r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|\\)')

# Usage tokens cover metavariables, optional/enum forms, ranges, and the
# composite forms emitted by current llama.cpp help (for example
# <tensor name pattern>=<buffer type>,... and [<repo>/]<model>[:quant]).
ELLIPSIS = r'(?:[,…]|\.\.\.)*'
ANGLE = r'<[^>\r\n]*>(?:=[^,\r\n]*)?' + ELLIPSIS
SQUARE = r'\[[^\]\r\n]*\](?:[=/][^,\s]*)?' + ELLIPSIS
BRACED = r'\{[^}\r\n]*\}' + ELLIPSIS
UPPER_META = r'[A-Z][A-Z0-9_+./:=()-]*(?:,[^\s]*)*'
ENUM_VALUE = r'[a-z][a-z0-9_-]*(?:[,:|/=][^\s]+)+'
HYPHEN_RANGE = r'[a-z][a-z0-9_-]*-[a-z0-9_-]+'
USAGE_ATOM = rf'(?:{ANGLE}|{SQUARE}|{BRACED}|{UPPER_META}|{ENUM_VALUE}|{HYPHEN_RANGE})'
USAGE_TOKEN_RE = re.compile(rf'{USAGE_ATOM}(?:[ \t]*[=/]?[ \t]*{USAGE_ATOM})*')
ARGUMENT_ONLY_RE = re.compile(rf'^{USAGE_ATOM}(?:[ \t]*[=/]?[ \t]*{USAGE_ATOM})*$')
USAGE_RE = re.compile(r' {2,}')
SECTION_RE = re.compile(r'^\s*-{3,}.*-{3,}\s*$')
REMOVED_RE = re.compile(
    r'\b(?:argument|option|flag)\s+'
    r'(?:(?:has|have)\s+(?:now\s+)?been|was|is|has\s+been|is\s+now)?\s*removed\b'
    r'|\b(?:has|have)\s+(?:now\s+)?been\s+removed\b'
    r'|\b(?:was|is)\s+(?:now\s+)?removed\b'
    r'|\bno longer (?:available|supported)\b',
    re.IGNORECASE)


def _usage_token(text):
    match = USAGE_TOKEN_RE.match(text)
    return match.group(0) if match else None


def _usage_prefix(text):
    """Return an argument-only usage prefix, or None for prose."""
    first = _usage_token(text)
    if first is None:
        return None

    # A few real declarations have two uppercase metavariables (START END).
    # Do not consume ordinary capitalized prose after one metavariable.
    tokens = [first]
    remainder = text[len(first):].lstrip()
    if re.fullmatch(UPPER_META, first):
        while True:
            next_token = _usage_token(remainder)
            if next_token is None or not re.fullmatch(UPPER_META, next_token):
                break
            tokens.append(next_token)
            remainder = remainder[len(next_token):].lstrip()
    return ' '.join(tokens)


def parse_rest(rest):
    """Split a declaration tail into usage and description.

    llama-server aligns descriptions in a fixed column.  Requiring that
    column, or an argument-only tail, prevents prose such as "--example N is
    mentioned in prose" from becoming an advertised option.
    """
    if not rest.strip():
        return '', ''

    separator = USAGE_RE.search(rest)
    if separator:
        usage = rest[:separator.start()].strip()
        description = rest[separator.end():].strip()
        return usage, description

    stripped = rest.strip()
    usage = _usage_prefix(stripped)
    if usage is not None and stripped == usage:
        return usage, ''
    return None


def _extract_values(usage):
    """Extract enum-like values from optional/enum usage forms."""
    if not re.search(r'[,|{}\[\]]', usage):
        return []
    values = re.findall(
        r'(?<![\w-])(?:[a-z][a-z0-9_-]*|\d+)(?![\w-])', usage)
    return list(dict.fromkeys(values))


def _description_column(match):
    separator = USAGE_RE.search(match['tail'])
    if separator is None:
        return None
    return len(match['indent']) + separator.end()


def _candidate_strength(rest):
    if not rest.strip() or USAGE_RE.search(rest):
        return 2
    return 1


def inspect_help(text):
    text = ANSI_RE.sub('', text)
    lines = text.expandtabs(8).splitlines()

    # Discover the declaration column from syntactically plausible lines.
    # Grouping by indentation avoids letting one prose line at column zero
    # pull an indented help block down to the wrong baseline.
    candidates = defaultdict(list)
    for line in lines:
        match = DECLARATION.match(line)
        if not match:
            continue
        if parse_rest(match['tail']) is None:
            continue
        candidates[len(match['indent'])].append(
            (match, _candidate_strength(match['tail'])))
    if not candidates:
        return {}

    baseline = min(
        candidates,
        key=lambda indent: (-len(candidates[indent]),
                            -sum(strength for _, strength in candidates[indent]),
                            indent))

    options = {}
    current = None
    for line in lines:
        match = DECLARATION.match(line)
        if match and len(match['indent']) == baseline:
            parsed = parse_rest(match['tail'])
            if parsed is None:
                current = None
                continue
            usage, description = parsed
            current = {'usage': usage, 'description': description}
            for flag in re.findall(FLAG, match['aliases']):
                options[flag] = current
            continue

        if current is None:
            continue
        if not line.strip():
            continue
        if SECTION_RE.match(line):
            current = None
            continue
        leading = len(line) - len(line.lstrip(' '))
        if leading > baseline:
            continuation = line.strip()
            if continuation:
                if current['description']:
                    current['description'] += '\n' + continuation
                else:
                    current['description'] = continuation
        else:
            current = None

    for option in options.values():
        option['removed'] = bool(REMOVED_RE.search(option['description']))
        option['values'] = _extract_values(option['usage'])
    return options


if __name__ == '__main__':
    json.dump(inspect_help(sys.stdin.read()), sys.stdout)
    print()