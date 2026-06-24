#!/usr/bin/env python3
"""调用 1688ai 卡密查询接口，若 card_code_obj 有值则打印卡密。

接口被 Cloudflare Managed Challenge 保护，需用浏览器过一次人机验证后，
把 cf_clearance cookie 和当时的 User-Agent 填到下面两个常量里。
注意：cf_clearance 绑定 IP + User-Agent + TLS 指纹，所以
1) 必须用与抓 cookie 时同一台机器（同出口 IP）跑脚本；
2) USER_AGENT 必须与你浏览器完全一致；
3) cookie 会过期（几十分钟到几小时），失效后重新抓一次即可。

依赖：pip install curl_cffi  （用它模拟 Chrome 的 TLS/JA3 指纹）
"""
import sys
import json

from curl_cffi import requests as cffi_requests

API_BASE = "https://86ai.one/tasks/card"

# ↓↓↓ 在浏览器 F12 → Application/Network 里复制这两个值 ↓↓↓
CF_CLEARANCE = "cf_clearance=AZF08s8qKlZob90AB8H_MVVpzUG2cwNXGObQGiFeMkg-1782120205-1.2.1.1-NDzhzux0jfMPka1oGHSKAWocR8pykcJ4at0GVsGVlRq_9oWtqBiExUCgpjrWAHOJl.wyMgoGdWA6ew3qSZn9FFlOGNounrk0CTxmvbr_Y4f_Y.aBIJ5bOobwU88GL2wkItHSzS1x5CufAXEqRZS_4u1IzTOSahmDHqNsW_LA8fabOqKu4ztE_cJ4d4yzG17AUp2P8IttYuCkjlPp8.CSUE70i0HXVuuOsvou5XcK7m1urftCq9tA_Nt.5m3JW698R5dplbCltk3AXl2oWLH23qKNtNmrfTLc4pOJok.483ZK6QTpjhfsrcywLYvQ44TMkfelisUfp1ucs.W71mRUdFxqLKnToRLK4gic.72P5sxzsFVN0zMylFS5oxnVU00PT61_9BKr0tIILHxF9y0Qnt3X7iYZUFME4XM9DMomXdshtTMY2b.sicO4QVg9D_pJ"

# 必须与抓 cookie 时浏览器的 UA 完全一致，否则 cf_clearance 失效
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

# curl_cffi 模拟的浏览器指纹，尽量与 USER_AGENT 的 Chrome 大版本对齐
IMPERSONATE = "chrome120"
# ↑↑↑ 配置区结束 ↑↑↑

# 排除的卡密文件（一行一个，空行和 # 注释会被忽略）
EXCLUDE_CODES_FILE = "exclued_codes.txt"

# 卡密来源文件：TSV 格式，首行表头，第一列为卡号（制表符分隔）。
# 命令行传参优先；否则从此文件读取。
CARD_CODES_FILE = "gemini pro订阅_20260622164559.txt"


def _emit(card_code: str, status: str, reason: str = "") -> None:
    """统一输出：卡密 状态 原因。"""
    print(f"{card_code}\t{status}\t{reason}")


# 卡号 → 出库时间（从 TSV 文件读入；命令行直接传卡号时为空）
OUTBOUND_TIME: dict[str, str] = {}


def check_card(card_code: str, page: int = 1, page_size: int = 20) -> None:
    url = f"{API_BASE}/{card_code}?page={page}&page_size={page_size}"
    resp = cffi_requests.get(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        cookies={"cf_clearance": CF_CLEARANCE},
        impersonate=IMPERSONATE,
        timeout=15,
    )

    # Cloudflare 拦截时返回 403 + HTML 质询页
    if resp.status_code != 200:
        if "Just a moment" in resp.text or resp.status_code == 403:
            _emit(card_code, "错误", "Cloudflare拦截(cf_clearance过期或UA/IP不匹配)")
        else:
            _emit(card_code, "错误", f"HTTP {resp.status_code}")
        return

    payload = resp.json()

    if not payload.get("success"):
        _emit(card_code, "错误", f"接口返回失败: {payload}")
        return

    card_code_obj = payload.get("data", {}).get("card_code_obj")

    # card_code_obj 为空 dict / None → 暂无卡密
    if not card_code_obj:
        _emit(card_code, "无卡密", "card_code_obj为空")
        return

    # 有值：按额度判断已用完 / 可用
    total = card_code_obj.get("total_quota")
    used = card_code_obj.get("used_quota")
    if isinstance(total, int) and isinstance(used, int):
        if used >= total:
            _emit(card_code, "已用完", f"已用 {used}/{total}")
        else:
            # 可用：在原因后附出库时间（若文件里有）
            reason = f"已用 {used}/{total}"
            outbound = OUTBOUND_TIME.get(card_code)
            if outbound:
                reason += f"  出库时间 {outbound}"
            _emit(card_code, "可用", reason)
    else:
        # 缺额度字段时原样附详情，避免误判
        _emit(card_code, "可用", json.dumps(card_code_obj, ensure_ascii=False))


def parse_codes(raw: str) -> list[str]:
    """逐行解析卡密，去掉空行、首尾空白和 # 注释行。"""
    codes = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        codes.append(line)
    return codes


def read_codes_from_file(path: str) -> list[str]:
    """从 TSV 文件读卡号：跳过表头，取每行第一列（制表符分隔）。

    顺带把第 7 列“出库时间”填入全局 OUTBOUND_TIME 映射。
    """
    codes = []
    # utf-8-sig 自动吃掉文件开头的 BOM
    with open(path, encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            cols = line.split("\t")
            code = cols[0].strip()
            # 跳过表头行（第一列是“卡号”二字而非真正的卡号）
            if i == 0 and code == "卡号":
                continue
            if not code or code.startswith("#"):
                continue
            codes.append(code)
            # 第 7 列（索引 6）为出库时间，存在则记录
            if len(cols) > 6 and cols[6].strip():
                OUTBOUND_TIME[code] = cols[6].strip()
    return codes


if __name__ == "__main__":
    # 命令行传参优先，否则从 CARD_CODES_FILE 读取
    if len(sys.argv) > 1:
        codes = sys.argv[1:]
    else:
        try:
            codes = read_codes_from_file(CARD_CODES_FILE)
        except FileNotFoundError:
            print(f"找不到卡密文件：{CARD_CODES_FILE}")
            sys.exit(1)
    if not codes:
        print(f"没有可查询的卡密，请检查文件 {CARD_CODES_FILE} 或命令行参数。")
        sys.exit(1)

    # 过滤掉排除列表中的卡密（排除文件可选，不存在则视为空）
    try:
        with open(EXCLUDE_CODES_FILE, encoding="utf-8-sig") as f:
            exclude_set = set(parse_codes(f.read()))
    except FileNotFoundError:
        exclude_set = set()
    codes = [c for c in codes if c not in exclude_set]
    if not codes:
        print("所有卡密都在排除列表中，无需查询。")
        sys.exit(0)

    # 表头
    _emit("卡密", "状态", "原因")
    for code in codes:
        try:
            check_card(code)
        except Exception as e:
            _emit(code, "错误", str(e))
