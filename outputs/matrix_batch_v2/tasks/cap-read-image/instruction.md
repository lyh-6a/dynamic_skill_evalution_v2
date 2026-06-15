Read the image at /root/input.png and extract its visible textual content.

Write a JSON file to /root/result.json with the following structure:

{
  "title": "<the title line shown at the top>",
  "lines": ["<line1>", "<line2>", ...]
}

- `title` must be the first/topmost line of text in the image.
- `lines` must be the list of all remaining visible text lines, in top-to-bottom order, each line as a single trimmed string.
- Preserve the exact wording and casing as shown in the image.
