读取 `/root/input.docx`，提取其中的所有段落文本（按文档顺序）以及所有内嵌图片的二进制内容，并写出 JSON 到 `/root/result.json`，结构如下：

```json
{
  "paragraphs": ["第一段", "第二段", ...],
  "images": [
    {"sha256": "<图片字节的 sha256 十六进制>", "size": <字节数>}
  ]
}
```

要求：
- `paragraphs` 必须按文档中出现的顺序，且仅包含非空段落文本（去掉首尾空白后非空）。
- `images` 列出 DOCX 中所有内嵌图片，按它们在 `word/media/` 中的字典序排列；`sha256` 是图片原始字节的 SHA-256 十六进制小写串，`size` 是字节数。
- 严禁读取 `/root/input.docx` 之外的任何文件。
