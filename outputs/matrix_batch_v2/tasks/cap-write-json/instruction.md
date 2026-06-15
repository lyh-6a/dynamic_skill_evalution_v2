Create a JSON file at /root/result.json with the following exact structure and values:

- A top-level object with keys: `title` (string), `count` (integer), `tags` (array of strings), `meta` (object).
- `title` must equal `Sample Report`.
- `count` must equal `3`.
- `tags` must equal `["alpha", "beta", "gamma"]` in that order.
- `meta` must be an object with keys `author` = `Alice` and `version` = `1`.

The file must be valid JSON (UTF-8) and decodable by `json.load`.
