Write a Markdown file to `/root/result.md` based on the structured content described in `/root/content.json`.

The Markdown file MUST contain, in this order:

1. A level-1 heading using the value of `title`.
2. A level-2 heading exactly equal to `Items`, followed by an unordered list (using `-` markers) of the strings in `items`, in the given order.
3. A level-2 heading exactly equal to `Scores`, followed by a GitHub-style Markdown table with header columns `Name | Score` (and the separator row `--- | ---`), one row per entry in `scores` (in the given order), where each row is `name | score`.

Use blank lines between blocks for readability. Do not add extra sections.
