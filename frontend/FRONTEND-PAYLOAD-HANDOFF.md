# Frontend payload and future backend handoff

**Status:** Implemented frontend draft contract; future API details are proposals, not implemented endpoints.  
**Scope:** Question + one CSV → browser validation → a simple local readiness confirmation. No backend adapter. The schema is internal and documented for developers, not displayed on the page.  
**Related requirements:** [Project specification](../Sandboxed-AI-Inference-Project-Specification.md), especially §§4–7 and R1–R6.

## 1. What the frontend contributes

The frontend collects the user's intended analysis and original dataset, provides immediate structural feedback, and prepares a typed, inspectable handoff. It reduces avoidable intake mistakes and gives the team an integration contract to discuss.

It **does not** supply a trusted execution result, identity, authorization, executable Python, a Kubernetes manifest, or proof of sandbox isolation. Preparing a payload is not submitting a request.

| Frontend contribution                                  | Benefit to the future backend                               | Trust level                                   |
| ------------------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------- |
| User's question                                        | Input for server-side code generation and later explanation | Untrusted user data; validate again           |
| Original browser `File`                                | Dataset bytes for a future authorized upload                | Untrusted file; inspect and limit again       |
| Client-generated request UUID                          | A proposed request-correlation/idempotency input            | Not authentication or a server run ID         |
| File name, byte count, browser MIME and encoding claim | Intake display/debugging hints                              | Claims only; recompute/check server-side      |
| Parsed row count and normalized column names           | Useful local feedback and potential diagnostic hints        | Never a substitute for server parsing         |
| Internal prepared object                               | Makes the proposed handoff understandable and testable      | Not a wire upload; does not contain CSV bytes |

The UI deliberately provides no model selector, runtime/hypervisor option, image, command, dependency list, host path, network destination, service account, CPU/memory setting or execution deadline. Those are server-controlled decisions.

## 2. Exact implemented in-memory shape

`src/lib/submission.ts` exports the inferred `PreparedSubmission` type and `prepareSubmission` function. The caller first validates the question and inspects the file. The preparation function assembles metadata; it is not an independent security validator.

```ts
{
  attachment: File, // original selected File object; retained only in memory
  metadata: {
    schema_version: "1.0",
    client_request_id: string, // crypto.randomUUID(), fresh on each successful preparation
    question: string,          // outer whitespace trimmed
    file: {
      name: string,
      size_bytes: number,
      mime_type: string,       // File.type, or text/csv if the browser provides none
      encoding: "utf-8"
    },
    client_hints: {
      row_count: number,       // data rows only, ignoring fully blank records
      column_names: string[]  // header text trimmed for the local preview
    }
  }
}
```

### Illustrative metadata preview

The following is an example for the bundled synthetic CSV, not a live API response. A different UUID is generated when the user prepares a new draft.

```json
{
  "schema_version": "1.0",
  "client_request_id": "00000000-0000-4000-8000-000000000001",
  "question": "Which product had the largest absolute drop in sales from October to November?",
  "file": {
    "name": "sample-sales.csv",
    "size_bytes": 93,
    "mime_type": "text/csv",
    "encoding": "utf-8"
  },
  "client_hints": {
    "row_count": 4,
    "column_names": ["product", "month", "units"]
  }
}
```

**Important:** `JSON.stringify(File)` does not serialize its bytes. The metadata examples in this document/chat contain descriptors only, not the file bytes. There is no JSON inspector or clipboard action in the revised page. The attachment is not base64-encoded, embedded in the question, or included in a result. A future transport must explicitly send the original File bytes.

## 3. Actual frontend validation rules

These are implemented UX limits for this frontend, not certified security controls or approved production limits. The byte cap follows the research guide's proposed small-fixture starting point; the remaining structural caps are explicit frontend choices to review with backend owners.

| Input              | Implemented check                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------ |
| Question           | Non-empty after trimming; at most 4,000 JavaScript UTF-16 code units, checked before trimming    |
| Number of files    | Exactly one; multiple dropped files are rejected rather than silently picking the first          |
| Extension          | Case-insensitive `.csv`; MIME alone is not used to accept/reject                                 |
| Byte size          | Greater than zero and no more than 131,072 bytes / 128 KiB; checked before decoding              |
| Encoding           | Fatal UTF-8 decode; optional UTF-8 BOM accepted; UTF-16/invalid UTF-8 rejected                   |
| Control characters | Reject NUL and ASCII controls other than tab, CR and LF                                          |
| Format             | Explicit comma delimiter; quoted commas and quoted newlines parsed with Papa Parse               |
| Header             | At least one column; each trimmed name non-empty; exact case-sensitive uniqueness after trimming |
| Shape              | At least one data row; each nonblank record has the header's field count                         |
| Bounds             | At most 100 columns and 10,000 data rows                                                         |
| Preview            | Only the first five parsed data rows; all cell values remain strings                             |

Fully empty/whitespace-only records are ignored. An error's row number is a logical parsed-record position, not necessarily the physical line number when blank lines or quoted newlines occur. Blank individual cells are permitted; missing values and numeric/business semantics are backend/model concerns.

Header trimming affects local preview/hints only. **The original file bytes are not rewritten.** The backend must choose and document its own parsing/normalization policy and derive model metadata from that authoritative parsing, not trust client hints.

The frontend does not validate that a question is answerable from the CSV or that a future answer is mathematically correct. It does not execute formulas, JavaScript, Python, URLs or instructions appearing in cells. CSV formula-like values are displayed literally; a future spreadsheet-export feature would need a separate formula-injection policy.

## 4. How this fits the specification's future backend

Keep the specification's **two-operation flow** rather than treating this combined local draft as a new backend endpoint:

### Step A — upload the dataset

- Send `attachment` as a multipart file part to the future authenticated dataset-upload operation.
- The server enforces an upload byte cap before expensive parsing, parses/validates content independently, uses generated storage identifiers rather than filename-derived paths, binds ownership, and sets retention/expiry.
- The server returns its own owner-scoped `dataset_id`, authoritative columns, and expiry.
- MIME, filenames and client hints do not authorize access or establish content type.

### Step B — ask the agent

After a successful upload, the future request uses only the authorized server ID, question and optional client correlation token:

```json
{
  "dataset_id": "<server-issued dataset ID>",
  "question": "<validated question>",
  "client_request_id": "<client-generated correlation UUID>"
}
```

The server independently resolves the caller's access to that dataset. It then owns model calls, tool-envelope validation, a server-issued request/run ID, the fixed Kata Job template, staging, result validation, deadlines, cancellation, and cleanup.

No URLs, endpoint paths, HTTP client, multipart serializer, retry logic, polling, WebSocket, model adapter or Kubernetes adapter are implemented in this frontend. HTTP status codes, auth/CSRF handling, CORS, upload response shape, idempotency semantics and status transport still require a backend contract. These should not be guessed into the current application.

### Request correlation is not identity

The frontend's `client_request_id` is regenerated on each successful Check my request click. It identifies a local prepared draft, not a guaranteed exactly-once execution. A future integration should preserve one token across retries of the same submitted request and define its scope/expiry/conflict behavior on the server. The backend must generate canonical IDs and atomically reconcile duplicate dispatches.

## 5. Required future backend responsibilities

| Area                       | Backend must own                                                                                                                |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Identity and authorization | Authenticate caller; bind dataset ownership; authorize request/status/cancel lookup                                             |
| Intake                     | Bound bytes and parse costs; inspect encoding/shape; choose schema/normalization rules; assign storage identifiers; expire data |
| Model privacy              | Decide approved provider/data policy; send only permitted metadata/result values; protect provider credentials                  |
| Tool policy                | Accept only the fixed bounded tool envelope; do not accept frontend/model-chosen infrastructure fields                          |
| Execution                  | Dispatch generated code exclusively through the approved Kata template; fail closed on unavailable Kata                         |
| Resource/network policy    | Set CPU/memory/storage/time/concurrency/output limits and actual network/node enforcement                                       |
| Result integrity           | Read the intended Job/Pod/container outcome; validate bounded output; distinguish execution status from guest claims            |
| Recovery                   | Persist intent/outcome; handle duplicates/restarts; resolve cancellation races; reconcile cleanup                               |
| Client response            | Return stable status/error codes, validated result and optional final explanation—not raw guest HTML/logs                       |

Never turn `client_hints` directly into model-visible authoritative metadata. Never accept a user ID, dataset owner, service-account name or execution-success field from this client as truth.

## 6. Future response-side UI contract — not implemented

Once the backend exists, agree on request/status/cancel contracts before adding network behavior. The existing frontend could then display these server-owned phases:

- Dataset upload / accepted server dataset ID.
- Code generation.
- Execution queued / running / collecting.
- Answer generation.
- Completed with structured result and explanation, or a stable failure.
- Cancellation and cleanup status separately when relevant.

Do not show these as simulated states now. The implemented UI stops at **Your request is ready. — Nothing has been sent. Backend integration is not connected yet.** It has no result panel pretending that code ran.

## 7. Data lifetime and integration cautions

- Draft question, file, preview and prepared payload are in memory only. Reload/reset clears application references; this is not a secure-erasure guarantee for browser memory.
- Editing a question or selecting/removing/replacing a file invalidates the prepared payload. A new successful preparation gets a new UUID.
- A generation counter prevents a superseded asynchronous file read from restoring an old selection after reset or replacement.
- The revised interface does not display or copy the metadata schema. It prepares the original File and metadata in memory only; payload examples stay in developer documentation/chat.
- There is no analytics, remote font, external API request, localStorage, IndexedDB or cookie persistence in application code. A Vite development session still loads local assets and uses local development tooling; “no uploads” refers to user data, not an absence of browser asset traffic.
- No sample values are portrayed as execution results. The synthetic file/example question are convenience inputs only.
- Before real backend integration, update the local-only UI wording and review network behavior, provider disclosure, authentication, cancellation, retention and error display together.

## 8. Handoff checklist

- [ ] Approve final server upload caps and CSV normalization policy.
- [ ] Define authentication, upload/request/status/cancel operations and response schemas.
- [ ] Confirm `client_request_id` retry semantics and canonical server IDs.
- [ ] Implement upload first; replace local file metadata with authoritative server dataset binding.
- [ ] Revalidate and authorize independently on the server.
- [ ] Keep model/runtime/storage credentials and all Kubernetes settings off the client.
- [ ] Add real status/result UI only against real server responses; keep structured results visible beside explanations.
- [ ] Exercise M0–M4 and R1–R6 separately: browser tests do not prove Kata isolation.

This handoff does not modify the original specification or research guide.
