# 注意：這個檔只是 Session 示範，請不要與 main.py 同時啟動。
# 交作業或實際執行請用 main.py。

from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import HTTPException
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="your-secret-key",
    max_age=None,
    same_site="lax",
    https_only=False,
)

def get_current_user(request: Request):
    user_id = request.session.get("user")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id

@app.get("/")
async def home(request: Request, user: str = Depends(get_current_user)):
    return {"message": f"Welcome back, {user}!"}

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/loginForm.html")

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == 'user' and password == 'pass':
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse("Invalid credentials <a href='/loginForm.html'>login again</a>", status_code=401)

# 不要在這裡掛 StaticFiles，避免與 main.py 衝突
