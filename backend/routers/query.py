"""Query router: accepts founder questions and streams agent responses via SSE."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.orchestrator import run_pipeline
from backend.auth.middleware import verify_jwt
from backend.rag.pipeline import RAGPipeline
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])


def _fetch_upload_context(founder_id: str, upload_id: Optional[str], sb) -> str:
    """Fetch actual CSV row data for direct LLM analysis, bypassing RAG vector search."""
    if sb is None:
        return ""
    try:
        if not upload_id:
            frow = sb.table("founders").select("active_upload_id").eq("id", founder_id).maybe_single().execute()
            upload_id = (frow.data or {}).get("active_upload_id")
        if not upload_id:
            return ""

        urow = (
            sb.table("uploads")
            .select("filename,file_type,columns,initial_metrics,row_count")
            .eq("id", upload_id)
            .eq("founder_id", founder_id)
            .maybe_single()
            .execute()
        )
        if not urow.data:
            return ""
        meta = urow.data
        filename = meta.get("filename", "file")

        # NOTE: there is no `financial_rows` table in this project (the schema
        # only has chunks/founders/query_history/uploads), so row-level
        # financial data is read back out of `chunks` instead, where
        # indexer.py stores each CSV row-chunk as plain text content.
        rows_res = (
            sb.table("chunks")
            .select("content")
            .eq("upload_id", upload_id)
            .eq("founder_id", founder_id)
            .order("created_at")
            .execute()
        )
        if rows_res.data:
            lines = [f"FILE: {filename}"]
            for r in rows_res.data:
                content = r.get("content")
                if content:
                    lines.append(content)
            return "\n".join(lines)

        # Fallback: use upload metadata + extracted metrics if no chunks yet
        cols = meta.get("columns") or []
        metrics = meta.get("initial_metrics") or {}
        lines = [
            f"FILE: {filename}",
            f"Columns: {', '.join(cols)}",
            f"Total rows: {meta.get('row_count', 0)}",
        ]
        if metrics:
            lines.append("Key metrics extracted:")
            for k, v in metrics.items():
                lines.append(f"  {k.replace('_', ' ')}: {v}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("_fetch_upload_context failed: %s", exc)
        return ""


class QueryRequest(BaseModel):
    question: str
    upload_id: Optional[str] = None


@router.get("/history")
async def get_chat_history(
    limit: int = 50,
    founder: dict = Depends(verify_jwt),
):
    """Retrieve the latest question/answer history for the founder."""
    founder_id = founder.get("sub")
    sb = get_supabase_client()
    if sb is None:
        return []

    try:
        result = (
            sb.table("query_history")
            .select("id, question, answer, upload_id, created_at")
            .eq("founder_id", founder_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.error("Chat history fetch failed: %s", exc)
        return []


@router.post("")
async def query(
    body: QueryRequest,
    request: Request,
    founder: dict = Depends(verify_jwt),
) -> StreamingResponse:
    """Stream a multi-agent analysis and save the Q&A pair to query_history."""
    founder_id: str = founder["sub"]
    logger.info("Query from founder=%s question=%r", founder_id, body.question[:80])

    sb = get_supabase_client()
    rag = RAGPipeline(supabase_client=sb)

    # Fetch direct CSV data so the LLM can analyze it without relying solely on RAG
    csv_context = _fetch_upload_context(founder_id, body.upload_id, sb)

    async def event_stream():
        full_response = ""
        try:
            async for chunk in run_pipeline(
                question=body.question,
                founder_id=founder_id,
                rag_pipeline=rag,
                csv_context=csv_context,
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected — stopping stream")
                    break

                # Accumulate the final answer text for persistence
                if chunk.startswith("event: synthesis_chunk"):
                    try:
                        data = json.loads(chunk.split("data: ")[1])
                        full_response += data.get("text", "")
                    except Exception:
                        pass
                elif chunk.startswith("event: final"):
                    # Save the completed question/answer pair as a single row,
                    # matching query_history's actual (question, answer) schema.
                    if sb and full_response:
                        try:
                            sb.table("query_history").insert({
                                "founder_id": founder_id,
                                "question": body.question,
                                "answer": full_response,
                                "upload_id": body.upload_id,
                            }).execute()
                        except Exception as exc:
                            logger.error("Failed to save query history: %s", exc)

                yield chunk
        except Exception as exc:
            logger.error("Stream error for founder=%s: %s", founder_id, str(exc))
            yield f"event: error\ndata: {json.dumps({'code': 'INTERNAL_ERROR', 'message': 'Stream failed'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
