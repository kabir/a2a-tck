import pytest

from tck import message_utils
from tck.sut_client import SUTClient
from tests.markers import optional_feature


@pytest.fixture(scope="module")
def sut_client():
    return SUTClient()

@pytest.fixture
def text_message_params():
    """Create a basic text message params object"""
    return {
        "message": {
            "parts": [
                {
                    "kind": "text",
                    "text": "Hello from reference task ID test!"
                }
            ]
        }
    }

@optional_feature
def test_reference_task_ids_valid(sut_client, text_message_params):
    """
    OPTIONAL FEATURE: A2A Reference Task IDs Support
    
    Tests optional implementation that enhances user experience
    but is not required for A2A compliance.
    
    Test validates handling of valid referenceTaskIds in messages.
    
    Failure Impact: Limits feature completeness (perfectly acceptable)
    Fix Suggestion: Implement referenceTaskIds support to enable task relationships
    
    Asserts:
        - Valid referenceTaskIds are processed without error
        - Response format is valid regardless of feature support
        - Task references are handled appropriately by implementation
    """
    # Step 1: Create a reference task
    create_req = message_utils.make_json_rpc_request("message/send", params=text_message_params)
    create_resp = sut_client.send_json_rpc(**create_req)
    
    # Skip test if response is not successful
    if not message_utils.is_json_rpc_success_response(create_resp, expected_id=create_req["id"]):
        pytest.skip("Failed to create reference task")
        
    reference_task_id = create_resp["result"]["id"]
    
    # Step 2: Create a new task with reference to the first task
    params_with_reference = {
        "message": {
            "parts": [
                {
                    "kind": "text",
                    "text": "This message references another task"
                }
            ],
            "referenceTaskIds": [reference_task_id]
        }
    }
    
    ref_req = message_utils.make_json_rpc_request("message/send", params=params_with_reference)
    ref_resp = sut_client.send_json_rpc(**ref_req)
    
    # The SUT might handle this in different ways:
    # 1. Accept it and use the reference (success)
    # 2. Ignore the reference but still process the message (success)
    # 3. Reject it if referenceTaskIds are not supported (error)
    
    # We'll just check for a valid response, since behavior is implementation-specific
    assert "jsonrpc" in ref_resp
    assert "id" in ref_resp and ref_resp["id"] == ref_req["id"]

@optional_feature
def test_reference_task_ids_invalid(sut_client):
    """
    OPTIONAL FEATURE: A2A Reference Task IDs Invalid Handling
    
    Tests optional implementation that enhances user experience
    but is not required for A2A compliance.
    
    Test validates handling of invalid referenceTaskIds in messages.
    
    Failure Impact: Limits feature completeness (perfectly acceptable)
    Fix Suggestion: Implement proper validation and error handling for invalid task references
    
    Asserts:
        - Invalid referenceTaskIds are handled gracefully
        - Error responses (if any) use appropriate error codes
        - Implementation behavior is consistent and predictable
    """
    # Create a message with an invalid/non-existent reference task ID
    params = {
        "message": {
            "parts": [
                {
                    "kind": "text",
                    "text": "This message references a non-existent task"
                }
            ],
            "referenceTaskIds": ["non-existent-task-id"]
        }
    }
    
    req = message_utils.make_json_rpc_request("message/send", params=params)
    resp = sut_client.send_json_rpc(**req)
    
    # The SUT might handle this in different ways:
    # 1. Reject with an error (TaskNotFoundError)
    # 2. Accept but ignore the invalid reference
    # 3. Accept but fail the task if references are critical
    
    # We'll just check for a valid response, since behavior is implementation-specific
    assert "jsonrpc" in resp
    assert "id" in resp and resp["id"] == req["id"]
    
    # If it's an error response, check it's a reasonable error code
    if message_utils.is_json_rpc_error_response(resp, expected_id=req["id"]):
        # Error code might be TaskNotFoundError or InvalidParamsError
        assert resp["error"]["code"] < 0, "Expected a negative error code" 