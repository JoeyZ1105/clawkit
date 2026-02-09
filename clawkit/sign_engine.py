#!/usr/bin/env python3
"""
sign_engine.py — 社交媒体 API 签名引擎

抖音: ABogus 签名 (SM3 国密哈希)
小红书: x-s / x-t / x-s-common 签名 (MD5 + 自定义 Base64)

依赖: gmssl (仅抖音签名需要)
"""

import ctypes
import hashlib
import json
import random
import string
import time
import urllib.parse
from binascii import crc32
from random import choice, randint
from typing import Optional
from urllib.parse import quote, urlencode

__all__ = ["sign_douyin", "sign_xiaohongshu", "get_xhs_cookies"]

# ════════════════════════════════════════════════════════════════════════════════
# 抖音 ABogus 签名
# 基于 TikTokDownloader (JoeanAmier) 的纯 Python 实现
# 核心算法: SM3 国密哈希 → RC4 加密 → 自定义 Base64 编码
# ════════════════════════════════════════════════════════════════════════════════

_DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_DEFAULT_BROWSER = "1536|742|1536|864|0|0|0|0|1536|864|1536|864|1536|742|24|24|Win32"

_ABOGUS_STR = {
    "s0": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
    "s1": "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
    "s2": "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
    "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
    "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
}

_SM3_IV = [
    1937774191, 1226093241, 388252375, 3666478592,
    2842636476, 372324522, 3817729613, 2969243214,
]


def _sm3_hash(data: bytes) -> list[int]:
    """SM3 哈希，返回 32 字节整数数组（纯 Python，无需 gmssl）"""
    b = list(data)
    size = len(b)
    reg = _SM3_IV[:]
    chunks = [b[i:i + 64] for i in range(0, len(b), 64)]
    if not chunks:
        chunks = [[]]
    last = chunks[-1]
    for chunk in chunks[:-1]:
        reg = _sm3_compress(reg, chunk)
    # Padding
    last.append(0x80)
    # Pad to 56 bytes mod 64
    while len(last) % 64 != 56:
        last.append(0)
    # Append bit length as 8 bytes big-endian
    bit_len = 8 * size
    for i in range(7, -1, -1):
        last.append((bit_len >> (8 * i)) & 255)
    # Process remaining blocks
    for i in range(0, len(last), 64):
        reg = _sm3_compress(reg, last[i:i + 64])
    # Convert to byte array
    result = []
    for v in reg:
        for shift in (24, 16, 8, 0):
            result.append((v >> shift) & 255)
    return result


def _sm3_double(data: str | list) -> list[int]:
    """双重 SM3 哈希"""
    if isinstance(data, str):
        b = data.encode("utf-8")
    else:
        b = bytes(data)
    first = _sm3_hash(b)
    return _sm3_hash(bytes(first))


def _rc4(plaintext: str, key: str) -> str:
    """RC4 加密"""
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + ord(key[i % len(key)])) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    cipher = []
    for k in range(len(plaintext)):
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        cipher.append(chr(s[(s[i] + s[j]) % 256] ^ ord(plaintext[k])))
    return "".join(cipher)


def _custom_b64(s: str, table_key: str = "s4") -> str:
    """自定义 Base64 编码"""
    table = _ABOGUS_STR[table_key]
    r = []
    for i in range(0, len(s), 3):
        if i + 2 < len(s):
            n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8) | ord(s[i + 2])
        elif i + 1 < len(s):
            n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8)
        else:
            n = ord(s[i]) << 16
        for j, k in zip(range(18, -1, -6), (0xFC0000, 0x03F000, 0x0FC0, 0x3F)):
            if j == 6 and i + 1 >= len(s):
                break
            if j == 0 and i + 2 >= len(s):
                break
            r.append(table[(n & k) >> j])
    r.append("=" * ((4 - len(r) % 4) % 4))
    return "".join(r)


def _de(e: int, r: int) -> int:
    """循环左移"""
    r %= 32
    return ((e << r) & 0xFFFFFFFF) | (e >> (32 - r))


def _random_list(a=None, b=170, c=85, d=0, e=0, f=0, g=0):
    r = a or (random.random() * 10000)
    v = [r, int(r) & 255, int(r) >> 8]
    return [v[1] & b | d, v[1] & c | e, v[2] & b | f, v[2] & c | g]


def _gen_string_1():
    s1 = _random_list(b=170, c=85, d=1, e=2, f=5, g=45 & 170)
    s2 = _random_list(b=170, c=85, d=1)
    s3 = _random_list(b=170, c=85, d=1, f=5)
    return "".join(chr(c) for c in s1 + s2 + s3)


class _ABogus:
    """ABogus 签名核心"""

    def __init__(self, user_agent: str):
        self.browser = _DEFAULT_BROWSER
        self.browser_len = len(self.browser)
        self.browser_code = [ord(c) for c in self.browser]
        ua_rc4 = _rc4(user_agent, "\u0000\u0001\u000e")
        ua_b64 = _custom_b64(ua_rc4, "s3")
        self.ua_code = self._sm3_sum(ua_b64)

    @staticmethod
    def _sm3_sum(data: str) -> list[int]:
        """SM3 哈希，使用内联压缩"""
        reg = _SM3_IV[:]
        b = [ord(c) for c in data] if isinstance(data, str) else list(data)
        size = len(b)
        # Split into 64-byte chunks
        chunks = [b[i:i + 64] for i in range(0, len(b), 64)]
        if len(chunks) == 0:
            chunks = [[]]
        last = chunks[-1]
        for chunk in chunks[:-1]:
            reg = _sm3_compress(reg, chunk)
        # Padding
        last.append(128)
        while len(last) < 60:
            last.append(0)
        bit_len = 8 * size
        for i in range(4):
            last.append((bit_len >> 8 * (3 - i)) & 255)
        reg = _sm3_compress(reg, last)
        # Convert to byte array
        o = [0] * 32
        for i in range(8):
            c = reg[i]
            o[4 * i + 3] = 255 & c
            c >>= 8
            o[4 * i + 2] = 255 & c
            c >>= 8
            o[4 * i + 1] = 255 & c
            c >>= 8
            o[4 * i] = 255 & c
        return o

    def sign(self, params: str, method: str = "GET") -> str:
        start_time = int(time.time() * 1000)
        end_time = start_time + randint(4, 8)

        params_code = _sm3_double(params + "cus")
        method_code = _sm3_double(method + "cus")

        a = [
            44, (end_time >> 24) & 255, 0, 0, 0, 0,
            24, params_code[21], method_code[21], 0,
            self.ua_code[23], (end_time >> 16) & 255, 0, 0, 0, 1,
            0, 239, params_code[22], method_code[22],
            self.ua_code[24], (end_time >> 8) & 255, 0, 0, 0, 0,
            (end_time >> 0) & 255, 0, 0, 14,
            (start_time >> 24) & 255, (start_time >> 16) & 255,
            0, (start_time >> 8) & 255, (start_time >> 0) & 255,
            3, int(end_time / 256 / 256 / 256 / 256) >> 0, 1,
            int(start_time / 256 / 256 / 256 / 256) >> 0, 1,
            self.browser_len, 0, 0, 0,
        ]

        check = 0
        for i in a:
            check ^= i
        a.extend(self.browser_code)
        a.append(check)

        string_2 = _rc4("".join(chr(c) for c in a), "y")
        string_1 = _gen_string_1()
        return _custom_b64(string_1 + string_2, "s4")


def sign_douyin(params: str, user_agent: str = _DEFAULT_UA, method: str = "GET") -> str:
    """
    生成抖音 a_bogus 签名参数

    Args:
        params: URL query string (不含 ?)
        user_agent: User-Agent 字符串
        method: HTTP 方法

    Returns:
        a_bogus 签名值
    """
    ab = _ABogus(user_agent)
    return ab.sign(params, method)


# ════════════════════════════════════════════════════════════════════════════════
# SM3 压缩函数（内联实现，避免依赖 gmssl 做签名结构计算）
# ════════════════════════════════════════════════════════════════════════════════

def _sm3_compress(reg: list[int], block: list[int]) -> list[int]:
    """SM3 压缩函数"""
    # 消息扩展
    w = [0] * 132
    for t in range(16):
        w[t] = ((block[4*t] << 24) | (block[4*t+1] << 16) |
                (block[4*t+2] << 8) | block[4*t+3]) & 0xFFFFFFFF
    for t in range(16, 68):
        a = w[t-16] ^ w[t-9] ^ _de(w[t-3], 15)
        a = a ^ _de(a, 15) ^ _de(a, 23)
        w[t] = (a ^ _de(w[t-13], 7) ^ w[t-6]) & 0xFFFFFFFF
    for t in range(68, 132):
        w[t] = (w[t-68] ^ w[t-64]) & 0xFFFFFFFF

    # 压缩
    v = reg[:]
    for o in range(64):
        tj = 2043430169 if o < 16 else 2055708042
        c = (_de(v[0], 12) + v[4] + _de(tj, o)) & 0xFFFFFFFF
        c = _de(c, 7)
        s = (c ^ _de(v[0], 12)) & 0xFFFFFFFF

        if o < 16:
            ff = (v[0] ^ v[1] ^ v[2]) & 0xFFFFFFFF
            gg = (v[4] ^ v[5] ^ v[6]) & 0xFFFFFFFF
        else:
            ff = (v[0] & v[1] | v[0] & v[2] | v[1] & v[2]) & 0xFFFFFFFF
            gg = (v[4] & v[5] | ~v[4] & v[6]) & 0xFFFFFFFF

        u = (ff + v[3] + s + w[o + 68]) & 0xFFFFFFFF
        b = (gg + v[7] + c + w[o]) & 0xFFFFFFFF

        v[3] = v[2]
        v[2] = _de(v[1], 9)
        v[1] = v[0]
        v[0] = u
        v[7] = v[6]
        v[6] = _de(v[5], 19)
        v[5] = v[4]
        v[4] = (b ^ _de(b, 9) ^ _de(b, 17)) & 0xFFFFFFFF

    return [(reg[i] ^ v[i]) & 0xFFFFFFFF for i in range(8)]


# ════════════════════════════════════════════════════════════════════════════════
# 小红书签名
# 基于 ReaJason/xhs 的纯 Python 实现
# 核心算法: MD5 → 自定义 Base64 → CRC32 变体
# ════════════════════════════════════════════════════════════════════════════════

_XHS_B64_TABLE = "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5"

_MRC_TABLE = [
    0, 1996959894, 3993919788, 2567524794, 124634137, 1886057615, 3915621685,
    2657392035, 249268274, 2044508324, 3772115230, 2547177864, 162941995,
    2125561021, 3887607047, 2428444049, 498536548, 1789927666, 4089016648,
    2227061214, 450548861, 1843258603, 4107580753, 2211677639, 325883990,
    1684777152, 4251122042, 2321926636, 335633487, 1661365465, 4195302755,
    2366115317, 997073096, 1281953886, 3579855332, 2724688242, 1006888145,
    1258607687, 3524101629, 2768942443, 901097722, 1119000684, 3686517206,
    2898065728, 853044451, 1172266101, 3705015759, 2882616665, 651767980,
    1373503546, 3369554304, 3218104598, 565507253, 1454621731, 3485111705,
    3099436303, 671266974, 1594198024, 3322730930, 2970347812, 795835527,
    1483230225, 3244367275, 3060149565, 1994146192, 31158534, 2563907772,
    4023717930, 1907459465, 112637215, 2680153253, 3904427059, 2013776290,
    251722036, 2517215374, 3775830040, 2137656763, 141376813, 2439277719,
    3865271297, 1802195444, 476864866, 2238001368, 4066508878, 1812370925,
    453092731, 2181625025, 4111451223, 1706088902, 314042704, 2344532202,
    4240017532, 1658658271, 366619977, 2362670323, 4224994405, 1303535960,
    984961486, 2747007092, 3569037538, 1256170817, 1037604311, 2765210733,
    3554079995, 1131014506, 879679996, 2909243462, 3663771856, 1141124467,
    855842277, 2852801631, 3708648649, 1342533948, 654459306, 3188396048,
    3373015174, 1466479909, 544179635, 3110523913, 3462522015, 1591671054,
    702138776, 2966460450, 3352799412, 1504918807, 783551873, 3082640443,
    3233442989, 3988292384, 2596254646, 62317068, 1957810842, 3939845945,
    2647816111, 81470997, 1943803523, 3814918930, 2489596804, 225274430,
    2053790376, 3826175755, 2466906013, 167816743, 2097651377, 4027552580,
    2265490386, 503444072, 1762050814, 4150417245, 2154129355, 426522225,
    1852507879, 4275313526, 2312317920, 282753626, 1742555852, 4189708143,
    2394877945, 397917763, 1622183637, 3604390888, 2714866558, 953729732,
    1340076626, 3518719985, 2797360999, 1068828381, 1219638859, 3624741850,
    2936675148, 906185462, 1090812512, 3747672003, 2825379669, 829329135,
    1181335161, 3412177804, 3160834842, 628085408, 1382605366, 3423369109,
    3138078467, 570562233, 1426400815, 3317316542, 2998733608, 733239954,
    1555261956, 3268935591, 3050360625, 752459403, 1541320221, 2607071920,
    3965973030, 1969922972, 40735498, 2617837225, 3943577151, 1913087877,
    83908371, 2512341634, 3803740692, 2075208622, 213261112, 2463272603,
    3855990285, 2094854071, 198958881, 2262029012, 4057260610, 1759359992,
    534414190, 2176718541, 4139329115, 1873836001, 414664567, 2282248934,
    4279200368, 1711684554, 285281116, 2405801727, 4167216745, 1634467795,
    376229701, 2685067896, 3608007406, 1308918612, 956543938, 2808555105,
    3495958263, 1231636301, 1047427035, 2932959818, 3654703836, 1088359270,
    936918000, 2847714899, 3736837829, 1202900863, 817233897, 3183342108,
    3401237130, 1404277552, 615818150, 3134207493, 3453421203, 1423857449,
    601450431, 3009837614, 3294710456, 1567103746, 711928724, 3020668471,
    3272380065, 1510334235, 755167117,
]


def _mrc(e: str) -> int:
    """CRC32 变体"""
    o = -1
    def _rws(num, bit=0):
        val = ctypes.c_uint32(num).value >> bit
        M = 4294967295
        return (val + (M + 1)) % (2 * (M + 1)) - M - 1
    for n in range(57):
        o = _MRC_TABLE[(o & 255) ^ ord(e[n])] ^ _rws(o, 8)
    return o ^ -1 ^ 3988292384


def _xhs_h(n: str) -> str:
    """自定义 Base64 编码 MD5"""
    d = "A4NjFqYu5wPHsO0XTdDgMa2r1ZQocVte9UJBvk6/7=yRnhISGKblCWi+LpfE8xzm3"
    m = ""
    for i in range(0, 32, 3):
        o = ord(n[i])
        g = ord(n[i + 1]) if i + 1 < 32 else 0
        h = ord(n[i + 2]) if i + 2 < 32 else 0
        x = ((o & 3) << 4) | (g >> 4)
        p = ((15 & g) << 2) | (h >> 6)
        v = o >> 2
        b = h & 63 if h else 64
        if not g:
            p = b = 64
        m += d[v] + d[x] + d[p] + d[b]
    return m


def _xhs_b64_encode(e: list[int]) -> str:
    """小红书自定义 Base64"""
    lookup = _XHS_B64_TABLE

    def triplet(e):
        return lookup[63 & (e >> 18)] + lookup[63 & (e >> 12)] + lookup[(e >> 6) & 63] + lookup[e & 63]

    P = len(e)
    W = P % 3
    parts = []
    for H in range(0, P - W, 3):
        n = (16711680 & (e[H] << 16)) + ((e[H+1] << 8) & 65280) + (e[H+2] & 255)
        parts.append(triplet(n))
    if W == 1:
        F = e[P - 1]
        parts.append(lookup[F >> 2] + lookup[(F << 4) & 63] + "==")
    elif W == 2:
        F = (e[P - 2] << 8) + e[P - 1]
        parts.append(lookup[F >> 10] + lookup[63 & (F >> 4)] + lookup[(F << 2) & 63] + "=")
    return "".join(parts)


def _encode_utf8(e: str) -> list[int]:
    """URL 编码后转字节数组"""
    b = []
    m = urllib.parse.quote(e, safe="~()*!.'")
    w = 0
    while w < len(m):
        if m[w] == "%":
            b.append(int(m[w+1] + m[w+2], 16))
            w += 2
        else:
            b.append(ord(m[w]))
        w += 1
    return b


def get_xhs_cookies() -> tuple[str, str]:
    """生成小红书 a1 和 webId cookie"""
    def rand_str(n):
        return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))
    d = hex(int(time.time() * 1000))[2:] + rand_str(30) + "50000"
    g = (d + str(crc32(d.encode())))[:52]
    return g, hashlib.md5(g.encode()).hexdigest()


def sign_xiaohongshu(uri: str, data: Optional[dict] = None, a1: str = "", b1: str = "") -> dict:
    """
    生成小红书 API 签名头

    Args:
        uri: API path (如 /api/sns/web/v1/feed)
        data: POST body dict (可选)
        a1: cookie a1 值
        b1: localStorage b1 值

    Returns:
        {"x-s": ..., "x-t": ..., "x-s-common": ...}
    """
    v = int(time.time() * 1000)
    body = json.dumps(data, separators=(',', ':'), ensure_ascii=False) if isinstance(data, dict) else ''
    raw = f"{v}test{uri}{body}"
    md5 = hashlib.md5(raw.encode()).hexdigest()
    x_s = _xhs_h(md5)
    x_t = str(v)

    common = {
        "s0": 5, "s1": "", "x0": "1", "x1": "3.2.0", "x2": "Windows",
        "x3": "xhs-pc-web", "x4": "2.3.1", "x5": a1, "x6": x_t,
        "x7": x_s, "x8": b1, "x9": _mrc(x_t + x_s), "x10": 1,
    }
    encoded = _encode_utf8(json.dumps(common, separators=(',', ':')))
    x_s_common = _xhs_b64_encode(encoded)

    return {"x-s": x_s, "x-t": x_t, "x-s-common": x_s_common}


def get_xhs_search_id() -> str:
    """生成小红书搜索 ID"""
    e = int(time.time() * 1000) << 64
    t = int(random.uniform(0, 2147483646))
    num = e + t
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if num == 0:
        return '0'
    result = ''
    while num:
        num, i = divmod(num, 36)
        result = alphabet[i] + result
    return result


# ════════════════════════════════════════════════════════════════════════════════
# 测试
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 测试抖音签名
    print("=== 抖音 ABogus 签名测试 ===")
    try:
        params = "aweme_id=7603687816681311524&aid=6383&version_name=23.5.0"
        sig = sign_douyin(params)
        print(f"params: {params[:50]}...")
        print(f"a_bogus: {sig}")
        print(f"长度: {len(sig)} (预期 ~172)")
        print("✅ 签名生成成功")
    except ImportError as e:
        print(f"⚠️ {e}")
        print("尝试不依赖 gmssl 的内联 SM3...")

    # 测试小红书签名
    print("\n=== 小红书签名测试 ===")
    a1, web_id = get_xhs_cookies()
    headers = sign_xiaohongshu("/api/sns/web/v1/feed", a1=a1)
    print(f"a1: {a1[:20]}...")
    print(f"x-s: {headers['x-s'][:30]}...")
    print(f"x-t: {headers['x-t']}")
    print(f"x-s-common: {headers['x-s-common'][:30]}...")
    print("✅ 签名生成成功")
