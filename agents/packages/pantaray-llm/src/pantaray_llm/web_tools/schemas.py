from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.profiles import (
    WEB_SEARCH_TOPIC_GENERAL,
    WebSearchCountry,
    WebSearchTopic,
)

type WebToolId = Literal["web_search", "web_extract", "web_crawl"]


class WebToolsRequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    action_id: str | None = None


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, pattern=r"\S")
    topic: WebSearchTopic | None = None
    country: WebSearchCountry | None = None

    @model_validator(mode="after")
    def validate_country_topic_combination(self) -> WebSearchArgs:
        if self.country is not None and self.topic not in (
            None,
            WEB_SEARCH_TOPIC_GENERAL,
        ):
            raise ValueError("country is only allowed when topic is general")
        return self


class WebExtractArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(min_length=1, max_length=5)
    query: str | None = Field(default=None, min_length=1, pattern=r"\S")


class WebCrawlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, pattern=r"\S")
    instructions: str | None = Field(default=None, min_length=1, pattern=r"\S")


type WebToolArgs = WebSearchArgs | WebExtractArgs | WebCrawlArgs


class WebToolsProxyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: WebToolId
    web_tool_profile: str = Field(min_length=1)
    args: WebToolArgs
    request_context: WebToolsRequestContext

    @model_validator(mode="after")
    def validate_args_shape(self) -> WebToolsProxyRequest:
        if self.tool_id == "web_search" and not isinstance(self.args, WebSearchArgs):
            raise ValueError("web_search args are invalid")
        if self.tool_id == "web_extract" and not isinstance(self.args, WebExtractArgs):
            raise ValueError("web_extract args are invalid")
        if self.tool_id == "web_crawl" and not isinstance(self.args, WebCrawlArgs):
            raise ValueError("web_crawl args are invalid")
        return self


class WebToolsProxyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1)
    status: str
    request_id: str
    response_time_ms: int
    result: dict[str, JSONValue] | None = None
    error: dict[str, JSONValue] | None = None


__all__ = [
    "WebCrawlArgs",
    "WebExtractArgs",
    "WebSearchArgs",
    "WebToolArgs",
    "WebToolId",
    "WebToolsProxyRequest",
    "WebToolsProxyResponse",
    "WebToolsRequestContext",
]
