读取 /root/input.md 的内容，并将结果写入 /root/result.json。

要求：
- 输出 JSON 包含字段 `content`，其值为该 Markdown 文件的完整原始文本（保留换行与所有 Markdown 标记）。
- 输出 JSON 包含字段 `line_count`，其值为文件的总行数（按 `\n` 切分后的行数）。
- 输出 JSON 包含字段 `headings`，其值为一个字符串列表，按出现顺序列出所有以 `#` 开头的标题行的标题文本（去掉前导 `#` 与空格）。

请确保对 UTF-8 编码（含非 ASCII 字符）正确处理。
