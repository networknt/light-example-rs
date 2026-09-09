# Insurance claim MCP server

The example now uses `2026-07-28` stateless Streamable HTTP at POST /mcp.
It implements server/discover, tools/list and tools/call for the same five
business tools. There is no initialize, session store or DELETE lifecycle.
Responses carry cache hints or complete tool results, including structured
business output. Calls can alternate independent replicas without session
sharing. GET and DELETE on /mcp return 405.

Use the light-fabric mcp-client modern profile. Every request needs Accept:
application/json, text/event-stream; Content-Type: application/json;
MCP-Protocol-Version: 2026-07-28; Mcp-Method matching the JSON method; and params
_meta entries for io.modelcontextprotocol/protocolVersion and
io.modelcontextprotocol/clientCapabilities. tools/call also needs Mcp-Name.
The example has no annotated parameter headers. Invalid business inputs return
complete results with isError true; transport/contract failures return errors.

For Portal publication, merge these fields into the selected tool's toolMetadata
and set backendResource to the actual MCP endpoint:

```json
{
  "backendMcpProtocol": "stateless",
  "backendCredentialMode": "anonymous",
  "backendResource": "http://127.0.0.1:8087/mcp",
  "sessionIndependent": true,
  "runtime": { "allowPrivateTargetHost": true }
}
```

The anonymous/private-target example is for an approved internal demo endpoint.
Protected deployments use gateway authentication and an explicit backend
credential policy appropriate to their server. The example rejects browser
Origin headers, limits request bodies to 1 MiB and advertises no subscriptions,
MRTR, tasks or OAuth authorization server capabilities.

Migration: update clients to the modern profile and publish the explicit backend
metadata before directing gateway traffic here. Old initialize/session clients
must keep using their previous example binary until migrated. No live deployment
has been changed by this source update.

`cargo test --locked -p demo-insurance-claim-mcp-server` runs business regressions
and real-client TCP tests for all tools against two independent Axum servers and
the light-pingora MCP runtime behind an HTTP test adapter. The full Pingora HTTP
boundary is tested separately in light-fabric's live gateway suite.
