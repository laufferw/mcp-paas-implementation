from typing import Dict, List, Optional, Union, Any
from enum import Enum
from pydantic import BaseModel, Field, validator, root_validator
import time
from datetime import datetime

# Base schemas
class BaseSchema(BaseModel):
    """Base schema for all models."""
    
    class Config:
        extra = "forbid"
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# Enums for inference parameters
class FinishReason(str, Enum):
    """Reasons why generation was stopped."""
    STOP = "stop"  # Generation stopped due to stop token
    LENGTH = "length"  # Generation stopped due to max tokens
    CONTENT_FILTER = "content_filter"  # Filtered due to content policy
    ERROR = "error"  # Error occurred during generation
    FUNCTION_CALL = "function_call"  # Generation stopped for function call
    INCOMPLETE = "incomplete"  # Generation is incomplete (for streaming)

class ModelParameters(BaseSchema):
    """Parameters for controlling model generation behavior."""
    
    temperature: Optional[float] = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Controls randomness of output. Higher values (e.g., 1.0) make output more random, lower values (e.g., 0.2) make it more deterministic."
    )
    top_p: Optional[float] = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Controls diversity via nucleus sampling. 0.5 means half of probability mass is considered."
    )
    max_tokens: Optional[int] = Field(
        default=1024,
        ge=1,
        le=32768,
        description="Maximum number of tokens to generate."
    )
    presence_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Penalizes tokens based on whether they've appeared so far. Positive values discourage repetition."
    )
    frequency_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Penalizes tokens based on their frequency in the text so far. Positive values discourage repetition."
    )
    stop: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Sequences where the model stops generating. Can be a string or array of strings."
    )
    
    @validator('temperature', 'top_p', 'presence_penalty', 'frequency_penalty', pre=True)
    def check_float_precision(cls, v):
        """Ensure float values are properly formatted."""
        if isinstance(v, float):
            return round(v, 6)
        return v
    
    @root_validator
    def check_parameters_compatibility(cls, values):
        """Validate that parameters are compatible with each other."""
        if values.get('temperature', 0) > 1.0 and values.get('top_p', 0) < 1.0:
            raise ValueError("High temperature with low top_p can lead to suboptimal results")
        return values
    
    class Config:
        schema_extra = {
            "example": {
                "temperature": 0.7,
                "top_p": 0.95,
                "max_tokens": 1024,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
                "stop": ["\n\n", "###"]
            }
        }

class StreamingOptions(BaseSchema):
    """Options for streaming inference responses."""
    
    enabled: bool = Field(
        default=False,
        description="Whether to stream responses or not."
    )
    chunk_size: Optional[int] = Field(
        default=20,
        ge=1,
        le=1000,
        description="Number of tokens to include in each chunk when streaming."
    )
    include_partial_outputs: Optional[bool] = Field(
        default=True,
        description="Whether to include incomplete outputs in stream chunks."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "enabled": True,
                "chunk_size": 20,
                "include_partial_outputs": True
            }
        }

# Request schemas
class FunctionDefinition(BaseSchema):
    """Definition of a function that can be called by the model."""
    
    name: str = Field(
        description="Name of the function to be called."
    )
    description: Optional[str] = Field(
        default=None,
        description="Description of what the function does."
    )
    parameters: Dict[str, Any] = Field(
        description="Parameters for the function, defined in JSON Schema format."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "name": "get_weather",
                "description": "Get the current weather in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA"
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"]
                        }
                    },
                    "required": ["location"]
                }
            }
        }

class InferenceRequest(BaseSchema):
    """Request model for running inference."""
    
    prompt: str = Field(
        description="The input text to generate from."
    )
    context_id: Optional[str] = Field(
        default=None,
        description="ID of an existing context to use for this inference."
    )
    model_parameters: Optional[ModelParameters] = Field(
        default_factory=ModelParameters,
        description="Parameters to control generation behavior."
    )
    streaming: Optional[StreamingOptions] = Field(
        default_factory=StreamingOptions,
        description="Options for response streaming."
    )
    functions: Optional[List[FunctionDefinition]] = Field(
        default=None,
        description="List of functions the model may generate calls for."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "prompt": "Write a short story about a robot learning to paint.",
                "context_id": "ctx_67890abcdef",
                "model_parameters": {
                    "temperature": 0.8,
                    "max_tokens": 2048,
                    "stop": ["THE END"]
                },
                "streaming": {
                    "enabled": True,
                    "chunk_size": 20
                }
            }
        }

# Response schemas
class TokenUsage(BaseSchema):
    """Tracking of token usage for the request."""
    
    prompt_tokens: int = Field(
        description="Number of tokens in the prompt."
    )
    completion_tokens: int = Field(
        description="Number of tokens in the completion."
    )
    total_tokens: int = Field(
        description="Total number of tokens used (prompt + completion)."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "prompt_tokens": 42,
                "completion_tokens": 128,
                "total_tokens": 170
            }
        }

class PerformanceMetrics(BaseSchema):
    """Performance metrics for the inference request."""
    
    latency_ms: float = Field(
        description="End-to-end latency in milliseconds."
    )
    tokens_per_second: float = Field(
        description="Generation speed in tokens per second."
    )
    first_token_ms: float = Field(
        description="Time to first token in milliseconds."
    )
    processing_start: datetime = Field(
        description="Timestamp when processing started."
    )
    processing_end: datetime = Field(
        description="Timestamp when processing completed."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "latency_ms": 1250.45,
                "tokens_per_second": 22.5,
                "first_token_ms": 320.8,
                "processing_start": "2023-06-01T12:30:45.123456",
                "processing_end": "2023-06-01T12:30:47.654321"
            }
        }

class FunctionCall(BaseSchema):
    """Function call generated by the model."""
    
    name: str = Field(
        description="Name of the function to call."
    )
    arguments: Dict[str, Any] = Field(
        description="Arguments to pass to the function."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "name": "get_weather",
                "arguments": {
                    "location": "San Francisco, CA",
                    "unit": "celsius"
                }
            }
        }

class ErrorDetails(BaseSchema):
    """Error information for failed inference requests."""
    
    code: str = Field(
        description="Error code identifier."
    )
    message: str = Field(
        description="Human-readable error message."
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "code": "model_overloaded",
                "message": "The model is currently overloaded with requests. Please try again later.",
                "details": {
                    "retry_after": 30,
                    "queue_position": 5
                }
            }
        }

class InferenceResponse(BaseSchema):
    """Response model for inference results."""
    
    id: str = Field(
        description="Unique identifier for this inference response."
    )
    text: str = Field(
        description="Generated text from the model."
    )
    finish_reason: FinishReason = Field(
        description="Reason why generation was stopped."
    )
    token_usage: TokenUsage = Field(
        description="Token usage statistics."
    )
    performance: PerformanceMetrics = Field(
        description="Performance metrics for the request."
    )
    function_call: Optional[FunctionCall] = Field(
        default=None,
        description="Function call generated by the model, if any."
    )
    error: Optional[ErrorDetails] = Field(
        default=None,
        description="Error details, if inference failed."
    )
    
    @validator('text')
    def trim_whitespace(cls, v):
        """Trim leading and trailing whitespace."""
        if isinstance(v, str):
            return v.strip()
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "id": "inf_12345abcdef",
                "text": "Once upon a time, there was a robot named Pixel who discovered an old set of paints...",
                "finish_reason": "stop",
                "token_usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 150,
                    "total_tokens": 162
                },
                "performance": {
                    "latency_ms": 1250.45,
                    "tokens_per_second": 22.5,
                    "first_token_ms": 320.8,
                    "processing_start": "2023-06-01T12:30:45.123456",
                    "processing_end": "2023-06-01T12:30:47.654321"
                }
            }
        }

# Streaming response schemas
class StreamingChunk(BaseSchema):
    """Chunk of text in a streaming response."""
    
    id: str = Field(
        description="Unique identifier for this inference response."
    )
    chunk_index: int = Field(
        description="Index of this chunk in the stream."
    )
    text: str = Field(
        description="Text generated in this chunk."
    )
    is_complete: bool = Field(
        description="Whether this is the last chunk in the stream."
    )
    finish_reason: Optional[FinishReason] = Field(
        default=None,
        description="Reason why generation was stopped (only for last chunk)."
    )
    tokens_generated: int = Field(
        description="Number of tokens generated so far."
    )
    progress_percentage: float = Field(
        description="Approximate percentage of completion (0-100)."
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when this chunk was generated."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "id": "inf_12345abcdef",
                "chunk_index": 3,
                "text": "who discovered an old set of paints",
                "is_complete": False,
                "tokens_generated": 60,
                "progress_percentage": 30.0,
                "timestamp": "2023-06-01T12:30:46.123456"
            }
        }

class StreamingFinalChunk(StreamingChunk):
    """Final chunk in a streaming response with complete statistics."""
    
    token_usage: TokenUsage = Field(
        description="Token usage statistics."
    )
    performance: PerformanceMetrics = Field(
        description="Performance metrics for the request."
    )
    function_call: Optional[FunctionCall] = Field(
        default=None,
        description="Function call generated by the model, if any."
    )
    
    class Config:
        schema_extra = {
            "example": {
                "id": "inf_12345abcdef",
                "chunk_index": 10,
                "text": ".",
                "is_complete": True,
                "finish_reason": "stop",
                "tokens_generated": 200,
                "progress_percentage": 100.0,
                "timestamp": "2023-06-01T12:30:48.123456",
                "token_usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 200,
                    "total_tokens": 212
                },
                "performance": {
                    "latency_ms": 3250.45,
                    "tokens_per_second": 22.5,
                    "first_token_ms": 320.8,
                    "processing_start": "2023-06-01T12:30:45.123456",
                    "processing_end": "2023-06-01T12:30:48.654321"
                }
            }
        }

