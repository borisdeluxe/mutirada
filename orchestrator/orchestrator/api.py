"""Task submission API - enables any Claude to submit tasks via HTTP."""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, field_validator
import psycopg
from psycopg.rows import dict_row


app = FastAPI(title="Mutirada Agency API", version="1.0.0")

PIPELINE_DIR = Path(os.environ.get('AGENCY_PIPELINE_DIR', '/opt/agency/.pipeline'))
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://agency:agency@localhost:5432/agency_db')

_api_secret = os.environ.get('AGENCY_API_SECRET')
if _api_secret is None:
    raise ValueError("AGENCY_API_SECRET environment variable must be set")
API_SECRET = _api_secret

FEATURE_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


def get_db():
    """Get database connection."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def verify_secret(x_agency_secret: str = Header(None)):
    """Verify API secret header."""
    if not x_agency_secret or x_agency_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Agency-Secret")
    return True


def generate_feature_id(prefix: str = "API") -> str:
    """Generate unique feature ID."""
    timestamp = datetime.now().strftime('%H%M%S')
    return f"{prefix}-{timestamp}"


def validate_feature_id(value: Optional[str]) -> Optional[str]:
    """Validate feature_id to prevent path traversal and injection."""
    if value is None:
        return None
    if '\x00' in value:
        raise ValueError("feature_id contains invalid characters")
    if value.startswith('/'):
        raise ValueError("feature_id cannot be an absolute path")
    if '..' in value:
        raise ValueError("feature_id cannot contain path traversal")
    if not FEATURE_ID_PATTERN.match(value):
        raise ValueError("feature_id must be alphanumeric with dashes/underscores")
    return value


class TaskSubmit(BaseModel):
    """Task submission request."""
    title: str
    body: str = ""
    feature_id: Optional[str] = None
    priority: int = 0

    @field_validator('feature_id')
    @classmethod
    def check_feature_id(cls, v):
        return validate_feature_id(v)


class ReviewSubmit(BaseModel):
    """Review submission request."""
    target: Optional[str] = None
    pr_number: Optional[int] = None


class TaskResponse(BaseModel):
    """Task creation response."""
    feature_id: str
    status: str
    input_file: str


@app.get("/health")
def health():
    """Health check - no auth required."""
    return {"status": "ok", "service": "mutirada-api"}


@app.post("/api/tasks", status_code=201, response_model=TaskResponse)
def submit_task(task: TaskSubmit, _: bool = Depends(verify_secret)):
    """Submit a new feature task to the pipeline."""
    feature_id = task.feature_id or generate_feature_id()

    # Create pipeline directory
    feature_dir = PIPELINE_DIR / feature_id
    feature_dir.mkdir(parents=True, exist_ok=True)

    # Write input.md
    input_content = f"""# {task.title}

## Description

{task.body if task.body else 'No description provided.'}

## Metadata

- Feature ID: {feature_id}
- Source: API
- Created: {datetime.now().isoformat()}
"""
    input_file = feature_dir / 'input.md'
    input_file.write_text(input_content)

    # Insert into database
    data = json.dumps({'title': task.title, 'body': task.body})

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agency_tasks (feature_id, source, priority, data)
            VALUES (%s, %s, %s, %s)
            """,
            (feature_id, 'api', task.priority, data)
        )
        conn.commit()

    return TaskResponse(
        feature_id=feature_id,
        status="pending",
        input_file=str(input_file)
    )


@app.post("/api/review", status_code=201, response_model=TaskResponse)
def submit_review(review: ReviewSubmit, _: bool = Depends(verify_secret)):
    """Submit a review-only task (skips to security_reviewer)."""
    if not review.target and not review.pr_number:
        raise HTTPException(status_code=400, detail="Provide target path or pr_number")

    feature_id = generate_feature_id("REVIEW")

    if review.pr_number:
        review_target = f"PR #{review.pr_number}"
        data = json.dumps({'pr_number': review.pr_number})
    else:
        review_target = review.target
        data = json.dumps({'path': review.target})

    # Create pipeline directory
    feature_dir = PIPELINE_DIR / feature_id
    feature_dir.mkdir(parents=True, exist_ok=True)

    # Write input.md
    input_content = f"""# Review Request

## Target

{review_target}

## Metadata

- Feature ID: {feature_id}
- Source: review
- Created: {datetime.now().isoformat()}
"""
    input_file = feature_dir / 'input.md'
    input_file.write_text(input_content)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agency_tasks (feature_id, source, data)
            VALUES (%s, %s, %s)
            """,
            (feature_id, 'review', data)
        )
        conn.commit()

    return TaskResponse(
        feature_id=feature_id,
        status="pending",
        input_file=str(input_file)
    )


@app.get("/api/status")
def get_status(_: bool = Depends(verify_secret)):
    """Get pipeline status and budget."""
    with get_db() as conn:
        # Active tasks
        tasks = conn.execute(
            """
            SELECT feature_id, status, current_agent, cost_eur
            FROM agency_tasks
            WHERE status IN ('pending', 'in_progress')
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()

        # Daily budget
        daily = conn.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0) as total
            FROM agency_tasks
            WHERE created_at >= CURRENT_DATE
            """
        ).fetchone()

    daily_total = float(daily['total']) if daily else 0

    return {
        "tasks": [
            {
                "feature_id": t["feature_id"],
                "status": t["status"],
                "current_agent": t["current_agent"],
                "cost_eur": float(t["cost_eur"] or 0)
            }
            for t in tasks
        ],
        "budget": {
            "daily_used": daily_total,
            "daily_limit": 20.00,
            "daily_remaining": 20.00 - daily_total
        }
    }


@app.delete("/api/tasks/{feature_id}")
def cancel_task(feature_id: str, _: bool = Depends(verify_secret)):
    """Cancel a pending or in-progress task."""
    with get_db() as conn:
        result = conn.execute(
            """
            UPDATE agency_tasks
            SET status = 'cancelled', updated_at = NOW()
            WHERE feature_id = %s AND status IN ('pending', 'in_progress')
            RETURNING feature_id
            """,
            (feature_id,)
        ).fetchone()
        conn.commit()

    if not result:
        raise HTTPException(status_code=404, detail="Task not found or already completed")

    return {"cancelled": feature_id}
