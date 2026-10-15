"""Shared Wiki text coordinates and unsuffixed heading normalization."""
import re


def physical_lines(text, keepends=False):
    """Split only CR/LF, preserving original terminators when requested.

    Unicode separators such as U+0085/U+2028 stay inside their physical line.
    As with editor line counts, a final newline adds no extra empty line.
    """
    if keepends:
        return re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)[:-1]
    lines = re.split(r"\r\n|\r|\n", text)
    if lines[-1] == "":
        lines.pop()
    return lines


def normalize_anchor(title):
    """Return the base slug; sections() owns collision suffixes."""
    plain = re.sub(r"[`*_]", "", title).lower()
    return "".join(c for c in plain if c.isalnum() or c in " -_").replace(" ", "-")
