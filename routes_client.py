from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from db import getDB
from deps import require_role

router = APIRouter()


# 取得承包人列表 (for 邀請)
@router.get("/contractors/list")
async def get_contractors_list(
    user=Depends(require_role("client")),
    conn=Depends(getDB)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, username FROM users WHERE role = 'contractor' ORDER BY username"
        )
        rows = await cur.fetchall()
    return {"items": rows}


# 取得委託人自己的案件列表
@router.get("/client/jobs")
async def client_jobs(user=Depends(require_role("client")), conn=Depends(getDB)):
    uid = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT j.id, j.title, j.status, j.created_at,
                   COALESCE((SELECT COUNT(*) FROM bids b WHERE b.job_id = j.id), 0) AS bid_count,
                   u_con.username AS contractor_name
            FROM jobs j
            LEFT JOIN users u_con ON j.contractor_id = u_con.id
            WHERE j.client_id = %s
            ORDER BY j.id DESC
            """,
            (uid,),
        )
        rows = await cur.fetchall()
    return {"owner": uid, "count": len(rows), "items": rows}


# 建立案件（必須設定投標截止日）
@router.post("/job/new")
async def job_new(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    budget_str: Optional[str] = Form(None),
    due_date_str: Optional[str] = Form(None),
    invited_contractor_id_str: Optional[str] = Form(None),
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]
    client_username = user["username"]

    # 基本長度檢查
    if not (1 <= len(title) <= 100) or not (1 <= len(content) <= 5000):
        return HTMLResponse("建立失敗：標題或內容長度不符", status_code=400)

    # 預算（可選）
    budget: Optional[int] = None
    if budget_str and budget_str.strip():
        try:
            budget = int(budget_str)
            if budget < 0 or budget > 999_999_999:
                raise ValueError()
        except:
            return HTMLResponse("建立失敗：預算需為 0~999,999,999", status_code=400)

    # === 投標截止日（必填） ===
    if not due_date_str or not due_date_str.strip():
        return HTMLResponse("建立失敗：必須設定投標截止日", status_code=400)

    try:
        due_date = date.fromisoformat(due_date_str)
    except:
        return HTMLResponse("建立失敗：截止日格式須為 YYYY-MM-DD", status_code=400)

    # 截止日不得早於今天
    if due_date < date.today():
        return HTMLResponse("建立失敗：投標截止日不得早於今天", status_code=400)

    # 邀請承包人（可選）
    invited_contractor_id: Optional[int] = None
    if invited_contractor_id_str and invited_contractor_id_str.strip():
        try:
            invited_contractor_id = int(invited_contractor_id_str)
            if invited_contractor_id == client_id:
                raise ValueError("不能邀請自己")
        except:
            return HTMLResponse("建立失敗：邀請的承包人 ID 錯誤", status_code=400)

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                job_status = 'pending'
                contractor_id_to_insert = None
                event_type = 'JOB_CREATED'
                event_msg = f"案件「{title}」"
                event_desc = f"委託人 {client_username} 建立了新案件「{title}」"

                if invited_contractor_id:
                    # 確認受邀者存在且為 contractor
                    await cur.execute(
                        "SELECT username FROM users WHERE id = %s AND role = 'contractor'",
                        (invited_contractor_id,)
                    )
                    invited_user = await cur.fetchone()
                    if not invited_user:
                        return HTMLResponse("建立失敗：邀請的承包人不存在", status_code=400)

                    job_status = 'invited'
                    contractor_id_to_insert = invited_contractor_id
                    event_type = 'JOB_INVITED'
                    event_msg = f"邀請 {invited_user['username']}"
                    event_desc = f"委託人 {client_username} 邀請 {invited_user['username']} 承接案件「{title}」"

                # 新增 job
                await cur.execute(
                    """
                    INSERT INTO jobs (title, content, client_id, status, budget, due_date, contractor_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (title, content, client_id, job_status, budget, due_date, contractor_id_to_insert),
                )
                row = await cur.fetchone()
                job_id = row["id"]

                # 新增事件
                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (job_id, client_id, event_type, event_msg, event_desc),
                )
        return RedirectResponse(url="/clientJobs.html", status_code=302)
    except Exception as e:
        return HTMLResponse(f"建立案件失敗：{e}", status_code=500)


# 委託人選標（限：已到截止日）
@router.post("/bid/accept")
async def bid_accept(
    request: Request,
    job_id: int = Form(...),
    bid_id: int = Form(...),
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]
    client_username = user["username"]

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 鎖住案件，並帶出截止日
                await cur.execute(
                    """
                    SELECT id, due_date
                    FROM jobs
                    WHERE id = %s AND client_id = %s AND status = 'pending'
                    FOR UPDATE
                    """,
                    (job_id, client_id)
                )
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=403, detail="Job not found, not yours, or not in 'pending' state.")

                # 若有設定截止日，必須到了之後才能選標
                if job["due_date"] is not None and date.today() < job["due_date"]:
                    raise HTTPException(status_code=400, detail="尚未到達投標截止日，暫時不能選標。")

                # 找出被選中的報價
                await cur.execute(
                    "SELECT contractor_id, price FROM bids WHERE id=%s AND job_id=%s",
                    (bid_id, job_id)
                )
                bid = await cur.fetchone()
                if not bid:
                    raise HTTPException(status_code=404, detail="Bid not found for this job.")

                contractor_id = bid["contractor_id"]

                await cur.execute("SELECT username FROM users WHERE id = %s", (contractor_id,))
                contractor = await cur.fetchone()
                contractor_username = contractor["username"] if contractor else f"#{contractor_id}"

                # 更新 job 狀態
                await cur.execute(
                    "UPDATE jobs SET status = 'accepted', contractor_id = %s, updated_at = NOW() WHERE id = %s",
                    (contractor_id, job_id)
                )

                # 寫入事件
                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, 'BID_SELECTED', %s, %s)
                    """,
                    (
                        job_id,
                        client_id,
                        f"報價 #{bid_id}",
                        f"委託人 {client_username} 選擇了承包人 {contractor_username} (報價ID: {bid_id}, 價格: {bid['price']})",
                    )
                )
    except HTTPException as e:
        return HTMLResponse(f"選標失敗：{e.detail}", status_code=e.status_code)
    except Exception as e:
        return HTMLResponse(f"選標失敗，伺服器錯誤：{e}", status_code=500)

    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)


# 委託人驗收 / 退件（不刪檔，只改狀態）
@router.post("/job/review")
async def job_review(
    user=Depends(require_role("client")),
    job_id: int = Form(...),
    decision: str = Form(...),
    message: str = Form(""),
    conn=Depends(getDB)
):
    client_id = user["user_id"]

    if decision not in ['closed', 'rejected']:
        raise HTTPException(status_code=400, detail="Invalid decision.")

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 僅在 status = 'uploaded' 時可審核
                await cur.execute(
                    "SELECT id, report_file FROM jobs WHERE id = %s AND client_id = %s AND status = 'uploaded' FOR UPDATE",
                    (job_id, client_id)
                )
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=403, detail="Job not found, not yours, or not in 'uploaded' state.")

                if decision == 'rejected':
                    # 退件：只改狀態，保留所有檔案（由 job_result_files 管理版本）
                    await cur.execute(
                        "UPDATE jobs SET status = 'rejected', updated_at = NOW() WHERE id = %s",
                        (job_id,)
                    )

                    await cur.execute(
                        """
                        INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                        VALUES (%s, %s, 'JOB_REJECTED', %s, %s)
                        """,
                        (
                            job_id,
                            client_id,
                            message,
                            f"委託人 {user['username']} 退件。理由：{message}",
                        )
                    )

                else:  # 'closed'
                    await cur.execute(
                        "UPDATE jobs SET status = %s, updated_at = NOW() WHERE id = %s",
                        (decision, job_id)
                    )
                    await cur.execute(
                        """
                        INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                        VALUES (%s, %s, 'JOB_CLOSED', %s, %s)
                        """,
                        (
                            job_id,
                            client_id,
                            "驗收結案",
                            f"委託人 {user['username']} 驗收結案。",
                        )
                    )
    except HTTPException as e:
        return HTMLResponse(f"審核失敗：{e.detail}", status_code=e.status_code)
    except Exception as e:
        return HTMLResponse(f"審核失敗，伺服器錯誤：{e}", status_code=500)

    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)
