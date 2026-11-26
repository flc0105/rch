# Go Client file transfer modes

The Go Client uses the same managed Transfer Center lifecycle and wire protocol
as the Python Client. The file-transfer mode is a **runtime Configuration**
setting, independent of the main connection's TCP/mTLS transport and
Reverse/Bind direction.

| `FILE_TRANSFER_MODE` | Behavior |
| --- | --- |
| `http_streaming` (default) | Existing Server Web HTTP upload/download |
| `tcp_streaming` | Independent authenticated RCH file-data socket, using the current session's TCP or mTLS transport |

Set the mode in the connected Client's Configuration view (under the Transfer
group), or with its existing Configuration `set` operation. Resetting the setting
restores `http_streaming`; only non-default overrides are persisted in the Go
Client's runtime configuration file. `HTTP_TRANSFER_BUFFER_SIZE` controls the
shared streaming buffer (default 1 MiB, range 64 KiB–16 MiB).

In Reverse, each TCP-streaming transfer dials the Server's active Listener;
in Bind, the Server dials the Go Client's existing Bind listening port. Each
auxiliary connection uses the existing session token and follows the same
mTLS identity verification when `mtls_tcp` was selected for the main session.
No new fixed discovery port or file-specific Listener is required.

Supported managed operations: Client-to-Server file, preview, directory ZIP,
ZIP entry and Server-to-Client file. Client-command file uploads (such as
`download` and `screenshot`) use the same transfer mode. TCP streams use the
shared file-control frame format, SHA-256 trailer, progress/cancel updates,
and the existing conflict-policy/commit checks. Older Go Client releases
remain on their own existing HTTP-only behavior until rebuilt.

Managed transfers belong to the active Client session. When the control
connection closes, the Client is intentionally stopped or relaunched, or
the inbound-message timeout expires, the Client cancels in-flight HTTP and TCP transfers and waits for their workers
to release temporary files and data sockets before admitting the next session.
Command-initiated TCP uploads registered with Transfer Center follow the same
session shutdown. Each replacement session receives its own transfer token.

`SERVER_INBOUND_TIMEOUT_SECONDS` is a runtime Connection setting, defaulting
to 120 seconds. Changes apply to the current Reverse or Bind session; set it
to `0` to disable inbound idle detection.

Reverse connection failures retry after 5, 10, 20, then at most 30 seconds;
receiving a valid session token resets the next retry to 5 seconds. A closed
connection or invalid identity is reported with its actual failure reason.
Bind remains a listening service rather than a dial/retry loop.
