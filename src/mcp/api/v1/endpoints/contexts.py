from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession

from mcp.db.session import get_db
from mcp.models.models import Context as ContextModel
from mcp.services.auth import get_current_user, get_current_active_tenant
from mcp.services.context_manager import ContextManager
from mcp.models.models import User, Tenant

from pydantic import BaseModel, Field, validator


# Pydantic models for request/response
class ContextBase(BaseModel):
    name: str = Field(..., description="Name of the context")
    model_id: str = Field(..., description="ID of the model to use")
    parameters: Optional[Dict[str, Any]] = Field(default={}, description="Parameters for the context")


class ContextCreate(ContextBase):
    description: Optional[str] = Field(default=None, description="Optional description for the context")
    tags: Optional[List[str]] = Field(default=[], description="Optional tags for categorization")
    ttl_seconds: Optional[int] = Field(default=None, description="Time to live in seconds, if temporary context")


class ContextUpdate(BaseModel):
    name: Optional[str] = Field(default=None, description="Updated name of the context")
    description: Optional[str] = Field(default=None, description="Updated description")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Updated parameters")
    tags: Optional[List[str]] = Field(default=None, description="Updated tags")
    ttl_seconds: Optional[int] = Field(default=None, description="Updated time to live in seconds")


class ContextResponse(ContextBase):
    id: UUID = Field(..., description="Unique identifier for the context")
    tenant_id: UUID = Field(..., description="Tenant ID that owns this context")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    description: Optional[str] = Field(default=None, description="Context description")
    tags: List[str] = Field(default=[], description="Tags for categorization")
    ttl_seconds: Optional[int] = Field(default=None, description="Time to live in seconds, if set")
    state: str = Field(..., description="Current state of the context")

    class Config:
        orm_mode = True


class InferenceRequest(BaseModel):
    prompt: str = Field(..., description="Input prompt for inference")
    parameters: Optional[Dict[str, Any]] = Field(default={}, description="Optional override parameters")
    stream: Optional[bool] = Field(default=False, description="Whether to stream the response")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens to generate")


class InferenceResponse(BaseModel):
    context_id: UUID = Field(..., description="Context ID used for inference")
    request_id: UUID = Field(..., description="Unique identifier for this inference request")
    completion: str = Field(..., description="Generated completion")
    usage: Dict[str, int] = Field(..., description="Token usage statistics")
    finish_reason: str = Field(..., description="Reason why the generation finished")
    model_id: str = Field(..., description="ID of the model used")


class ContextStatusResponse(BaseModel):
    context_id: UUID = Field(..., description="Context ID")
    state: str = Field(..., description="Current state of the context")
    resources: Dict[str, Any] = Field(..., description="Resource usage information")
    token_usage: Dict[str, int] = Field(..., description="Token usage statistics")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    last_used_at: Optional[str] = Field(default=None, description="Last usage timestamp")
    inference_count: int = Field(..., description="Number of inferences run")


# Create router
router = APIRouter(prefix="/contexts", tags=["contexts"])


@router.post("", response_model=ContextResponse, status_code=status.HTTP_201_CREATED)
async def create_context(
    context_in: ContextCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant)
):
    """
    Create a new model context.
    
    Creates a new model context with the specified parameters. The context 
    is associated with the current tenant and is available for running 
    inferences immediately after creation.
    """
    context_manager = ContextManager(db)
    
    try:
        context = await context_manager.create_context(
            tenant_id=current_tenant.id,
            user_id=current_user.id,
            name=context_in.name,
            model_id=context_in.model_id,
            parameters=context_in.parameters,
            description=context_in.description,
            tags=context_in.tags,
            ttl_seconds=context_in.ttl_seconds
        )
        
        return context
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create context: {str(e)}"
        )


@router.get("/{context_id}", response_model=ContextResponse)
async def get_context(
    context_id: UUID = Path(..., description="The ID of the context to retrieve"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant)
):
    """
    Get a specific model context by ID.
    
    Retrieves the details of an existing model context.
    """
    context_manager = ContextManager(db)
    
    try:
        context = await context_manager.get_context(
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        if not context:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Context with ID {context_id} not found"
            )
            
        return context
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve context: {str(e)}"
        )


@router.get("", response_model=List[ContextResponse])
async def list_contexts(
    skip: int = Query(0, description="Number of records to skip"),
    limit: int = Query(100, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant)
):
    """
    List all model contexts for the current tenant.
    
    Returns a paginated list of all model contexts owned by the current tenant.
    """
    context_manager = ContextManager(db)
    
    try:
        contexts = await context_manager.list_contexts(
            tenant_id=current_tenant.id,
            skip=skip,
            limit=limit
        )
        
        return contexts
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list contexts: {str(e)}"
        )


@router.put("/{context_id}", response_model=ContextResponse)
async def update_context(
    context_in: ContextUpdate,
    context_id: UUID = Path(..., description="The ID of the context to update"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant)
):
    """
    Update an existing model context.
    
    Updates the details of an existing model context.
    """
    context_manager = ContextManager(db)
    
    try:
        # First check if the context exists
        existing_context = await context_manager.get_context(
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        if not existing_context:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Context with ID {context_id} not found"
            )
        
        # Update the context
        updated_context = await context_manager.update_context(
            tenant_id=current_tenant.id,
            context_id=context_id,
            update_data=context_in.dict(exclude_unset=True)
        )
        
        return updated_context
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update context: {str(e)}"
        )


@router.delete("/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_context(
    context_id: UUID = Path(..., description="The ID of the context to delete"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant),
    background_tasks: BackgroundTasks = Depends()
):
    """
    Delete a model context.
    
    Deletes an existing model context and releases all associated resources.
    """
    context_manager = ContextManager(db)
    
    try:
        # First check if the context exists
        existing_context = await context_manager.get_context(
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        if not existing_context:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Context with ID {context_id} not found"
            )
        
        # Delete the context asynchronously
        background_tasks.add_task(
            context_manager.delete_context,
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        return None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete context: {str(e)}"
        )


@router.post("/{context_id}/inference", response_model=InferenceResponse)
async def run_inference(
    inference_in: InferenceRequest,
    context_id: UUID = Path(..., description="The ID of the context to use for inference"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant)
):
    """
    Run model inference using a specific context.
    
    Executes an inference request using the specified model context.
    The context must be in a valid state for inference.
    """
    context_manager = ContextManager(db)
    
    try:
        # First check if the context exists
        existing_context = await context_manager.get_context(
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        if not existing_context:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Context with ID {context_id} not found"
            )
        
        # Run inference
        result = await context_manager.run_inference(
            tenant_id=current_tenant.id,
            context_id=context_id,
            prompt=inference_in.prompt,
            parameters=inference_in.parameters,
            stream=inference_in.stream,
            max_tokens=inference_in.max_tokens
        )
        
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run inference: {str(e)}"
        )


@router.get("/{context_id}/status", response_model=ContextStatusResponse)
async def get_context_status(
    context_id: UUID = Path(..., description="The ID of the context to check"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_active_tenant)
):
    """
    Get the status of a model context.
    
    Retrieves the current status and resource usage of a model context.
    """
    context_manager = ContextManager(db)
    
    try:
        # First check if the context exists
        existing_context = await context_manager.get_context(
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        if not existing_context:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Context with ID {context_id} not found"
            )
        
        # Get context status
        status_info = await context_manager.get_context_status(
            tenant_id=current_tenant.id,
            context_id=context_id
        )
        
        return status_info
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get context status: {str(e)}"
        )

