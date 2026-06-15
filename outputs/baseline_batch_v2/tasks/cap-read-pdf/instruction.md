Read the PDF at `/root/input.pdf` and extract its textual content.

Write a JSON file to `/root/result.json` with the following schema:

```json
{
  "lines": ["<line 1>", "<line 2>", ...],
  "full_text": "<all lines joined by \n>"
}
```

Requirements:
- `lines` must be the non-empty text lines of the PDF in their natural top-to-bottom reading order.
- Preserve each line's exact characters (including digits, punctuation, and any non-ASCII characters).
- Do not invent, drop, or reorder lines.
