# remember_blob

Store a binary memory — an image, document, audio file, or any other non-text content.

## Parameters

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `key` | string | Yes | Unique identifier for the memory. Same path-like convention as [`remember`](/tools/remember). |
| `data` | string | Yes | Standard Base64-encoded bytes of the binary content. |
| `content_type` | string | Yes | MIME type of the content, e.g. `image/png`, `application/pdf`. |
| `tags` | list of strings | No | Tags for grouping and retrieval. |

## Behaviour

- Content is stored in S3; only metadata is written to DynamoDB.
- If `content_type` starts with `image/` (e.g. `image/png`, `image/jpeg`, `image/webp`), the memory gets `value_type="image"`.
- All other MIME types produce `value_type="blob"`.
- Calling `remember_blob` with the same key again **replaces** the existing binary content (upsert semantics, same `memory_id`).
- The `data` payload (after Base64 decoding) must not exceed **10 MB**. In practice the deployed request path (CloudFront → Lambda) caps a single request body well below that, so **several-MB blobs are the realistic ceiling** for one call.

### Minimum renderable image size

When you store an `image/*` blob and later `recall` it, the client renders the returned bytes through an image API (Anthropic's, for Claude clients) that **rejects images below roughly a few dozen pixels per side**. A **32×32 image (or larger) renders**; a degenerate fixture such as a 1×1 or 16×16 PNG is stored and returned **byte-exact** by Hive, but the consuming client reports `Error processing image`. This is a client/API minimum, **not** a Hive limit — store real, sensibly-sized images.

## Examples

Store a PNG screenshot:

```
Store this screenshot as a memory with key "project/myapp/ui-screenshot".
Tag it "project" and "screenshot".
```

Store a PDF document:

```
Save this architecture PDF as "project/myapp/architecture-doc" with tag "docs".
```

## Limits

| Limit | Value |
| --- | --- |
| Maximum payload (decoded bytes) | 10 MB (single-request path caps lower; several MB is realistic) |
| Minimum renderable image | ~32×32 px — smaller images store byte-exact but won't render in clients |
| Supported MIME types | Any non-empty string (typically a MIME type such as `image/png`) |
| Key length | Up to 512 characters |

## Retrieval

Use [`recall`](/tools/recall) to retrieve a binary memory. For both `value_type="image"` and `value_type="blob"`, the tool returns an MCP `ImageContent` block whose `data` contains the Base64-encoded bytes and whose `mimeType` is set from the stored `content_type`. Non-image blobs (e.g. PDFs, audio) are still returned as `ImageContent` with `type="image"`; client implementations must use `mimeType` to determine the actual content type and must not assume the payload is an image.

Binary memories are not embedded, so they generally won't appear in semantic search (`search_memories`) results — retrieve them by key or tag only.

## Related tools

- [`remember`](/tools/remember) — store text (handles large text transparently via S3)
- [`recall`](/tools/recall) — retrieve any memory by key
- [`list_memories`](/tools/list-memories) — list memories by tag (shows metadata for binary memories)
