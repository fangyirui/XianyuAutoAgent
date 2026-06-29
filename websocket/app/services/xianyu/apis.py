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

    def _absorb_set_cookies(self, resp) -> list[str]:
        """从响应的原始 Set-Cookie 头解析并写回 self.cookies，返回写回的 cookie 名列表。

        不能用 aiohttp 的 resp.cookies：它底层是 http.cookies.SimpleCookie，遇到闲鱼下发的
        Partitioned（CHIPS）属性会解析失败，把整批 cookie 静默丢弃——表现为 _m_h5_tk 明明
        在原始 Set-Cookie 头里，却进不了 self.cookies，两步握手第二步永远拿不到续期 token
        （持续刷屏 FAIL_SYS_TOKEN_EXOIRED）。这里只取每条 Set-Cookie 分号前的 name=value，
        绕开属性解析，从根上接住续期。"""
        names = []
        for raw in resp.headers.getall("Set-Cookie", []):
            first = raw.split(";", 1)[0].strip()
            if "=" not in first:
                continue
            k, v = first.split("=", 1)
            k = k.strip()
            if k:
                self.cookies[k] = v.strip()
                names.append(k)
        return names

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
                    self._absorb_set_cookies(resp)
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
            res = await self._signed_post("mtop.taobao.idlemessage.pc.login.token", data_val)
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

            # token 过期是两步握手的第一步：本次请求已通过 Set-Cookie 接住服务端新下发的
            # _m_h5_tk（见 _signed_post → _absorb_set_cookies），下一次 attempt 直接拿它
            # 签名即为正确的第二步。切勿在此 pop 掉新 token，否则永远停在第一步、握手完不成。
            logger.warning(f"Token API调用失败: {ret_value}")

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
                    self._absorb_set_cookies(resp)
        return res.get("content", {}).get("success", False)

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
