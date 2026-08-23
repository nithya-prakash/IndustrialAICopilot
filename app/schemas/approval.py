from pydantic import BaseModel, Field


class ApprovalDecisionRequest(BaseModel):
    comments: str | None = Field(default=None, max_length=2000)
