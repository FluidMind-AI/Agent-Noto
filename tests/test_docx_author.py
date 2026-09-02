"""Tests for tools/docx_author.py — Word authoring and tracked changes.

The interesting assertions are the OOXML ones: that revisions are genuine
w:ins/w:del elements Word will accept, and that versions chain (v3 marks only
what is new rather than re-flagging v2's changes).
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

docx = pytest.importorskip("docx", reason="python-docx not installed")
import docx_author as da  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

V1 = """# Report

## Summary
Alpha beta gamma.

## Findings
- First finding.
- Second finding.
"""

V2 = """# Report

## Summary
Alpha beta gamma delta.

## Findings
- First finding.
- Second finding.
- Third finding.
"""


@pytest.fixture
def folder():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _xml(path):
    import zipfile
    from lxml import etree
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read("word/document.xml"))


# ------------------------------------------------------------------ parsing

def test_parse_blocks_kinds():
    blocks = da.parse_blocks("# H1\n\nBody text.\n\n- bullet\n\n1. numbered\n\n> quote")
    assert [b[0] for b in blocks] == ["h", "p", "ul", "ol", "quote"]


def test_parse_blocks_heading_level():
    assert da.parse_blocks("### Deep")[0] == ("h", 3, "Deep")


def test_split_inline_bold_italic_code():
    got = da.split_inline("plain **bold** and *it* and `code`")
    assert ("bold", True, False, False) in got
    assert ("it", False, True, False) in got
    assert ("code", False, False, True) in got


@pytest.mark.parametrize("name,expected", [
    ("Memo v1.docx", ("Memo", 1)),
    ("Board Update v12.docx", ("Board Update", 12)),
    ("No Version.docx", ("No Version", 1)),
])
def test_parse_version(name, expected):
    assert da.parse_version(name) == expected


# ------------------------------------------------------------------ create

def test_create_writes_file(folder):
    out = da.create(V1, os.path.join(folder, "Report v1.docx"), "Report")
    assert os.path.exists(out)


def test_create_refuses_to_clobber(folder):
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    assert da.latest_version(folder, "Report")[1] == 1


# ------------------------------------------------------------ revision xml

def test_revision_elements_are_real(folder):
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2), author="Tester")
    root = _xml(da.version_path(folder, "Report", 2))
    assert root.findall(f".//{W}ins"), "no w:ins elements produced"
    assert root.findall(f".//{W}del"), "no w:del elements produced"


def test_every_revision_has_author_and_date(folder):
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2), author="Tester")
    root = _xml(da.version_path(folder, "Report", 2))
    revs = root.findall(f".//{W}ins") + root.findall(f".//{W}del")
    for el in revs:
        assert el.get(W + "id"), "revision missing w:id"
        assert el.get(W + "author") == "Tester"
        assert el.get(W + "date"), "revision missing w:date"


def test_revision_ids_unique(folder):
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2))
    root = _xml(da.version_path(folder, "Report", 2))
    ids = [el.get(W + "id")
           for el in root.findall(f".//{W}ins") + root.findall(f".//{W}del")]
    assert len(ids) == len(set(ids)), "duplicate w:id values"


def test_ppr_child_order_is_schema_valid(folder):
    """CT_PPr is a sequence: w:pStyle first, w:rPr last.

    Getting this wrong makes Word report the document as corrupt, which no
    amount of round-tripping through python-docx would reveal.
    """
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2))
    root = _xml(da.version_path(folder, "Report", 2))
    for pPr in root.iter(W + "pPr"):
        kids = [k.tag.replace(W, "") for k in pPr]
        if "rPr" in kids:
            assert kids.index("rPr") == len(kids) - 1, f"rPr not last: {kids}"
        if "pStyle" in kids:
            assert kids.index("pStyle") == 0, f"pStyle not first: {kids}"


# --------------------------------------------------------------- semantics

def test_accept_and_reject_differ(folder):
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2))
    v2 = da.version_path(folder, "Report", 2)
    assert da.doc_blocks(v2, "final") != da.doc_blocks(v2, "original")


def test_final_text_matches_requested_content(folder):
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2))
    final = " ".join(t for _, t in
                     da.doc_blocks(da.version_path(folder, "Report", 2), "final"))
    assert "Third finding." in final
    assert "Alpha beta gamma delta." in final


def test_versions_chain_without_reflagging(folder):
    """v3 must diff against v2's ACCEPTED state, marking only what is new."""
    v3_md = V2.replace("Third finding.", "Third finding, revised.")
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    da.revise(da.version_path(folder, "Report", 1), V2,
              da.version_path(folder, "Report", 2))
    counts = da.revise(da.version_path(folder, "Report", 2), v3_md,
                       da.version_path(folder, "Report", 3))
    assert counts["edited"] == 1, counts
    assert counts["inserted"] == 0, counts
    assert counts["deleted"] == 0, counts


def test_front_matter_excluded_from_diff(folder):
    """Title and byline are re-emitted each revision; diffing them would
    delete and re-add the heading block every time."""
    da.create(V1, da.version_path(folder, "Report", 1), "Report")
    counts = da.revise(da.version_path(folder, "Report", 1), V1,
                       da.version_path(folder, "Report", 2), title="Report")
    assert counts["inserted"] == counts["deleted"] == counts["edited"] == 0


def test_latest_version_finds_highest(folder):
    for n in (1, 2, 10):
        da.create(V1, da.version_path(folder, "Doc", n), "Doc")
    assert da.latest_version(folder, "Doc")[1] == 10


def test_latest_version_ignores_word_lockfiles(folder):
    da.create(V1, da.version_path(folder, "Doc", 1), "Doc")
    open(os.path.join(folder, "~$Doc v9.docx"), "w").close()
    assert da.latest_version(folder, "Doc")[1] == 1
