"""
联网搜索工具模块
支持多种搜索引擎：DuckDuckGo、Bing、Google（需要API Key）
"""

import json
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class SearchResult:
    """搜索结果数据结构"""
    title: str
    url: str
    snippet: str
    
    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet
        }


class SearchEngine(ABC):
    """搜索引擎基类"""
    
    @abstractmethod
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        pass


class DuckDuckGoSearch(SearchEngine):
    """
    DuckDuckGo 搜索引擎（免费，无需 API Key）
    使用 DuckDuckGo Instant Answer API
    """
    
    def __init__(self):
        self.base_url = "https://api.duckduckgo.com"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """执行搜索"""
        try:
            # 使用 DuckDuckGo 的 HTML 搜索接口
            params = {
                'q': query,
                'format': 'json',
                'no_html': 1,
                'skip_disambig': 1
            }
            
            response = requests.get(
                "https://api.duckduckgo.com/",
                params=params,
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            
            # 从 RelatedTopics 提取结果
            for item in data.get('RelatedTopics', [])[:num_results]:
                if 'Text' in item and 'FirstURL' in item:
                    results.append(SearchResult(
                        title=item.get('Text', '').split(' - ')[0],
                        url=item.get('FirstURL', ''),
                        snippet=item.get('Text', '')
                    ))
            
            # 如果结果不足，尝试使用网页搜索
            if len(results) < num_results:
                web_results = self._html_search(query, num_results - len(results))
                results.extend(web_results)
            
            return results[:num_results]
            
        except Exception as e:
            print(f"DuckDuckGo 搜索出错: {e}")
            return []
    
    def _html_search(self, query: str, num_results: int) -> List[SearchResult]:
        """备用 HTML 搜索方法"""
        try:
            # 使用 duckduckgo-html 库的方式
            url = "https://html.duckduckgo.com/html/"
            params = {'q': query}
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            response = requests.post(url, data=params, headers=headers, timeout=15)
            response.raise_for_status()
            
            # 简单解析 HTML（生产环境建议用 BeautifulSoup）
            results = []
            lines = response.text.split('\n')
            
            for i, line in enumerate(lines):
                if 'result__a' in line and len(results) < num_results:
                    # 提取标题
                    title_start = line.find('">') + 2
                    title_end = line.find('</a>')
                    if title_start > 1 and title_end > title_start:
                        title = line[title_start:title_end].strip()
                        
                        # 查找 URL
                        url_start = line.find('href="') + 6
                        url_end = line.find('"', url_start)
                        if url_start > 5 and url_end > url_start:
                            result_url = line[url_start:url_end]
                            
                            # 查找摘要
                            snippet = ""
                            for j in range(i+1, min(i+10, len(lines))):
                                if 'result__snippet' in lines[j]:
                                    snip_start = lines[j].find('">') + 2
                                    snip_end = lines[j].find('</a>')
                                    if snip_start > 1 and snip_end > snip_start:
                                        snippet = lines[j][snip_start:snip_end].strip()
                                    break
                            
                            results.append(SearchResult(
                                title=title,
                                url=result_url,
                                snippet=snippet if snippet else title
                            ))
            
            return results
            
        except Exception as e:
            print(f"HTML 搜索出错: {e}")
            return []


class BingSearch(SearchEngine):
    """
    Bing 搜索引擎（需要 API Key）
    注册：https://www.microsoft.com/en-us/bing/apis
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.bing.microsoft.com/v7.0/search"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        try:
            headers = {"Ocp-Apim-Subscription-Key": self.api_key}
            params = {
                "q": query,
                "count": num_results,
                "mkt": "zh-CN"
            }
            
            response = requests.get(
                self.endpoint,
                headers=headers,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("webPages", {}).get("value", []):
                results.append(SearchResult(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", "")
                ))
            
            return results
            
        except Exception as e:
            print(f"Bing 搜索出错: {e}")
            return []


class GoogleSearch(SearchEngine):
    """
    Google 搜索引擎（需要 API Key 和 Search Engine ID）
    注册：https://developers.google.com/custom-search/v1/introduction
    """
    
    def __init__(self, api_key: str, search_engine_id: str):
        self.api_key = api_key
        self.search_engine_id = search_engine_id
        self.endpoint = "https://www.googleapis.com/customsearch/v1"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        try:
            params = {
                "key": self.api_key,
                "cx": self.search_engine_id,
                "q": query,
                "num": num_results
            }
            
            response = requests.get(
                self.endpoint,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("items", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", "")
                ))
            
            return results
            
        except Exception as e:
            print(f"Google 搜索出错: {e}")
            return []


class WebSearchTool:
    """
    联网搜索工具类
    统一接口，支持多种搜索引擎
    """
    
    def __init__(self, engine: str = "duckduckgo", **kwargs):
        """
        初始化搜索工具
        
        Args:
            engine: 搜索引擎类型 ("duckduckgo", "bing", "google")
            **kwargs: 搜索引擎配置参数
        """
        self.engine_name = engine
        
        if engine == "duckduckgo":
            self.engine = DuckDuckGoSearch()
        elif engine == "bing":
            api_key = kwargs.get("api_key") or kwargs.get("bing_api_key")
            if not api_key:
                raise ValueError("Bing 搜索需要提供 api_key")
            self.engine = BingSearch(api_key)
        elif engine == "google":
            api_key = kwargs.get("api_key") or kwargs.get("google_api_key")
            search_engine_id = kwargs.get("search_engine_id") or kwargs.get("cx")
            if not api_key or not search_engine_id:
                raise ValueError("Google 搜索需要提供 api_key 和 search_engine_id")
            self.engine = GoogleSearch(api_key, search_engine_id)
        else:
            raise ValueError(f"不支持的搜索引擎: {engine}")
    
    def search(self, query: str, num_results: int = 5) -> str:
        """
        执行搜索并返回格式化结果
        
        Args:
            query: 搜索查询
            num_results: 返回结果数量
            
        Returns:
            格式化的搜索结果字符串
        """
        results = self.engine.search(query, num_results)
        
        if not results:
            return f"未找到关于 '{query}' 的相关结果。"
        
        output = f"搜索 '{query}' 的结果：\n\n"
        for i, result in enumerate(results, 1):
            output += f"【{i}】{result.title}\n"
            output += f"    链接：{result.url}\n"
            output += f"    摘要：{result.snippet}\n\n"
        
        return output
    
    def search_json(self, query: str, num_results: int = 5) -> List[Dict]:
        """执行搜索并返回 JSON 格式结果"""
        results = self.engine.search(query, num_results)
        return [r.to_dict() for r in results]
    
    def get_tool_definition(self) -> Dict:
        """
        返回工具定义（用于 Function Calling）
        兼容 OpenAI 和 Ollama 格式
        """
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索工具，用于搜索互联网上的最新信息。当用户询问实时信息、新闻、天气、股价等需要联网的内容时使用此工具。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询关键词，应该简洁明确"
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "返回的搜索结果数量，默认为5",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            }
        }


# 便捷函数
def create_search_tool(engine: str = "duckduckgo", **kwargs) -> WebSearchTool:
    """创建搜索工具的便捷函数"""
    return WebSearchTool(engine, **kwargs)


if __name__ == "__main__":
    # 测试搜索
    tool = WebSearchTool("duckduckgo")
    print(tool.search("Python 最新版本", 3))
