Read the JSON file at /root/pages.json. It contains a list under the key "pages"; each item is a string representing the full text content of one PDF page (in order). Produce a PDF file at /root/result.pdf such that:

1. The PDF is a valid, openable PDF file.
2. It has exactly the same number of pages as the length of the "pages" list, in the same order.
3. Each page contains the corresponding string as visible text (a substring match is sufficient).

Write only the PDF file at /root/result.pdf. Do not write any other files.
