#!/usr/bin/env python3
"""调用 1688ai 卡密查询接口，若 card_code_obj 有值则打印卡密。"""
import sys
import ssl
import json
import urllib.request

API_BASE = "https://1688ai.vip/tasks/card"

# 在这里填卡密，一行一个（空行和 # 开头的行会被忽略）
CARD_CODES = """
7379M9G0AR7LSX9Z
ZUZX3D1IT98PIWRD
W1E3DUEOI2V9C4UT
9WUV57NHVCE5LVHM
K19MEVCL6ZPUNPHP
YKIH0AH3AY8ZM6OG
3UMYH5GE3C1H1WG1
E2RT013JRYY5FJZB
NLLXHDF99GUAZ194
Y9R18E5WCCSUDM36
DG62Y2SFHURLXUAA
1MC7L0HATPNGSRCA
CRO73X98228NBIGQ
F4B6HPZDH1KV8R3C
BUR7GC9VD119TPFF
MSHRZ6JB74EDPVV2
LRYT95K7MW906MD7
L3XV9FT00I9KELIL
DJ3P22WIUDF93EVY
PL67K2XBGIZTVKUY
22SPAIDHVWG7FZIR
WS3OAFXQQWLJ6HLA
ISR96341DWQJF6K0
DREJGJZ01S3ZO0I7
Y94JXZZNA3WRPPV8
V5D0EP4NGKWPSIS4
RQZRIG914S8F8YAC
4NJXGGVG2T4LOJ8O
QDO585LTO6W5X8PY
6FG1RHTZEGR1YLHZ
GFLF8GPP46GDLTGC
ELIYKIEUMG3SNRGE
A1UBCNKW34RS0HFT
FD58YQ7DH5J0OKED
0HL497XUBJLZ5PZJ
TV41PONC7C72C3I7
ZN28WMBLXYAH63DZ
MQRZ7BEMDRQJ9QHM
LACMGIHTEXVCJTB7
F5YS9EBRIJTABQWS
971MEWHIXKYP1OUC
DNDJHLUWEG3OSUYU
YKXWI7MR6JZC01K0
0YT7VRC8QTRGNMRS
AS9MMBKCNHAXD0HO
68RSNKS2495MK3LY
FY0SZPX333DHP610
3OMYPQ3Y1C3KT148
WQ0T0DIREU5TMV47
9M4UVV24LSN8EPLS
7KFPUWUNP3EQNYXP
VDKO3JIYLWPA77R4
VVRCW4214NW88M0U
VV851MO5S5W40G2R
76WXB5YX5IY8WO6N
R6KU5WPU843COOU9
76YG9D4U0G8MB0EP
LDNJXGHY2DRVJK32
EVM5TXOG92LFVAGJ
IT4Y77LCO5NIBXN9
SORBJBDR2PIU9PEN
"""


def _build_ssl_context() -> ssl.SSLContext:
    """优先用 certifi 证书；缺失（如 python.org 版未装系统 CA）则回退到不校验。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


def check_card(card_code: str, page: int = 1, page_size: int = 20) -> int:
    url = f"{API_BASE}/{card_code}?page={page}&page_size={page_size}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=15, context=_build_ssl_context()) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if not payload.get("success"):
        print(f"[{card_code}] 接口返回失败: {payload}")
        return

    card_code_obj = payload.get("data", {}).get("card_code_obj")

    # card_code_obj 有值（非空 dict）即认为卡密有效
    if card_code_obj:
        print(f"卡密: {card_code}  详情: {json.dumps(card_code_obj, ensure_ascii=False)}")
    else:
        print(f"[{card_code}] card_code_obj 为空，暂无卡密")


def parse_codes(raw: str) -> list[str]:
    """逐行解析卡密，去掉空行、首尾空白和 # 注释行。"""
    codes = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        codes.append(line)
    return codes


if __name__ == "__main__":
    # 命令行传参优先，否则用脚本顶部的 CARD_CODES
    codes = sys.argv[1:] if len(sys.argv) > 1 else parse_codes(CARD_CODES)
    if not codes:
        print("没有可查询的卡密，请在脚本顶部 CARD_CODES 中填入，一行一个。")
        sys.exit(1)

    for code in codes:
        try:
            check_card(code)
        except Exception as e:
            print(f"[{code}] 查询出错: {e}")
