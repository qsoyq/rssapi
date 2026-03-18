import logging
import re
from typing import cast

import markdown
from markdown import Markdown
from markdown.blockprocessors import HashHeaderProcessor
from markdown.extensions import Extension

logger = logging.getLogger(__file__)


class StrictHashHeaderProcessor(HashHeaderProcessor):
    """Only treat `#` as a header when followed by a space (e.g. `# Title`, not `#1`)."""

    RE = re.compile(r"(?:^|\n)(?P<level>#{1,6})[ ](?P<header>(?:\\.|[^\\])*?)#*(?:\n|$)")


class StrictHashHeaderExtension(Extension):
    """Strictly enforce that `#` headers must be followed by a space."""

    def extendMarkdown(self, md: Markdown) -> None:
        md.parser.blockprocessors.deregister("hashheader")
        md.parser.blockprocessors.register(StrictHashHeaderProcessor(md.parser), "hashheader", 70)


def markdown_parse(text: str) -> str:
    try:
        return cast(str, markdown.markdown(text, extensions=[StrictHashHeaderExtension()]))
    except Exception as e:
        logger.warning(f"failed to parse markdown: {e}")
        return text
