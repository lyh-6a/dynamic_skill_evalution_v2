读取 `/root/input.pptx`，按幻灯片顺序提取每张幻灯片中的全部文本内容。

将结果写入 `/root/result.json`，JSON 结构为：

```json
{
  "slide_count": <int>,
  "slides": [
    {"index": 1, "text": "<该幻灯片所有文本，按出现顺序用换行连接>"},
    {"index": 2, "text": "..."}
  ]
}
```

要求：
- `slides` 按幻灯片顺序排列，`index` 从 1 开始。
- 每张幻灯片的 `text` 字段需包含该页所有文本框/占位符里的文字（包括标题与正文），不同文本框之间用 `\n` 连接，原始字符（含非 ASCII）要保留。
- 不要混入其它幻灯片的内容。
