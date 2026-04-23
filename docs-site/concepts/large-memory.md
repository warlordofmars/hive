# Large memory — text, images, and blobs

Hive stores three kinds of non-standard memory alongside ordinary inline text. Understanding the distinction helps you choose the right tool and set accurate expectations for retrieval behaviour.

## Memory value types

| `value_type` | Stored where | How it arrives | Max size |
| --- | --- | --- | --- |
| `text` | DynamoDB (inline) | `remember` with a short value | ~100 KB |
| `text-large` | S3 (auto-promoted) | `remember` with a long value | No hard limit\* |
| `image` | S3 | `remember_blob` with an `image/*` MIME type | 10 MB |
| `blob` | S3 | `remember_blob` with any other MIME type | 10 MB |

\* Practical upper bound is the Lambda request payload size (~6 MB for synchronous invocations). Large documents should be split into sections.

## Inline threshold — when text spills to S3

When you call `remember` with a text value, Hive checks the encoded byte length against a 100 KB threshold:

- **≤ 100 KB** — stored inline in DynamoDB as `value_type="text"`. Retrieval is a single `GetItem`.
- **> 100 KB** — stored in S3 as `value_type="text-large"`. The DynamoDB item holds metadata only; the value is fetched from S3 when you `recall` the key.

The promotion to `text-large` is **transparent**: you call `remember` and `recall` exactly as before. The only observable differences are:

- `list_memories` omits the inline value for `text-large` memories (it shows metadata only).
- Retrieval adds a small S3 latency (~50–200 ms) on top of the DynamoDB read.

## Binary memories — images and blobs

Use [`remember_blob`](/tools/remember_blob) to store images, PDFs, audio, or any other binary content. Pass the bytes as standard Base64 and specify a MIME type.

Hive routes by MIME prefix:

- `image/*` (e.g. `image/png`, `image/jpeg`) → `value_type="image"`
- Everything else (e.g. `application/pdf`, `audio/mpeg`) → `value_type="blob"`

Both subtypes are stored in S3. A binary memory has no inline `value` — the management UI and `recall` fetch the bytes directly from S3.

## Semantic search

Semantic search (via `search_memories`) operates on **text embeddings**:

| `value_type` | Embedded? | Notes |
| --- | --- | --- |
| `text` | Yes | Full inline value is embedded |
| `text-large` | No | S3 content is not embedded (no vectors for large text) |
| `image` | No | Binary content is not embedded |
| `blob` | No | Binary content is not embedded |

`text-large` and binary memories are excluded from semantic search results. They are still reachable via `recall` (by key) and `list_memories` (by tag).

## Size limits summary

| Limit | Value |
| --- | --- |
| Inline text threshold (auto S3 promotion) | 100 KB |
| Maximum blob / `remember_blob` payload | 10 MB |
| DynamoDB item ceiling (hard) | 400 KB |

## Related pages

- [`remember`](/tools/remember) — store text memories (handles text-large transparently)
- [`remember_blob`](/tools/remember_blob) — store binary content
- [`recall`](/tools/recall) — retrieve any memory by key
- [Memory Browser](/ui-guide/memory-browser) — view and download large memories in the UI
