from .douyin import DouyinExtractor
from .xiaohongshu import XiaohongshuExtractor
from .bilibili import BilibiliExtractor
from .weibo import WeiboExtractor
from .zhihu import ZhihuExtractor
from .kuaishou import KuaishouExtractor
from .youtube import YoutubeExtractor
from .twitter import TwitterExtractor
from .goofish import GooFishExtractor
from .._legacy import detect_platform, extract as _extract

EXTRACTORS = {
    "douyin": DouyinExtractor,
    "xiaohongshu": XiaohongshuExtractor,
    "bilibili": BilibiliExtractor,
    "weibo": WeiboExtractor,
    "zhihu": ZhihuExtractor,
    "kuaishou": KuaishouExtractor,
    "youtube": YoutubeExtractor,
    "twitter": TwitterExtractor,
    "goofish": GooFishExtractor,
}


def extract(url: str, *args, analyze: bool = False, **kwargs):
    return _extract(url, *args, analyze=analyze, **kwargs)


__all__ = ["EXTRACTORS", "extract", "detect_platform"]
