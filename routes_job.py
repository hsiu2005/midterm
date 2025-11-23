from fastapi import APIRouter, Depends, HTTPException
from db import getDB
from deps import session_user

router = APIRouter()


@router.get("/job/{job_id}/detail")
async def get_job_detail(job_id: int, user=Depends(session_user), conn=Depends(getDB)):
    user_id = user["user_id"]

    async with conn.cursor() as cur:
        # 讀取案件
        await cur.execute(
            """
            SELECT j.*, u.username AS client_name, u_con.username AS contractor_name
            FROM jobs j
            JOIN users u ON u.id = j.client_id
            LEFT JOIN users u_con ON j.contractor_id = u_con.id
            WHERE j.id = %s
            """,
            (job_id,),
        )
        job = await cur.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # 判斷目前使用者在此案件中的角色
        user_job_role = "visitor"
        if job["client_id"] == user_id:
            user_job_role = "client"
        elif job["contractor_id"] == user_id:
            user_job_role = "contractor"
        elif user["role"] == "contractor":
            await cur.execute("SELECT 1 FROM bids WHERE job_id = %s AND contractor_id = %s", (job_id, user_id))
            bid_exists = await cur.fetchone()
            if job["status"] == 'pending' or bid_exists:
                user_job_role = "visitor_contractor"

        if user_job_role == "visitor":
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this job.")

        bids = []
        winning_bid = None

        # === 委託人視角 ===
        if user_job_role == "client":
            if job["status"] == 'pending':
                # 委託人查看所有報價（含提案書）
                await cur.execute(
                    """
                    SELECT
                        b.id, b.price, b.note, b.contractor_id,
                        u.username AS contractor_name,
                        b.created_at,
                        b.proposal_file,
                        b.proposal_original_name
                    FROM bids b
                    JOIN users u ON u.id = b.contractor_id
                    WHERE b.job_id = %s
                    ORDER BY b.price ASC
                    """,
                    (job_id,),
                )
                bids = await cur.fetchall()
            elif job["status"] != 'pending' and job["status"] != 'invited':
                # 已選標，僅顯示得標那筆（報價制）
                if job["contractor_id"]:
                    await cur.execute(
                        """
                        SELECT
                            b.id, b.price, b.note,
                            u.username AS contractor_name,
                            b.proposal_file,
                            b.proposal_original_name
                        FROM bids b
                        JOIN users u ON b.contractor_id = u.id
                        WHERE b.job_id = %s AND b.contractor_id = %s
                        LIMIT 1
                        """,
                        (job_id, job["contractor_id"]),
                    )
                    winning_bid = await cur.fetchone()

        # === 承包人 / 已報價承包人視角 ===
        elif user_job_role in ("contractor", "visitor_contractor"):
            await cur.execute(
                """
                SELECT
                    b.id, b.price, b.note, b.contractor_id,
                    u.username AS contractor_name,
                    b.created_at,
                    b.proposal_file,
                    b.proposal_original_name
                FROM bids b
                JOIN users u ON u.id = b.contractor_id
                WHERE b.job_id = %s AND b.contractor_id = %s
                """,
                (job_id, user_id),
            )
            bids = await cur.fetchall()
            if user_job_role == "contractor" and bids:
                winning_bid = bids[0]

        # 最近一次退件理由（給承包人看）
        last_rejection = None
        if user_job_role == "contractor" and job["status"] == "rejected":
            await cur.execute(
                """
                SELECT message
                FROM job_events
                WHERE job_id = %s AND event_type = 'JOB_REJECTED'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            )
            last_rejection = await cur.fetchone()

        # 成果檔案歷史版本列表（所有有權限的人都可以看到）
        await cur.execute(
            """
            SELECT
                id,
                version,
                file_path,
                original_name,
                uploaded_at,
                contractor_id
            FROM job_result_files
            WHERE job_id = %s
            ORDER BY version ASC
            """,
            (job_id,),
        )
        result_files = await cur.fetchall()

    return {
        "job": job,
        "bids": bids,
        "user_job_role": user_job_role,
        "last_rejection": last_rejection,
        "winning_bid": winning_bid,
        "result_files": result_files,
    }


@router.get("/history")
async def get_history(user=Depends(session_user), conn=Depends(getDB)):
    user_id = user["user_id"]
    role = user["role"]

    if role == "client":
        query = """
            SELECT e.*, j.title AS job_title, u.username AS actor_name
            FROM job_events e
            JOIN jobs j ON e.job_id = j.id
            LEFT JOIN users u ON e.actor_id = u.id
            WHERE j.client_id = %s
            ORDER BY e.created_at DESC
            """
        params = (user_id,)
    else:
        query = """
            SELECT e.*, j.title AS job_title, u.username AS actor_name
            FROM job_events e
            JOIN jobs j ON e.job_id = j.id
            LEFT JOIN users u ON e.actor_id = u.id
            WHERE e.job_id IN (
                SELECT DISTINCT job_id FROM bids WHERE contractor_id = %s
                UNION
                SELECT DISTINCT id FROM jobs WHERE contractor_id = %s
            )
            AND (
                e.event_type <> 'BID_SUBMITTED'
                OR (e.event_type = 'BID_SUBMITTED' AND e.actor_id = %s)
            )
            ORDER BY e.created_at DESC
            """
        params = (user_id, user_id, user_id)

    async with conn.cursor() as cur:
        await cur.execute(query, params)
        events = await cur.fetchall()

    return {"items": events}
