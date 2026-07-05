"""
Совместимость Ragas 0.2.x с современным langchain-community.

Проблема: ragas.llms.base на верхнем уровне делает
    from langchain_community.chat_models.vertexai import ChatVertexAI
а свежие версии langchain-community удалили этот путь (Vertex вынесен в
отдельный пакет langchain-google-vertexai). Импорт падает ещё до того,
как ragas успевает что-либо сделать.

Мы работаем через OpenAI, Vertex AI не используется вообще. Поэтому до
импорта ragas подкладываем в sys.modules модуль-заглушку с пустыми
классами — этого достаточно, чтобы верхнеуровневый импорт прошёл.

Импортируйте ЭТОТ модуль ПЕРВЫМ, до любого `import ragas`.
"""
from __future__ import annotations

import sys
import types

_MODNAME = "langchain_community.chat_models.vertexai"


def install() -> None:
    try:
        __import__(_MODNAME)
        return  # путь существует — заглушка не нужна
    except Exception:
        pass
    import importlib
    stub = types.ModuleType(_MODNAME)
    stub.ChatVertexAI = type("ChatVertexAI", (), {})
    stub.VertexAI = type("VertexAI", (), {})
    sys.modules[_MODNAME] = stub
    try:  # чтобы `from ...chat_models.vertexai import X` находил заглушку и как атрибут родителя
        parent = importlib.import_module("langchain_community.chat_models")
        setattr(parent, "vertexai", stub)
    except Exception:
        pass


install()
