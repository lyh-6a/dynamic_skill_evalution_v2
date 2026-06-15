Read the OpenDocument Text file at /root/input.odt and extract its plain text content.

Write a JSON file to /root/result.json with the following shape:

```
{
  "text": "<full plain text of the document, paragraphs joined by \n>"
}
```

Preserve paragraph order and the exact characters (including any non-ASCII characters) as they appear in the document.
