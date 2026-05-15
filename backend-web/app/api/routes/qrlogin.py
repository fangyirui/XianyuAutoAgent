import asyncio
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger
from common.db import get_db, get_redis
from common.models import SystemConfig, Seller
from app.api.deps import get_current_user
import aiohttp

router = APIRouter(prefix="/qrlogin", tags=["qrlogin"], dependencies=[Depends(get_current_user)])

_qr_sessions: dict = {}

_COMMON_HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
}

_LOGIN_FORM_BASE = {
    "appName": "xianyu",
    "appEntrance": "web",
    "isMobile": "false",
    "lang": "zh_CN",
    "returnUrl": "https://www.goofish.com/",
    "fromSite": "77",
    "bizParams": "",
    "mainPage": "false",
    "isIframe": "true",
    "documentReferer": "https://www.goofish.com/",
    "defaultView": "qrcode",
    "umidTag": "SERVER",
    "navlanguage": "zh-CN",
    "navPlatform": "Win32",
}


@router.post("/start")
async def qrlogin_start():
    try:
        jar = aiohttp.CookieJar()
        async with aiohttp.ClientSession(headers=_COMMON_HEADERS, cookie_jar=jar) as session:
            await session.get("https://passport.goofish.com/mini_login.htm", params={
                "lang": "zh_cn", "appName": "xianyu", "appEntrance": "web",
                "styleType": "auto", "bizParams": "", "isMobile": "false",
                "returnUrl": "https://www.goofish.com/", "fromSite": "77",
            })

            url = "https://passport.goofish.com/newlogin/qrcode/generate.do"
            params = {"appName": "xianyu", "fromSite": "77"}
            resp = await session.post(url, params=params, data=_LOGIN_FORM_BASE, headers={
                "origin": "https://passport.goofish.com",
                "referer": "https://passport.goofish.com/mini_login.htm",
            })
            res_json = await resp.json(content_type=None)
            content_data = res_json.get("content", {}).get("data", {})
            if not content_data:
                return {"error": "获取二维码失败"}

            t = str(content_data.get("t", ""))
            ck = content_data.get("ck", "")
            _qr_sessions[t] = {"jar": jar, "ck": ck}
            return {"codeContent": content_data.get("codeContent", ""), "t": t}
    except Exception as e:
        logger.error(f"生成二维码失败: {e}")
        return {"error": str(e)}


@router.get("/status")
async def qrlogin_status(t: str = Query(...), db: AsyncSession = Depends(get_db)):
    qr_data = _qr_sessions.get(t)
    if not qr_data:
        return {"error": "会话已过期，请重新获取二维码"}

    jar = qr_data["jar"]
    ck = qr_data["ck"]

    try:
        async with aiohttp.ClientSession(headers={
            **_COMMON_HEADERS,
            "origin": "https://passport.goofish.com",
            "referer": "https://passport.goofish.com/mini_login.htm",
        }, cookie_jar=jar) as session:
            url = "https://passport.goofish.com/newlogin/qrcode/query.do"
            params = {"appName": "xianyu", "fromSite": "77"}
            data = {**_LOGIN_FORM_BASE, "t": t, "ck": ck}
            resp = await session.post(url, params=params, data=data)
            res_json = await resp.json(content_type=None)
            content_data = res_json.get("content", {}).get("data", {})
            qr_status = content_data.get("qrCodeStatus", "")

            if qr_status == "CONFIRMED":
                all_cookies = {}
                if content_data.get("cookieList"):
                    for item in content_data["cookieList"]:
                        all_cookies[item["name"]] = item["value"]
                for cookie in jar:
                    if cookie.key not in all_cookies:
                        all_cookies[cookie.key] = cookie.value

                # 调用 H5 API 获取 _m_h5_tk
                try:
                    import time
                    from common.utils import generate_sign
                    h5_jar = aiohttp.CookieJar()
                    async with aiohttp.ClientSession(headers={
                        **_COMMON_HEADERS,
                        "origin": "https://www.goofish.com",
                        "referer": "https://www.goofish.com/",
                    }, cookie_jar=h5_jar) as h5_session:
                        for k, v in all_cookies.items():
                            h5_jar.update_cookies({k: v})
                        ts = str(int(time.time()) * 1000)
                        data_val = '{"itemId":"0"}'
                        sign = generate_sign(ts, "", data_val)
                        h5_params = {
                            "jsv": "2.7.2", "appKey": "34839810", "t": ts,
                            "sign": sign, "v": "1.0", "type": "originaljson",
                            "accountSite": "xianyu", "dataType": "json",
                            "timeout": "20000", "api": "mtop.taobao.idle.pc.detail",
                            "sessionOption": "AutoLoginOnly",
                        }
                        h5_resp = await h5_session.post(
                            "https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/",
                            params=h5_params, data={"data": data_val},
                        )
                        for cookie in h5_jar:
                            all_cookies[cookie.key] = cookie.value
                except Exception as e:
                    logger.warning(f"获取 _m_h5_tk 失败: {e}")

                cookie_str = "; ".join([f"{k}={v}" for k, v in all_cookies.items()])
                if cookie_str:
                    # 保存到 sellers 表
                    user_id = all_cookies.get("unb", "")
                    if user_id:
                        result = await db.execute(select(Seller).where(Seller.user_id == user_id))
                        seller = result.scalar_one_or_none()
                        if seller:
                            seller.cookies_str = cookie_str
                            seller.is_active = True
                        else:
                            db.add(Seller(user_id=user_id, cookies_str=cookie_str, is_active=True))
                        await db.commit()
                        r = await get_redis()
                        await r.publish("config:reload", "qrlogin")
                        logger.info(f"扫码登录成功，Cookie 已保存到 sellers 表 ({len(all_cookies)} 项)")
                    else:
                        logger.warning(f"扫码登录成功但 Cookie 中缺少 unb 字段，无法保存到 sellers 表")

                _qr_sessions.pop(t, None)
                return {"status": "CONFIRMED"}
            elif qr_status == "SCANED":
                return {"status": "SCANED"}
            elif qr_status == "EXPIRED":
                _qr_sessions.pop(t, None)
                return {"status": "EXPIRED"}
            else:
                return {"status": "NEW"}
    except Exception as e:
        logger.error(f"查询扫码状态失败: {e}")
        return {"error": str(e)}
