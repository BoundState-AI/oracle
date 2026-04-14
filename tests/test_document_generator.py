"""Tests for markdown-to-block parsing in the document generator."""
from oracle.document_generator import parse_markdown


def test_parse_markdown_preserves_basic_structure():
    md = """# Title

## Section

Paragraph one
continues here.

- bullet one
1. numbered one

```python
print("hi")
```
"""

    blocks = parse_markdown(md)

    assert [(block.kind, block.text) for block in blocks] == [
        ("h1", "Title"),
        ("h2", "Section"),
        ("paragraph", "Paragraph one continues here."),
        ("bullet", "bullet one"),
        ("numbered", "numbered one"),
        ("code", 'print("hi")'),
    ]
