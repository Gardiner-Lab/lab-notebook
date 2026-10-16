"""
A page's text (the cleaned HTML of a text block) as a small tree, for exports
to walk: the PDF writes it back out with links and pictures resolved, the Word
document turns it into paragraphs and runs.
"""

import html
from html.parser import HTMLParser
from typing import Dict, List, Optional, Union

VOID = {'br', 'hr', 'img'}
BLOCKS = {'p', 'h1', 'h2', 'h3', 'ul', 'ol', 'li', 'pre', 'blockquote', 'hr'}


class Node:
    def __init__(self, tag: str, attrs: Optional[Dict[str, str]] = None):
        self.tag = tag
        self.attrs: Dict[str, str] = dict(attrs or {})
        self.children: List[Union['Node', str]] = []

    def text(self) -> str:
        return ''.join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        """Every element below this one, depth first."""
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v or '' for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, {k: v or '' for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(source: str) -> Node:
    builder = _Builder()
    builder.feed(source or '')
    builder.close()
    return builder.root


def to_html(node: Union[Node, str]) -> str:
    """Write a tree (or a piece of it) back out as HTML."""
    if isinstance(node, str):
        return html.escape(node, quote=False)
    inner = ''.join(to_html(c) for c in node.children)
    if node.tag == 'root':
        return inner
    attrs = ''.join(f' {k}="{html.escape(v, quote=True)}"' for k, v in node.attrs.items() if v is not None)
    if node.tag in VOID:
        return f'<{node.tag}{attrs}>'
    return f'<{node.tag}{attrs}>{inner}</{node.tag}>'
