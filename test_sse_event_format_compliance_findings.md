# Test Failure Analysis: test_sse_event_format_compliance

**Date:** 2026-04-20  
**Test:** `tests/optional/capabilities/test_streaming_methods.py::test_sse_event_format_compliance`  
**Issue:** Test ONLY fails with gRPC transport on port 9999  

---

## Failure Details

**Error:**
```
grpc.aio._call.AioRpcError: <AioRpcError of RPC that terminated with:
    status = StatusCode.UNAVAILABLE
    details = "Socket closed"
    debug_error_string = "UNKNOWN:Error received from peer ipv4:127.0.0.1:9999 {grpc_status:14, grpc_message:"Socket closed"}"
>
```

**Location:** `tck/transport/grpc_client.py:534` in `send_streaming_message()`  
**Point of failure:** `async for response in stream:` - connection closes before any events are received

---

## Test Overview

### Specification Reference
- **A2A v0.3.0 §3.3.1** - SSE Event Format
- **Status:** MANDATORY if `capabilities.streaming = true`

### Test Purpose
Validates that SSE streaming events follow proper A2A format with correct object structures.

### Test Flow
1. Sends a streaming message request with text: "Test SSE event format"
2. Iterates through streaming events
3. Validates each event is a dictionary/object
4. Checks event structure based on type:
   - **Message events** (`kind: "message"`): Must have `role` and `parts` fields
   - **Status update events** (`kind: "status-update"`): Must have `taskId` field
   - **Artifact update events** (`kind: "artifact-update"`): Must have `taskId` and `artifact` fields
   - **Task objects**: Must have `id` and `status.state` fields
5. Processes at least 3 events (breaks after 3 to avoid consuming entire stream)
6. Asserts at least 1 event was received

---

## Transport Coverage

**YES** - This test runs on ALL transport protocols:
- ✅ **REST** - Uses SSE over HTTP at `/v1/message:stream`
- ✅ **JSON-RPC** - Uses `message/stream` method with SSE response
- ✅ **gRPC** - Uses `A2AService.SendStreamingMessage()` RPC call

The test uses the transport-agnostic `sut_client` fixture which delegates to the appropriate transport client based on configuration.

---

## Reproduction Commands for SUT Developer

### JSON-RPC (SSE over HTTP)
```bash
curl -N -X POST http://localhost:9999 \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/stream",
    "params": {
      "message": {
        "kind": "message",
        "messageId": "test-sse-format-debug-001",
        "role": "user",
        "parts": [{"kind": "text", "text": "Test SSE event format"}]
      }
    },
    "id": "test-request-001"
  }'
```

**Expected:** Server-sent events stream with `data: {...}` lines containing Task/Message/StatusUpdate objects

---

### REST (SSE over HTTP)
```bash
curl -N -X POST http://localhost:9999/v1/message:stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "message": {
      "messageId": "test-sse-format-debug-001",
      "role": "USER",
      "content": [{"text": "Test SSE event format"}]
    }
  }'
```

**Expected:** Server-sent events stream with Task/Message objects

---

### gRPC (requires grpcurl)
```bash
grpcurl -plaintext -d '{
  "request": {
    "message_id": "test-sse-format-debug-001",
    "role": "USER",
    "content": [{"text": "Test SSE event format"}]
  }
}' localhost:9999 a2a.v1.A2AService/SendStreamingMessage
```

**Expected:** Stream of protobuf responses with `task`, `status_update`, or `msg` payloads  
**Actual (failing):** Connection immediately closes with `UNAVAILABLE` status

---

## Working vs Failing Instances

| Port  | Version | gRPC Status |
|-------|---------|-------------|
| 9999  | 0.3.x   | ❌ FAILS - Socket closed immediately |
| 19999 | 0.3.x   | ✅ WORKS |
| 29999 | 0.3.x   | ✅ WORKS |

**Key observation:** ONLY port 9999 fails, and ONLY on gRPC transport. REST and JSON-RPC work fine on all ports.

---

## Root Cause Analysis

### CONFIRMED: This is a TCK Bug, NOT a SUT Bug

**The test PASSES when run in isolation but FAILS when run as part of the full test suite.**

### Root Cause
The TCK's `TransportManager` caches gRPC clients across tests (session scope), and the `GRPCClient` caches gRPC channels. This causes:

1. **Channel Reuse Across 27+ Tests**: All tests in the suite share the same gRPC channel
2. **Stream State Corruption**: After many streaming calls, the channel state becomes invalid
3. **SUT Correctly Rejects Invalid Request**: Server detects "Request stream 1 is not correct for server connection"
4. **Server Sends GOAWAY**: HTTP/2 GOAWAY frame with error code 1 (protocol error)

**Evidence from test run:**
```
WARNING: Unknown event structure: {'status_update': {'taskId': '...', 'status': {'state': 'submitted'}}}
WARNING: Unknown event structure: {'status_update': {'taskId': '...', 'status': {'state': 'working'}}}
ERROR: gRPC streaming call failed: UNAVAILABLE - Socket closed
Got goaway [1] err=UNAVAILABLE:GOAWAY received; Error code: 1; 
Debug Text: Request stream 1 is not correct for server connection
```

The test receives 2 events successfully, then the server closes the connection when it detects the protocol violation.

### TCK Code Issues

**Issue 1: Session-scoped transport manager caches clients**
- `conftest.py` line 188: `@pytest.fixture(scope="session")` for `transport_manager`
- `transport_manager.py` line 231-236: Returns cached client instances

**Issue 2: GRPCClient caches channels indefinitely**
- `grpc_client.py` line 316: `self._channel: Optional[grpc.Channel] = None`
- `grpc_client.py` line 322-331: Channel created once and reused

**Issue 3: Event format mismatch**
- gRPC client returns `{"status_update": {...}}` 
- Test expects `{"kind": "status-update", ...}`
- Events are processed but logged as "Unknown event structure"

### Likely Causes (PREVIOUSLY INVESTIGATED - NOT THE ACTUAL ISSUE)

1. **gRPC handler crash/panic**
   - Handler receives request but panics during processing
   - Check server logs for panic stack traces

2. **Request deserialization failure**
   - Protobuf message parsing fails silently
   - Handler doesn't properly validate incoming `SendMessageRequest`

3. **Missing streaming implementation**
   - Handler exists but doesn't properly use gRPC streaming response writer
   - May be returning early or not calling `stream.Send()`

4. **Server-side timeout or resource limit**
   - gRPC stream timeout set too low
   - Resource exhaustion (memory, goroutines, etc.)

5. **gRPC interceptor/middleware issue**
   - Middleware closing stream prematurely
   - Authentication/authorization interceptor rejecting request

6. **Version-specific regression**
   - Port 9999 running different code/config than working ports
   - Recent change broke gRPC streaming specifically

### Evidence Supporting Each Hypothesis

**For crash/panic (#1):**
- Immediate failure suggests handler didn't start streaming
- No partial data received

**For deserialization failure (#2):**
- REST/JSON-RPC work fine with same logical message
- Issue is gRPC-specific protobuf format

**For missing implementation (#3):**
- Common when adding new RPC methods
- Handler might send `Unimplemented` status

**For timeout (#4):**
- Less likely given immediate failure
- Would expect some delay before closure

---

## Debugging Steps for SUT Developer

### Step 1: Verify handler is reached
```go
func (s *Server) SendStreamingMessage(req *pb.SendMessageRequest, stream pb.A2AService_SendStreamingMessageServer) error {
    log.Printf("DEBUG: SendStreamingMessage called with messageId=%s", req.Request.MessageId)
    // ... rest of implementation
}
```

### Step 2: Check for panics
- Enable panic recovery logging
- Check server logs during test execution
- Look for stack traces

### Step 3: Compare working vs failing instances
```bash
# Check version/config differences
diff <(curl -s http://localhost:9999/.well-known/agent-card) \
     <(curl -s http://localhost:19999/.well-known/agent-card)
```

### Step 4: Test with grpcurl verbose mode
```bash
grpcurl -v -plaintext -d '{...}' localhost:9999 a2a.v1.A2AService/SendStreamingMessage
```

### Step 5: Enable gRPC debug logging
```bash
# For Go gRPC server:
export GRPC_GO_LOG_VERBOSITY_LEVEL=99
export GRPC_GO_LOG_SEVERITY_LEVEL=info
```

### Step 6: Minimal reproduction
Create a minimal gRPC client that:
1. Connects to port 9999
2. Calls `SendStreamingMessage`
3. Logs each received event
4. Compares behavior with ports 19999/29999

---

## Test Execution Commands

### Reproduce the FAILURE (port 9999, gRPC)
```bash
.venv/bin/python3 -m pytest \
  tests/optional/capabilities/test_streaming_methods.py::test_sse_event_format_compliance \
  --sut-url=http://localhost:9999 \
  --transports grpc \
  --transport-strategy agent_preferred \
  --test-scope=all \
  --tb=short \
  -v -s
```

### Verify REST works (port 9999, REST)
```bash
.venv/bin/python3 -m pytest \
  tests/optional/capabilities/test_streaming_methods.py::test_sse_event_format_compliance \
  --sut-url=http://localhost:9999 \
  --transports rest \
  --transport-strategy agent_preferred \
  --test-scope=all \
  --tb=short \
  -v -s
```

### Verify JSON-RPC works (port 9999, JSON-RPC)
```bash
.venv/bin/python3 -m pytest \
  tests/optional/capabilities/test_streaming_methods.py::test_sse_event_format_compliance \
  --sut-url=http://localhost:9999 \
  --transports jsonrpc \
  --transport-strategy agent_preferred \
  --test-scope=all \
  --tb=short \
  -v -s
```

### Compare with WORKING instance (port 19999, gRPC)
```bash
.venv/bin/python3 -m pytest \
  tests/optional/capabilities/test_streaming_methods.py::test_sse_event_format_compliance \
  --sut-url=http://localhost:19999 \
  --transports grpc \
  --transport-strategy agent_preferred \
  --test-scope=all \
  --tb=short \
  -v -s
```

---

## Code References

### Test Location
- **File:** `tests/optional/capabilities/test_streaming_methods.py`
- **Function:** `test_sse_event_format_compliance` (lines 560-635)
- **Fixture:** Uses `sut_client` (transport-agnostic)

### Transport Implementations
- **gRPC client:** `tck/transport/grpc_client.py:497-578` (`send_streaming_message`)
- **REST client:** `tck/transport/rest_client.py:252-329` (`send_streaming_message`)
- **JSON-RPC client:** `tck/transport/jsonrpc_client.py:294-327` (`send_streaming_message`)

### Error Location
- **File:** `tck/transport/grpc_client.py`
- **Line:** 534 - `async for response in stream:`
- **Error handling:** Lines 569-578

### Protobuf Definition
- **File:** `a2a.proto`
- **RPC:** `SendStreamingMessage` (lines 41-46)
- **Request:** `SendMessageRequest` (line 619)
- **Response:** `stream StreamResponse` (server-side streaming)

---

## Recommended Fixes for TCK

### Fix Option 1: Create Fresh Channel Per Streaming Request (RECOMMENDED)

Modify `grpc_client.py::send_streaming_message()` to create a fresh channel:

```python
async def send_streaming_message(self, message: Dict[str, Any], **kwargs):
    # Create fresh channel for this streaming request (don't reuse cached channel)
    if self.use_tls:
        credentials = grpc.ssl_channel_credentials()
        channel = grpc.aio.secure_channel(self.grpc_target, credentials)
    else:
        channel = grpc.aio.insecure_channel(self.grpc_target)
    
    async with channel:  # Use context manager to ensure cleanup
        stub = self._pb_grpc.A2AServiceStub(channel)
        stream = stub.SendStreamingMessage(request, timeout=self.timeout)
        
        async for response in stream:
            # ... yield events ...
```

### Fix Option 2: Don't Cache gRPC Clients

Modify `transport_manager.py::get_transport_client()`:

```python
def get_transport_client(self, transport_type: Optional[TransportType] = None):
    # ... selection logic ...
    
    # Don't cache gRPC clients - always create fresh
    if selected_transport == TransportType.GRPC:
        return self._create_transport_client(selected_transport)
    
    # Cache other transport types
    if selected_transport in self._client_cache:
        return self._client_cache[selected_transport]
    # ...
```

### Fix Option 3: Function-Scoped Client Fixture

Change `conftest.py` to close client after each test:

```python
@pytest.fixture(scope="function")
def sut_client(transport_manager, request):
    client = transport_manager.get_transport_client()
    yield client
    # Cleanup: close gRPC channel if it's a gRPC client
    if hasattr(client, 'close'):
        client.close()
```

### Fix Option 4: Fix Event Format (Secondary Issue)

Update `grpc_client.py` lines 546-555 to match test expectations:

```python
elif response.WhichOneof("payload") == "status_update":
    su = response.status_update
    yield {
        "kind": "status-update",  # Add kind field
        "taskId": su.task_id,
        "contextId": su.context_id,
        "status": {"state": self._map_state_enum_to_json(su.status.state)},
        "final": getattr(su, "final", False),
    }
```

---

## Next Steps

### For TCK Maintainers:
1. **Immediate:** Implement Fix Option 1 (fresh channel per streaming request)
2. **Follow-up:** Fix event format mismatch (Fix Option 4)
3. **Consider:** Review all transport client lifecycle management
4. **Test:** Run full test suite multiple times to verify fix

### For SUT Developer:
**No action needed** - the SUT is behaving correctly by rejecting invalid stream state. The issue is in the TCK's gRPC client management.

The error "Request stream 1 is not correct for server connection" indicates the SUT is properly detecting and rejecting protocol violations.
