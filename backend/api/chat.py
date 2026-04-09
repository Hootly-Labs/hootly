"""Chat Q&A endpoints — streaming conversation grounded in analysis data."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import Analysis, ChatMessage, User, _utcnow
from services.auth_service import get_current_user
from services.chat_service import (
    FREE_CHAT_LIMIT,
    build_system_prompt,
    stream_chat_response,
)
from services.rate_limiter import check_rate_limit_key

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/analysis/{analysis_id}/chat")
def send_chat_message(
    analysis_id: str,
    req: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate analysis ownership
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not current_user.is_admin and analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status != "completed" or not analysis.result:
        raise HTTPException(status_code=400, detail="Analysis is not yet completed")

    # Rate limit: 30 messages per minute per user
    allowed, retry_after = check_rate_limit_key(
        f"chat:{current_user.id}", max_requests=30, window=60
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many messages. Try again in {retry_after} seconds.")

    # Free plan limit: 10 user messages per analysis
    if current_user.plan == "free":
        user_msg_count = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.analysis_id == analysis_id,
                ChatMessage.user_id == current_user.id,
                ChatMessage.role == "user",
            )
            .count()
        )
        if user_msg_count >= FREE_CHAT_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="FREE_CHAT_LIMIT_REACHED",
            )

    # Validate message length
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(message) > 4000:
        raise HTTPException(status_code=400, detail="Message too long (max 4000 characters)")

    # Load analysis result
    try:
        result = json.loads(analysis.result)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse analysis result")

    # Load annotations for tribal knowledge context
    annotations_data = None
    try:
        from models import Annotation
        anns = (
            db.query(Annotation)
            .filter(Annotation.analysis_id == analysis_id)
            .limit(20)
            .all()
        )
        if anns:
            annotations_data = [
                {"type": a.annotation_type, "file_path": a.file_path, "content": a.content}
                for a in anns
            ]
    except Exception:
        pass

    # Build system prompt with vector search context
    system_prompt = build_system_prompt(
        result,
        question=message,
        annotations=annotations_data,
        analysis_id=analysis_id,
        db=db,
    )

    # Ensure session is clean before querying chat history
    # (RAG search may have left it in a failed state)
    try:
        db.rollback()
    except Exception:
        pass

    # Load last 20 messages for conversation history
    history = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.analysis_id == analysis_id,
            ChatMessage.user_id == current_user.id,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(20)
        .all()
    )

    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": message})

    # Persist user message
    user_msg = ChatMessage(
        analysis_id=analysis_id,
        user_id=current_user.id,
        role="user",
        content=message,
    )
    db.add(user_msg)
    db.commit()

    # Stream response, persist assistant message after completion
    def generate():
        full_text = ""
        for chunk in stream_chat_response(system_prompt, messages):
            # Extract full_text from done event
            if '"type": "done"' in chunk or '"type":"done"' in chunk:
                try:
                    data_str = chunk.replace("data: ", "").strip()
                    data = json.loads(data_str)
                    full_text = data.get("full_text", "")
                except Exception:
                    pass
            yield chunk

        # Persist assistant message in a fresh session
        if full_text:
            persist_db = SessionLocal()
            try:
                assistant_msg = ChatMessage(
                    analysis_id=analysis_id,
                    user_id=current_user.id,
                    role="assistant",
                    content=full_text,
                )
                persist_db.add(assistant_msg)
                persist_db.commit()
            except Exception as exc:
                logger.warning("Failed to persist assistant message: %s", exc)
            finally:
                persist_db.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/analysis/{analysis_id}/chat")
def get_chat_history(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate analysis ownership
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not current_user.is_admin and analysis.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.analysis_id == analysis_id,
            ChatMessage.user_id == current_user.id,
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]
