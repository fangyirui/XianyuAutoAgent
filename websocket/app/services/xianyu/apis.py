import asyncio
import json
import time
import aiohttp
from loguru import logger
from common.utils import generate_sign


RISK_CONTROL_COOLDOWN = 600  # 触发风控后的冷却秒数（10分钟）
NONE_RETRY_BACKOFF = 2  # _signed_post 返回 None（网络抖动/非 JSON 响应）时的重试间隔秒数


class XianyuApis:
    def __init__(self, cookies_str: str):
        self.cookies_str = cookies_str
        self.cookies = self._parse_cookies(cookies_str)
        self.risk_control_until: float = 0.0
        # 串行化所有 mtop 请求的"读 _m_h5_tk → 签名 → 请求 → 接 Set-Cookie 续期"原子段。
        # _m_h5_tk 是"首次失败续期、二次成功"的两步握手 token，token_refresh_loop 与多个
        # 消息 worker 会并发打 mtop，不串行就会互相覆盖刚续期的 token，导致签名永远对不上。
        self._mtop_lock = asyncio.Lock()
        self._headers = {
            "accept": "application/json",
            "origin": "https://www.goofish.com",
            "referer": "https://www.goofish.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        }

    def _in_cooldown(self) -> int:
        remaining = int(self.risk_control_until - time.time())
        return remaining if remaining > 0 else 0

    def _trip_risk_control(self, ret_value):
        self.risk_control_until = time.time() + RISK_CONTROL_COOLDOWN
        logger.error(f"触发风控，进入 {RISK_CONTROL_COOLDOWN}s 冷却: {ret_value}")

    def _parse_cookies(self, cookies_str: str) -> dict:
        cookies = {}
        for item in cookies_str.split("; "):
            parts = item.split("=", 1)
            if len(parts) == 2:
                cookies[parts[0]] = parts[1]
        return cookies

    @property
    def cookie_str(self) -> str:
        """实时 cookie 串：含每次 mtop 请求经 Set-Cookie 滚动续期后的最新值。
        WebSocket 握手 header 与持久化都应取这里，而非 __init__ 的初始快照。"""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _cookie_header(self) -> str:
        return self.cookie_str

    async def _signed_post(self, api: str, data_val: str, extra_params: dict | None = None) -> dict | None:
        """执行一次签名 mtop 请求并接住 Set-Cookie 续期，整段在锁内原子完成。

        读 _m_h5_tk → 算签名 → 发请求 → 把 resp 的 Set-Cookie 写回 self.cookies，
        这四步必须对并发调用方互斥：否则 A 刚拿到续期 token、B 又用旧 token 覆盖，
        握手永远完不成（持续 FAIL_SYS_TOKEN_EXPIRED）。返回解析后的 dict，非 dict 返回 None。"""
        async with self._mtop_lock:
            t = str(int(time.time()) * 1000)
            token = self.cookies.get("_m_h5_tk", "").split("_")[0]
            sign = generate_sign(t, token, data_val)
            params = {
                "jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign,
                "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
                "dataType": "json", "timeout": "20000",
                "api": api,
                "sessionOption": "AutoLoginOnly",
            }
            if extra_params:
                params.update(extra_params)
            url = f"https://h5api.m.goofish.com/h5/{api}/1.0/"
            async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
                async with session.post(url, params=params, data={"data": data_val}) as resp:
                    res = await resp.json()
                    # 诊断：直接看原始 Set-Cookie 头里有哪些 cookie 名（不打值，避免泄露凭证）。
                    # 与下面 resp.cookies 解析出的名字对比——若原始头里有 _m_h5_tk 而
                    # resp.cookies 没解析出来，就是 aiohttp 漏接续期，定位到客户端侧。
                    raw_set_cookie = resp.headers.getall("Set-Cookie", [])
                    raw_names = [c.split("=", 1)[0].strip() for c in raw_set_cookie]
                    for cookie in resp.cookies.values():
                        self.cookies[cookie.key] = cookie.value
                    parsed_names = list(resp.cookies.keys())
                    logger.debug(
                        f"[setcookie] api={api.split('.')[-1]} "
                        f"原始头={raw_names or '<无>'} 已解析={parsed_names or '<无>'}"
                    )
        return res if isinstance(res, dict) else None

    async def get_token(self, device_id: str) -> dict | None:
        """获取登录 token。有限重试（不再递归）：最多 MAX_ATTEMPTS 次请求，
        其间允许一次 has_login 复核重置；耗尽即返回 None，由调用方退避。
        彻底杜绝旧实现里 has_login 恒 True 导致的无限递归（RecursionError + 刷屏）。"""
        remaining = self._in_cooldown()
        if remaining > 0:
            logger.warning(f"风控冷却中，跳过 token 请求，剩余 {remaining}s")
            return None

        MAX_ATTEMPTS = 6        # token 请求总次数上限
        relogin_checked = False  # has_login 复核只做一次，避免再退化成无限重置
        data_val = f'{{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"{device_id}"}}'

        for attempt in range(MAX_ATTEMPTS):
            tk_before = self.cookies.get("_m_h5_tk", "")
            res = await self._signed_post("mtop.taobao.idlemessage.pc.login.token", data_val)
            tk_after = self.cookies.get("_m_h5_tk", "")
            # 两步握手诊断：tk_before/tk_after 不同说明服务端经 Set-Cookie 下发了新 token，
            # 下一轮 attempt 理应用 tk_after 签名成功；若始终相同则是没续期（卡在第一步）。
            logger.debug(
                f"[token握手] attempt={attempt} "
                f"tk_before={tk_before[:24] or '<空>'} -> tk_after={tk_after[:24] or '<空>'} "
                f"{'变化' if tk_before != tk_after else '未变'}"
            )
            if res is None:
                await asyncio.sleep(NONE_RETRY_BACKOFF)
                continue

            ret_value = res.get("ret", [])
            if any("SUCCESS" in r for r in ret_value):
                logger.info("Token获取成功")
                return res

            error_msg = str(ret_value)
            if "RGV587_ERROR" in error_msg or "被挤爆啦" in error_msg:
                self._trip_risk_control(ret_value)
                return None

            logger.warning(f"Token API调用失败: {ret_value}")

            # 两步握手的真正触发条件是 _m_h5_tk 为空：mtop 在 token 非空时只校验、不主动
            # 重发，所以一旦本地存着一个已坏死的 token，就会“用坏 token 签名→被拒→服务端
            # 不下发新 token”地死循环（诊断日志表现为 tk_before==tk_after 持续“未变”）。
            # 故此：本轮失败且 token 未经 Set-Cookie 续期时，主动清空 _m_h5_tk，逼下一轮
            # 以空 token 请求，触发服务端走第一步下发新 token。
            if tk_after and tk_before == tk_after:
                self.cookies.pop("_m_h5_tk", None)
                logger.warning("token 未续期且签名被拒，已清空 _m_h5_tk 以触发重新下发")

            # 连续失败到一半时，复核 passport 登录态：失效则无谓再试，直接返回
            if not relogin_checked and attempt >= 2:
                relogin_checked = True
                if not await self.has_login():
                    logger.error("Cookie已失效")
                    return None

        logger.error(f"Token获取失败，已重试 {MAX_ATTEMPTS} 次仍未成功")
        return None

    async def has_login(self) -> bool:
        url = "https://passport.goofish.com/newlogin/hasLogin.do"
        data = {
            "hid": self.cookies.get("unb", ""),
            "ltl": "true", "appName": "xianyu", "appEntrance": "web",
            "fromSite": "77", "lang": "zh_CN",
        }
        async with self._mtop_lock:
            async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
                async with session.post(url, params={"appName": "xianyu", "fromSite": "77"}, data=data) as resp:
                    res = await resp.json()
                    for cookie in resp.cookies.values():
                        self.cookies[cookie.key] = cookie.value
        success = res.get("content", {}).get("success", False)
        # 诊断：打印 passport 登录态复核结果。若 success=True 却仍拿不到 token，
        # 说明登录态没真失效，问题在 mtop 侧 token 下发；False 则是 Cookie 真过期需重登。
        logger.debug(f"[haslogin] success={success} resultCode={res.get('content', {}).get('data', {}).get('resultCode')}")
        return success

    async def get_item_info(self, item_id: str) -> dict:
        remaining = self._in_cooldown()
        if remaining > 0:
            return {"error": f"风控冷却中，剩余 {remaining}s"}

        data_val = f'{{"itemId":"{item_id}"}}'
        for _ in range(3):
            res = await self._signed_post("mtop.taobao.idle.pc.detail", data_val)
            if res is None:
                await asyncio.sleep(NONE_RETRY_BACKOFF)
                continue
            ret_value = res.get("ret", [])
            if any("SUCCESS" in r for r in ret_value):
                return res
            error_msg = str(ret_value)
            if "RGV587_ERROR" in error_msg or "被挤爆啦" in error_msg:
                self._trip_risk_control(ret_value)
                return {"error": f"风控: {ret_value}"}
            # token 过期：本次已接住 Set-Cookie 新 token，下一轮循环自然走第二步握手
        return {"error": "获取商品信息失败"}

    async def get_item_list_info(self, user_id: str, page_number: int = 1, page_size: int = 20) -> dict:
        """获取卖家自己发布的商品列表（mtop.idle.web.xyh.item.list）。"""
        remaining = self._in_cooldown()
        if remaining > 0:
            return {"error": f"风控冷却中，剩余 {remaining}s"}

        data = {
            "needGroupInfo": False,
            "pageNumber": page_number,
            "pageSize": page_size,
            "groupName": "在售",
            "groupId": "58877261",
            "defaultGroup": True,
            "userId": user_id,
        }
        data_val = json.dumps(data, separators=(",", ":"))
        for _ in range(3):
            res = await self._signed_post(
                "mtop.idle.web.xyh.item.list", data_val,
                extra_params={"spm_cnt": "a21ybx.im.0.0"},
            )
            if res is None:
                await asyncio.sleep(NONE_RETRY_BACKOFF)
                continue
            ret_value = res.get("ret", [])
            if any("SUCCESS" in r for r in ret_value):
                card_list = res.get("data", {}).get("cardList", [])
                items = [c.get("cardData", {}) for c in card_list if c.get("cardData")]
                return {"success": True, "items": items, "page": page_number}

            error_msg = str(ret_value)
            if "RGV587_ERROR" in error_msg or "被挤爆啦" in error_msg:
                self._trip_risk_control(ret_value)
                return {"error": f"风控: {ret_value}"}
            # token 过期：本次已接住 Set-Cookie 新 token，下一轮循环自然走第二步握手
            logger.warning(f"商品列表API调用失败 page={page_number}: {ret_value}")
        return {"error": "获取商品列表失败，重试次数过多"}

    async def get_all_items(self, user_id: str, page_size: int = 20, max_pages: int | None = None) -> list:
        """分页拉取所有商品，返回 cardData 列表。"""
        all_items: list = []
        page = 1
        while True:
            if max_pages and page > max_pages:
                break
            result = await self.get_item_list_info(user_id, page, page_size)
            if "error" in result:
                logger.error(f"分页拉取中断 page={page}: {result['error']}")
                break
            items = result.get("items", [])
            if not items:
                break
            all_items.extend(items)
            if len(items) < page_size:
                break
            page += 1
            await asyncio.sleep(1)
        return all_items
