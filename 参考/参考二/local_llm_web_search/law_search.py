"""
法条搜索和验证模块
通过国家法律法规库 (flk.npc.gov.cn) 的真实 API 搜索和验证法条

已验证的 API 接口：
- GET  /law-search/prompts/search?title=xxx     搜索建议
- POST /law-search/search/list                    搜索法律列表
- GET  /law-search/search/flfgDetails?bbbs=xxx    获取法律详情（含目录树）
- GET  /law-search/search/enumData                获取分类枚举
- GET  /law-search/index/aggregateData            获取统计数据
"""

import json
import re
import requests
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class LawSearchResult:
    """法律搜索结果"""
    title: str              # 法律标题
    bbbs: str               # 法律唯一 ID（用于获取详情）
    gbrq: str               # 公布日期
    sxrq: str               # 施行日期
    sxx: int                # 时效性：1=已废止, 2=已修改, 3=有效, 4=尚未生效
    flxz: str               # 法律性质：法律、行政法规、地方性法规等
    zdjg_name: str          # 制定机关
    source: str = "国家法律法规数据库"  # 数据来源
    detail_url: str = ""    # 详情页链接

    @property
    def is_valid(self) -> bool:
        """是否现行有效"""
        return self.sxx == 3

    @property
    def status_text(self) -> str:
        status_map = {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效"}
        return status_map.get(self.sxx, "未知")

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "bbbs": self.bbbs,
            "gbrq": self.gbrq,
            "sxrq": self.sxrq,
            "sxx": self.sxx,
            "status": self.status_text,
            "is_valid": self.is_valid,
            "flxz": self.flxz,
            "zdjg_name": self.zdjg_name,
            "source": self.source,
            "detail_url": self.detail_url
        }


@dataclass
class LawTreeNode:
    """法律目录树节点"""
    id: str
    title: str
    index: int
    children: List['LawTreeNode'] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "children": [c.to_dict() for c in self.children]
        }


class FLKApiClient:
    """
    国家法律法规数据库 API 客户端
    基于 flk.npc.gov.cn 的真实 API 接口
    """

    BASE_URL = "https://flk.npc.gov.cn"

    def __init__(self, timeout: int = 15):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://flk.npc.gov.cn/',
            'Content-Type': 'application/json;charset=utf-8'
        })
        self.timeout = timeout

    def _clean_html(self, text: str) -> str:
        """去除 HTML 标签"""
        return re.sub(r'<[^>]+>', '', text)

    def search_suggest(self, title: str) -> List[str]:
        """
        搜索建议（输入提示）
        GET /law-search/prompts/search?title=xxx

        Args:
            title: 搜索关键词

        Returns:
            建议标题列表
        """
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/law-search/prompts/search",
                params={"title": title},
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 200:
                return [
                    self._clean_html(item["title"])
                    for item in data.get("data", [])
                ]
            return []
        except Exception as e:
            print(f"搜索建议请求失败: {e}")
            return []

    def search_laws(
        self,
        keyword: str,
        search_type: int = 2,
        page: int = 1,
        page_size: int = 10,
        flfg_code_id: Optional[List] = None,
        zdjg_code_id: Optional[List] = None,
        sxx: Optional[List] = None,
        gbrq_year: Optional[List] = None
    ) -> Tuple[List[LawSearchResult], int]:
        """
        搜索法律法规
        POST /law-search/search/list

        Args:
            keyword: 搜索关键词
            search_type: 搜索类型 1=精确 2=模糊（默认）
            page: 页码
            page_size: 每页数量
            flfg_code_id: 法律分类 ID 列表
            zdjg_code_id: 制定机关 ID 列表
            sxx: 时效性筛选
            gbrq_year: 公布年份筛选

        Returns:
            (搜索结果列表, 总数)
        """
        try:
            payload = {
                "searchRange": 1,
                "sxrq": [],
                "gbrq": [],
                "searchType": search_type,
                "sxx": sxx or [],
                "gbrqYear": gbrq_year or [],
                "flfgCodeId": flfg_code_id or [],
                "zdjgCodeId": zdjg_code_id or [],
                "searchContent": keyword,
                "page": page,
                "pageSize": page_size
            }

            resp = self.session.post(
                f"{self.BASE_URL}/law-search/search/list",
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 200 and "rows" not in data:
                return [], 0

            results = []
            for row in data.get("rows", []):
                results.append(LawSearchResult(
                    title=self._clean_html(row.get("title", "")),
                    bbbs=row.get("bbbs", ""),
                    gbrq=row.get("gbrq", ""),
                    sxrq=row.get("sxrq", ""),
                    sxx=row.get("sxx", 0),
                    flxz=row.get("flxz", ""),
                    zdjg_name=row.get("zdjgName", ""),
                    detail_url=f"{self.BASE_URL}/detail2?id={row.get('bbbs', '')}"
                ))

            total = data.get("total", 0)
            return results, total

        except Exception as e:
            print(f"搜索法律法规请求失败: {e}")
            return [], 0

    def get_law_detail(self, bbbs: str) -> Optional[Dict]:
        """
        获取法律详情（含目录树结构）
        GET /law-search/search/flfgDetails?bbbs=xxx

        Args:
            bbbs: 法律唯一 ID

        Returns:
            法律详情字典，包含 title, gbrq, sxrq, sxx, flxz, zdjgName,
            content(目录树), ossFile(文件下载信息) 等
        """
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/law-search/search/flfgDetails",
                params={"bbbs": bbbs},
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 200:
                return data.get("data")
            return None

        except Exception as e:
            print(f"获取法律详情失败: {e}")
            return None

    def get_law_toc(self, bbbs: str) -> Optional[LawTreeNode]:
        """
        获取法律目录树
        从 flfgDetails 接口的 content 字段解析

        Args:
            bbbs: 法律唯一 ID

        Returns:
            目录树根节点
        """
        detail = self.get_law_detail(bbbs)
        if not detail or not detail.get("content"):
            return None

        content = detail["content"]
        return self._parse_toc(content)

    def _parse_toc(self, node_data: Dict) -> LawTreeNode:
        """递归解析目录树"""
        children = []
        for child in node_data.get("children", []):
            children.append(self._parse_toc(child))

        return LawTreeNode(
            id=node_data.get("id", ""),
            title=node_data.get("title", ""),
            index=node_data.get("index", 0),
            children=children
        )

    def get_article_text(self, law_name: str, article_num: str) -> List[Dict]:
        """
        通过必应搜索获取法条文本内容
        
        Args:
            law_name: 法律名称（如"民法典"）
            article_num: 条款号（如"第143条"）
            
        Returns:
            包含法条文本的字典列表
        """
        try:
            # 使用必应搜索
            keyword = f"{law_name} {article_num}"
            search_url = f"https://cn.bing.com/search?q={requests.utils.quote(keyword)}"
            
            resp = self.session.get(
                search_url,
                timeout=15,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            
            # 解析搜索结果
            from html import unescape
            text = resp.text
            
            # 提取包含"第X条"的片段
            results = []
            
            # 方法1: 提取包含条款号的 <p> 标签
            article_patterns = [
                r'第[一二三四五六七八九十百千万\d]+条[^<。]{0,200}?',
                r'第一百[一二三四五六七八九十\d]+[款项][^<。]{0,100}?',
            ]
            
            for pattern in article_patterns:
                matches = re.findall(pattern, text)
                for match in matches[:5]:
                    clean = re.sub(r'<[^>]+>', '', unescape(match)).strip()
                    clean = re.sub(r'\s+', ' ', clean)
                    if len(clean) > 30 and len(clean) < 500:
                        results.append({
                            "text": clean,
                            "source": "Bing Search"
                        })
            
            # 方法2: 从 <p> 标签中提取
            snippets = re.findall(r'<p[^>]*>([^<]{100,})', text)
            for snippet in snippets[:20]:
                clean = re.sub(r'<[^>]+>', '', unescape(snippet)).strip()
                clean = re.sub(r'\s+', ' ', clean)
                
                # 检查是否包含法条特征
                if ('第' in clean and '条' in clean and 
                    len(clean) > 50 and len(clean) < 600 and
                    not clean.startswith('http') and
                    not any(x in clean for x in ['百度百科', '百度知道', '视频', '图片'])):
                    results.append({
                        "text": clean[:500],
                        "source": "Bing Search"
                    })
            
            # 去重
            seen = set()
            unique_results = []
            for r in results:
                text = r['text']
                # 提取前100字符作为去重键
                key = text[:80]
                if key not in seen and len(text) > 50:
                    seen.add(key)
                    unique_results.append(r)
            
            return unique_results[:5]
            
        except Exception as e:
            print(f"获取法条文本失败: {e}")
            return []

    def get_enum_data(self) -> Optional[Dict]:
        """
        获取法律分类枚举数据
        GET /law-search/search/enumData

        Returns:
            分类枚举数据
        """
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/law-search/search/enumData",
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 200:
                return data.get("data")
            return None

        except Exception as e:
            print(f"获取枚举数据失败: {e}")
            return None

    def get_aggregate_data(self) -> Optional[Dict]:
        """
        获取统计数据
        GET /law-search/index/aggregateData

        Returns:
            统计数据
        """
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/law-search/index/aggregateData",
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 200:
                return data.get("data")
            return None

        except Exception as e:
            print(f"获取统计数据失败: {e}")
            return None


class LawSearchTool:
    """
    法条搜索工具类
    统一接口，供大模型 Function Calling 使用
    """

    def __init__(self, web_search_tool=None):
        self.flk_client = FLKApiClient()
        self.web_search = web_search_tool

    def search(
        self,
        query: str,
        num_results: int = 5,
        verify: bool = True
    ) -> str:
        """
        搜索法条并格式化输出

        Args:
            query: 搜索查询
            num_results: 返回结果数量
            verify: 是否到国家法律法规库验证

        Returns:
            格式化的搜索结果字符串
        """
        if verify:
            return self._search_with_verification(query, num_results)
        else:
            return self._search_without_verification(query, num_results)

    def _search_with_verification(self, query: str, num_results: int) -> str:
        """带验证的搜索"""
        # 1. 先用国家法律法规库 API 搜索
        results, total = self.flk_client.search_laws(
            keyword=query,
            page_size=num_results
        )

        if results:
            output = self._format_results(query, results, total, verified=True)
            return output

        # 2. 如果官方库没找到，用网页搜索补充
        if self.web_search:
            web_results = self.web_search.search_json(
                query=f"{query} site:flk.npc.gov.cn OR site:gov.cn 法律",
                num_results=num_results
            )
            if web_results:
                output = f"法条搜索结果：{query}\n"
                output += "=" * 50 + "\n"
                output += "⚠️ 以下结果来自网页搜索，未在国家法律法规库中直接验证\n\n"
                for i, r in enumerate(web_results, 1):
                    output += f"【{i}】{r.get('title', '')}\n"
                    output += f"    摘要：{r.get('snippet', '')}\n"
                    output += f"    链接：{r.get('url', '')}\n\n"
                output += f"建议访问 {FLKApiClient.BASE_URL} 进行确认\n"
                return output

        return f"未找到关于 '{query}' 的相关法条。"

    def _search_without_verification(self, query: str, num_results: int) -> str:
        """不带验证的搜索"""
        results, total = self.flk_client.search_laws(
            keyword=query,
            page_size=num_results
        )
        if results:
            return self._format_results(query, results, total, verified=False)
        return f"未找到关于 '{query}' 的相关法条。"

    def _format_results(
        self,
        query: str,
        results: List[LawSearchResult],
        total: int,
        verified: bool
    ) -> str:
        """格式化搜索结果"""
        output = f"法条搜索结果：{query}\n"
        output += "=" * 60 + "\n\n"

        for i, r in enumerate(results, 1):
            # 时效性标记
            if r.is_valid:
                status = "✅ 有效"
            elif r.sxx == 1:
                status = "❌ 已废止"
            elif r.sxx == 2:
                status = "⚠️ 已修改"
            elif r.sxx == 4:
                status = "🕐 尚未生效"
            else:
                status = "❓ 未知"

            output += f"【{i}】{r.title} {status}\n"
            output += f"    性质：{r.flxz}\n"
            output += f"    机关：{r.zdjg_name}\n"
            output += f"    公布：{r.gbrq}  施行：{r.sxrq}\n"

            if verified:
                output += f"    来源：{r.source}\n"

            output += f"    链接：{r.detail_url}\n\n"


        output += f"- 共找到 {total} 条相关法律法规\n"
        output += f"- 显示前 {len(results)} 条\n"

        # 统计时效性
        valid_count = sum(1 for r in results if r.is_valid)
        deprecated_count = sum(1 for r in results if r.sxx == 1)
        if deprecated_count > 0:
            output += f"- ⚠️ 其中有 {deprecated_count} 条已废止，请注意\n"

        return output

    def search_with_text(
        self,
        query: str,
        num_results: int = 5
    ) -> str:
        """
        搜索法条并尝试获取法条文本内容
        
        验证流程：
        1. 通过 flk.npc.gov.cn 验证法律存在性和时效性
        2. 通过网页搜索获取法条文本摘要
        3. 标注文本来源可靠性
        4. 添加免责声明，建议以官方原文为准
        
        Args:
            query: 搜索查询
            num_results: 返回结果数量
            
        Returns:
            格式化的搜索结果，包含法条文本
        """
        # 1. 用国家法律法规库搜索（核心验证）
        results, total = self.flk_client.search_laws(
            keyword=query,
            page_size=num_results
        )
        
        if not results:
            return f"未找到关于 '{query}' 的相关法条。"
        
        output = f"法条搜索结果：{query}\n"
        output += "=" * 60 + "\n"
        output += f"✅ 法律验证：国家法律法规数据库 (flk.npc.gov.cn)\n"
        output += f"⚠️ 文本摘要：通过网络搜索获取，仅供参考\n\n"
        
        for i, r in enumerate(results[:3], 1):
            # 时效性验证
            if r.is_valid:
                status = "✅ 有效"
            elif r.sxx == 1:
                status = "❌ 已废止"
            elif r.sxx == 2:
                status = "⚠️ 已修改"
            else:
                status = "❓ 未知"
            
            output += f"{'─' * 40}\n"
            output += f"【{i}】{r.title} {status}\n"
            output += f"    性质：{r.flxz} | 机关：{r.zdjg_name}\n"
            output += f"    公布：{r.gbrq} | 施行：{r.sxrq}\n"
            output += f"    官方详情：{r.detail_url}\n"
            
            # 2. 尝试获取法条文本（带可靠性评估）
            article_texts = self._get_article_texts(r.title, query)
            if article_texts:
                # 按可靠性排序
                reliable_texts = [t for t in article_texts if t.get('reliability') == 'high']
                other_texts = [t for t in article_texts if t.get('reliability') != 'high']
                
                # 只显示高可靠性的文本
                if reliable_texts:
                    output += f"\n    📜 法条文本摘要：\n"
                    for j, text_info in enumerate(reliable_texts[:1], 1):
                        text = text_info['text']
                        output += f"      {j}. {text[:500]}"
                        if len(text) > 500:
                            output += "..."
                        output += "\n"
                elif other_texts:
                    # 没有高可靠性来源，显示低可靠性来源但加强提示
                    output += f"\n    📜 法条文本摘要（仅供参考）：\n"
                    for j, text_info in enumerate(other_texts[:1], 1):
                        text = text_info['text']
                        output += f"      ⚠️ {text[:400]}"
                        if len(text) > 400:
                            output += "..."
                        output += "\n"
            else:
                output += f"\n    💡 提示：请访问官方详情页查看完整法条原文\n"
            
            output += "\n"
        
        output += f"{'─' * 40}\n"
        output += f"共找到 {total} 条相关法律法规\n\n"
        
        # 免责声明
        output += "=" * 60 + "\n"
        output += "⚠️ 免责声明：\n"
        output += "1. 法条文本摘要通过网络搜索获取，可能不完整或存在偏差\n"
        output += "2. 法律条文以国家法律法规数据库 (flk.npc.gov.cn) 官方原文为准\n"
        output += "3. 如需准确的法律依据，建议查阅官方原文或咨询专业律师\n"
        output += "4. 部分法律可能已被修订或废止，请注意时效性标注\n"
        
        return output
    
    def _get_article_texts(self, law_title: str, query: str) -> List[Dict]:
        """
        尝试获取法条文本
        
        Returns:
            包含文本和来源信息的字典列表，用于后续验证
        """
        import re
        
        # 从查询中提取条款号
        article_nums = re.findall(r'第[一二三四五六七八九十百千万\d]+条', query)
        if not article_nums:
            return []
        
        # 优先使用查询中包含的法律名称
        law_keywords = ['民法典', '合同法', '刑法', '婚姻法', '劳动法', '公司法', '民事诉讼法', '刑事诉讼法']
        search_law = None
        for kw in law_keywords:
            if kw in query:
                search_law = kw
                break
        if not search_law:
            for kw in law_keywords:
                if kw in law_title:
                    search_law = kw
                    break
        
        results = []
        for article_num in article_nums[:2]:
            law_to_use = search_law or '民法典'
            # 通过必应搜索获取文本
            article_results = self.flk_client.get_article_text(law_to_use, article_num)
            for result in article_results:
                if result.get('text'):
                    results.append({
                        "text": result['text'],
                        "source": result.get('source', 'Bing Search'),
                        "reliability": self._assess_reliability(result.get('text', ''))
                    })
        
        return results
    
    def _assess_reliability(self, text: str) -> str:
        """
        评估文本来源的可靠性
        
        Returns:
            'high', 'medium', 'low'
        """
        # 高可靠性来源关键词
        high_keywords = ['flk.npc.gov.cn', 'gov.cn', 'pkulaw', 'court.gov.cn', 
                        '法律', '法规', '最高人民法院', '全国人大常委会']
        
        # 低可靠性来源关键词
        low_keywords = ['百度知道', '百度经验', '知乎', '个人博客', 
                       '360doc', 'MBA智库', '民间']
        
        text_lower = text.lower()
        
        for kw in high_keywords:
            if kw in text_lower:
                return 'high'
        
        for kw in low_keywords:
            if kw in text_lower:
                return 'low'
        
        return 'medium'

    def get_detail(self, bbbs: str) -> Optional[str]:
        """
        获取法律详情的格式化输出

        Args:
            bbbs: 法律唯一 ID

        Returns:
            格式化的法律详情
        """
        detail = self.flk_client.get_law_detail(bbbs)
        if not detail:
            return None

        output = f"法律详情：{detail.get('title', '')}\n"
        output += "=" * 50 + "\n"
        output += f"性质：{detail.get('flxz', '')}\n"
        output += f"机关：{detail.get('zdjgName', '')}\n"
        output += f"公布：{detail.get('gbrq', '')}\n"
        output += f"施行：{detail.get('sxrq', '')}\n"

        # 目录
        content = detail.get("content")
        if content:
            output += "\n目录：\n"
            self._print_toc(content, output_lines=[])

        return output

    def _print_toc(self, node: Dict, depth: int = 0, output_lines: list = None):
        """递归打印目录树"""
        if output_lines is None:
            output_lines = []
        indent = "  " * depth
        title = node.get("title", "")
        children = node.get("children", [])
        child_count = len(children)
        output_lines.append(f"{indent}{'├─ ' if depth > 0 else ''}{title}")

        for child in children:
            self._print_toc(child, depth + 1, output_lines)

        return output_lines

    def get_tool_definition(self) -> Dict:
        """返回工具定义（用于 Function Calling）"""
        return {
            "type": "function",
            "function": {
                "name": "law_search",
                "description": (
                    "法条搜索工具，通过国家法律法规数据库（flk.npc.gov.cn）搜索中国法律法规。"
                    "当用户询问法律条款、法律解释、法律责任、权利义务、法律程序等问题时使用。"
                    "返回结果包含法律的时效性状态（有效/已废止/已修改），并提供官方链接。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "搜索查询，应包含法律名称或关键词。"
                                "例如：'民法典'、'劳动合同法 试用期'、'刑法 盗窃罪'、'消费者权益保护法'"
                            )
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "返回的搜索结果数量，默认为5",
                            "default": 5
                        },
                        "verify": {
                            "type": "boolean",
                            "description": "是否通过国家法律法规库验证，默认为true",
                            "default": True
                        }
                    },
                    "required": ["query"]
                }
            }
        }


# 便捷函数
def search_law(query: str, num_results: int = 5, verify: bool = True) -> str:
    """便捷的法条搜索函数"""
    tool = LawSearchTool()
    return tool.search(query, num_results, verify)


if __name__ == "__main__":
    client = FLKApiClient()

    print("=== 测试搜索建议 ===")
    suggests = client.search_suggest("民法典")
    for s in suggests:
        print(f"  {s}")

    print("\n=== 测试搜索法律 ===")
    results, total = client.search_laws("民法典", page_size=3)
    print(f"共 {total} 条结果：")
    for r in results:
        print(f"  [{r.status_text}] {r.title} ({r.flxz})")

    print("\n=== 测试获取详情 ===")
    if results:
        detail = client.get_law_detail(results[0].bbbs)
        if detail:
            print(f"标题：{detail.get('title')}")
            print(f"性质：{detail.get('flxz')}")
            print(f"机关：{detail.get('zdjgName')}")
            content = detail.get('content', {})
            print(f"目录层级数：{len(content.get('children', []))} 编")
