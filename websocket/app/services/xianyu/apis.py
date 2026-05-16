import asyncio
import json
import time
import aiohttp
from loguru import logger
from common.utils import generate_sign


class XianyuApis:
    def __init__(self, cookies_str: str):
        self.cookies_str = cookies_str
        self.cookies = self._parse_cookies(cookies_str)
        self._headers = {
            "accept": "application/json",
            "origin": "https://www.goofish.com",
            "referer": "https://www.goofish.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        }

    def _parse_cookies(self, cookies_str: str) -> dict:
        cookies = {}
        for item in cookies_str.split("; "):
            parts = item.split("=", 1)
            if len(parts) == 2:
                cookies[parts[0]] = parts[1]
        return cookies

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    async def get_token(self, device_id: str, retry_count: int = 0) -> dict | None:
        if retry_count >= 3:
            login_ok = await self.has_login()
            if login_ok:
                return await self.get_token(device_id, 0)
            logger.error("Cookie已失效")
            return None

        t = str(int(time.time()) * 1000)
        data_val = f'{{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"{device_id}"}}'
        token = self.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign,
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.taobao.idlemessage.pc.login.token",
            "sessionOption": "AutoLoginOnly",
        }

        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(
                "https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/",
                params=params, data={"data": data_val}
            ) as resp:
                res = await resp.json()
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value

        if not isinstance(res, dict):
            return await self.get_token(device_id, retry_count + 1)

        ret_value = res.get("ret", [])
        if any("SUCCESS" in r for r in ret_value):
            logger.info("Token获取成功")
            return res

        error_msg = str(ret_value)
        if "RGV587_ERROR" in error_msg or "被挤爆啦" in error_msg:
            logger.error(f"触发风控: {ret_value}")
            return None

        logger.warning(f"Token API调用失败: {ret_value}")
        return await self.get_token(device_id, retry_count + 1)

    async def has_login(self) -> bool:
        url = "https://passport.goofish.com/newlogin/hasLogin.do"
        data = {
            "hid": self.cookies.get("unb", ""),
            "ltl": "true", "appName": "xianyu", "appEntrance": "web",
            "fromSite": "77", "lang": "zh_CN",
        }
        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(url, params={"appName": "xianyu", "fromSite": "77"}, data=data) as resp:
                res = await resp.json()
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value
        return res.get("content", {}).get("success", False)

    async def get_item_info(self, item_id: str, retry_count: int = 0) -> dict:
        if retry_count >= 3:
            return {"error": "获取商品信息失败"}

        t = str(int(time.time()) * 1000)
        data_val = f'{{"itemId":"{item_id}"}}'
        token = self.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign,
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.taobao.idle.pc.detail",
            "sessionOption": "AutoLoginOnly",
        }

        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(
                "https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/",
                params=params, data={"data": data_val}
            ) as resp:
                res = await resp.json()
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value

        if isinstance(res, dict):
            ret_value = res.get("ret", [])
            if any("SUCCESS" in r for r in ret_value):
                return res
        return await self.get_item_info(item_id, retry_count + 1)

    async def get_item_list_info(self, user_id: str, page_number: int = 1, page_size: int = 20, retry_count: int = 0) -> dict:
        """获取卖家自己发布的商品列表（mtop.idle.web.xyh.item.list）。"""
        if retry_count >= 3:
            return {"error": "获取商品列表失败，重试次数过多"}

        t = str(int(time.time()) * 1000)
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
        token = self.cookies.get("_m_h5_tk", "").split("_")[0]
        sign = generate_sign(t, token, data_val)

        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": t, "sign": sign,
            "v": "1.0", "type": "originaljson", "accountSite": "xianyu",
            "dataType": "json", "timeout": "20000",
            "api": "mtop.idle.web.xyh.item.list",
            "sessionOption": "AutoLoginOnly",
            "spm_cnt": "a21ybx.im.0.0",
        }

        async with aiohttp.ClientSession(headers=self._headers, cookies=self.cookies) as session:
            async with session.post(
                "https://h5api.m.goofish.com/h5/mtop.idle.web.xyh.item.list/1.0/",
                params=params, data={"data": data_val}
            ) as resp:
                res = await resp.json()
                for cookie in resp.cookies.values():
                    self.cookies[cookie.key] = cookie.value

        if not isinstance(res, dict):
            return await self.get_item_list_info(user_id, page_number, page_size, retry_count + 1)

        ret_value = res.get("ret", [])
        if any("SUCCESS" in r for r in ret_value):
            card_list = res.get("data", {}).get("cardList", [])
            items = [c.get("cardData", {}) for c in card_list if c.get("cardData")]
            return {"success": True, "items": items, "page": page_number}

        error_msg = str(ret_value)
        if "RGV587_ERROR" in error_msg or "被挤爆啦" in error_msg:
            logger.error(f"获取商品列表触发风控: {ret_value}")
            return {"error": f"风控: {ret_value}"}

        logger.warning(f"商品列表API调用失败 page={page_number}: {ret_value}")
        return await self.get_item_list_info(user_id, page_number, page_size, retry_count + 1)

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
