读取 /root/input.xlsx，将其共享字符串中的每个字符串原样替换为 /root/translations.json 中对应的翻译（按索引顺序），保持工作表结构、单元格位置与单元格引用完全不变，并把结果写到 /root/output.xlsx。同时在 /root/result.json 中写入：{"output_path": "/root/output.xlsx"}。
